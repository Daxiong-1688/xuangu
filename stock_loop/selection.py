from __future__ import annotations

from typing import Any

from .utils import clamp, safe_float


SELECTED_FIELDS = [
    "date",
    "stock_code",
    "stock_name",
    "sector",
    "selected_price",
    "strategy_version",
    "total_score",
    "hot_sector_score",
    "capital_flow_score",
    "technical_score",
    "risk_score",
    "reason_summary",
    "observation_period",
    "risk_level",
    "signals",
    "structure_tags",
    "technical_structure",
    "pool_status",
    "data_quality_note",
]


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def _source_structure_details(candidate: dict[str, Any]) -> list[str]:
    detail_map = (
        ("结构状态", "source_structure_status"),
        ("趋势动量", "source_momentum_summary"),
        ("量价K线", "source_volume_price"),
        ("缠论结构", "source_chan_structure"),
        ("位置风险", "source_position_risk"),
        ("观察位", "source_follow_up"),
    )
    details = []
    for label, key in detail_map:
        value = str(candidate.get(key) or "").strip()
        if value and value not in {"暂无", "待确认"}:
            details.append(f"来源{label}提示（未作为打分依据）：{value}")
    return details


def evaluate_technical_structure(candidate: dict[str, Any]) -> dict[str, Any]:
    """Score technical structure only from real fields available in the snapshot.

    Trend, moving-average and 52-week position can be scored from close/MA/return
    fields. Candlestick, K-line combination, volume-price and Chan dimensions need
    real OHLCV or confirmed structure fields; missing data is reported as neutral
    instead of inferred from signals.
    """

    provided = safe_float(candidate.get("technical_score"))
    open_price = safe_float(candidate.get("open"))
    high = safe_float(candidate.get("high"))
    low = safe_float(candidate.get("low"))
    close = safe_float(candidate.get("close"))
    ma20 = safe_float(candidate.get("ma20"))
    ma60 = safe_float(candidate.get("ma60"))
    p5 = safe_float(candidate.get("pct_change_5"))
    p20 = safe_float(candidate.get("pct_change_20"))
    p60 = safe_float(candidate.get("pct_change_60"))
    high52 = safe_float(candidate.get("high_52w"))
    volume_ratio = safe_float(candidate.get("volume_ratio"))
    volume = safe_float(candidate.get("volume"))
    amount = safe_float(candidate.get("amount"))
    turnover_rate = safe_float(candidate.get("turnover_rate"))
    has_ohlc = all(value is not None for value in (open_price, high, low, close)) and (
        high is not None and low is not None and high >= low
    )
    has_volume_field = any(
        value is not None for value in (volume_ratio, volume, amount, turnover_rate)
    )
    score = 50.0
    details: list[str] = []
    tags: list[str] = []

    if p20 is not None and p60 is not None:
        if p20 > 0 and p60 > 0:
            score += 10
            details.append("趋势：20/60日趋势同向为正")
            tags.append("趋势延续")
        elif p20 < 0 and p60 < 0:
            score -= 10
            details.append("趋势：20/60日趋势同向偏弱")
        else:
            score += 2
            details.append("趋势：中短周期方向分化，需等结构确认")
    elif p20 is not None:
        score += max(-8, min(8, p20 * 0.5))
        details.append(f"趋势：20日涨跌幅 {p20:.2f}%")

    if p5 is not None:
        if 0 <= p5 <= 8:
            score += 7
            details.append("短线动量：温和增强")
            tags.append("动量温和")
        elif 8 < p5 <= 15:
            score += 4
            details.append("短线动量：偏强但需防追高")
            tags.append("短线偏强")
        elif p5 > 15:
            score -= 7
            details.append("短线动量：涨幅过快，K线加速风险上升")
            tags.append("K线加速")
        else:
            score -= 4
            details.append("短线动量：短期回落")

    if close is not None and ma20 is not None:
        if close > ma20:
            score += 8
            details.append("均线：收盘价站上20日线")
        else:
            score -= 6
            details.append("均线：收盘价仍在20日线下方")
    if ma20 is not None and ma60 is not None:
        if ma20 > ma60:
            score += 10
            details.append("均线：20日线高于60日线，多头结构占优")
            tags.append("均线多头")
        else:
            score -= 7
            details.append("均线：20/60日均线结构尚未转强")

    if close is not None and high52:
        ratio = close / high52
        if 0.72 <= ratio <= 0.94:
            score += 7
            details.append("形态位置：处于前高下方的中位趋势区")
            tags.append("中位趋势")
        elif ratio > 0.98:
            score -= 6
            details.append("形态位置：接近52周前高，突破失败风险放大")
            tags.append("接近前高")
        elif ratio < 0.65:
            score -= 3
            details.append("形态位置：距离前高较远，先按低位修复观察")

    if volume_ratio is not None:
        if volume_ratio >= 1.8 and (p5 or 0) > 12:
            score -= 4
            details.append("量价：真实量比显示高涨幅叠加放量，留意放量滞涨")
        elif volume_ratio >= 1.2 and (p5 or 0) > 0:
            score += 6
            details.append("量价：真实量比显示放量配合上涨")
            tags.append("量价配合")
        elif volume_ratio < 0.85 and (p5 or 0) < 0:
            score -= 5
            details.append("量价：真实量比显示缩量回落或承接不足")
    elif has_volume_field:
        details.append("量价：有真实成交/换手字段但缺少量比基准，不参与量价加减分")
    else:
        details.append("量价：缺少真实成交量/成交额/换手率字段，不参与量价加减分")

    if has_ohlc:
        assert open_price is not None and high is not None and low is not None and close is not None
        day_range = high - low
        close_position = (close - low) / day_range if day_range > 0 else 0.5
        upper_shadow = high - max(open_price, close)
        lower_shadow = min(open_price, close) - low
        if close > open_price and close_position >= 0.7:
            score += 3
            details.append("蜡烛图：真实OHLC显示阳线且收于日内高位")
            tags.append("阳线收强")
        elif close < open_price and close_position <= 0.35:
            score -= 3
            details.append("蜡烛图：真实OHLC显示阴线且收盘偏低")
        if day_range > 0 and upper_shadow / day_range >= 0.45:
            score -= 3
            details.append("K线影线：真实OHLC显示上影线偏长，追高风险增加")
        if day_range > 0 and lower_shadow / day_range >= 0.45 and close >= open_price:
            score += 2
            details.append("K线影线：真实OHLC显示下影承接，作为企稳观察")
    else:
        details.append("K线/蜡烛图：缺少真实 open/high/low，不参与K线形态加减分")

    confirmed_chan = str(candidate.get("chan_structure_confirmed") or "").strip()
    if confirmed_chan:
        score += 4
        details.append(f"缠论：{confirmed_chan}")
        tags.append("缠论确认")
    else:
        details.append("缠论：缺少连续OHLC分型/笔/中枢数据，不参与缠论加减分")

    source_details = _source_structure_details(candidate)
    if source_details:
        details.extend(source_details)

    local_score = clamp(score)
    final_score = local_score
    if provided is not None:
        final_score = clamp(provided * 0.55 + local_score * 0.45)
    unique_tags = list(dict.fromkeys(tags))
    return {
        "score": round(final_score, 2),
        "local_score": round(local_score, 2),
        "details": details[:12],
        "tags": unique_tags[:6],
        "summary": "；".join(details[:10]) if details else "技术结构待确认",
    }


def calculate_technical_score(candidate: dict[str, Any]) -> float:
    return float(evaluate_technical_structure(candidate)["score"])


def data_coverage(candidates: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    total = max(1, len(candidates))
    return {
        field: round(
            sum(safe_float(candidate.get(field)) is not None for candidate in candidates) / total,
            4,
        )
        for field in fields
    }


def select_stocks(
    market_data: dict[str, Any],
    strategy: dict[str, Any],
    run_date: str,
    observation_periods: list[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = list(market_data.get("candidates", []))
    quality_config = strategy.get("data_quality", {})
    required_fields = quality_config.get(
        "required_technical_fields", ["close", "pct_change_20", "ma20", "ma60"]
    )
    coverage = data_coverage(candidates, required_fields)
    minimum_coverage = float(quality_config.get("minimum_required_field_coverage", 0.6))
    formal_pool = bool(candidates) and all(value >= minimum_coverage for value in coverage.values())
    pool_status = "formal_research_pool" if formal_pool else "candidate_observation_pool"
    thresholds = strategy.get("score_thresholds", {})
    weights = strategy.get("weights", {})
    scored: list[dict[str, Any]] = []

    for candidate in candidates:
        code = str(candidate.get("stock_code", ""))
        name = str(candidate.get("stock_name", ""))
        if not code or not name or code.endswith(".BJ") or "ST" in name.upper() or "退" in name:
            continue
        close = safe_float(candidate.get("close"))
        if close is None or close <= 0:
            continue
        hot = safe_float(candidate.get("hot_sector_score"), 50.0) or 50.0
        capital = safe_float(candidate.get("capital_flow_score"), 50.0) or 50.0
        technical_view = evaluate_technical_structure(candidate)
        technical = float(technical_view["score"])
        risk = safe_float(candidate.get("risk_score"), 50.0) or 50.0
        total = (
            hot * float(weights.get("hot_sector_score", 0.25))
            + capital * float(weights.get("capital_flow_score", 0.20))
            + technical * float(weights.get("technical_score", 0.45))
            + (100 - risk) * float(weights.get("risk_control_score", 0.10))
        )
        if risk > float(thresholds.get("maximum_risk_score", 70)):
            continue
        if formal_pool and technical < float(thresholds.get("minimum_technical_score", 50)):
            continue
        if formal_pool and total < float(thresholds.get("minimum_total_score", 55)):
            continue
        signals = _as_list(candidate.get("signals", []))
        signals = list(dict.fromkeys([*signals, *technical_view["tags"]]))
        reason_parts = []
        if hot >= 65:
            reason_parts.append("热点质量较强")
        if capital >= 62:
            reason_parts.append(
                "资讯情绪维度较积极"
                if candidate.get("capital_flow_is_inferred")
                else "资金维度较积极"
            )
        if technical >= 65:
            reason_parts.append("技术结构相对完整")
        if technical_view["tags"]:
            reason_parts.append("结构标签：" + "、".join(technical_view["tags"][:3]))
        if candidate.get("reason_from_source"):
            reason_parts.append(str(candidate["reason_from_source"]))
        if not reason_parts:
            reason_parts.append("进入候选观察池，等待更多结构确认")
        risk_level = "高" if risk >= 65 else "中" if risk >= 40 else "低"
        scored.append(
            {
                "date": run_date,
                "stock_code": code,
                "stock_name": name,
                "sector": candidate.get("sector", "待确认"),
                "selected_price": round(close, 4),
                "strategy_version": strategy.get("strategy_version", "unknown"),
                "total_score": round(total, 2),
                "hot_sector_score": round(hot, 2),
                "capital_flow_score": round(capital, 2),
                "technical_score": round(technical, 2),
                "risk_score": round(risk, 2),
                "reason_summary": "；".join(reason_parts)[:240],
                "observation_period": "/".join(str(item) for item in observation_periods) + "个交易日",
                "risk_level": risk_level,
                "signals": ";".join(signals),
                "structure_tags": ";".join(technical_view["tags"]),
                "technical_structure": str(technical_view["summary"])[:500],
                "pool_status": pool_status,
                "data_quality_note": (
                    "核心趋势字段覆盖达标"
                    if formal_pool
                    else "核心趋势字段覆盖不足，降级为候选观察池"
                ),
                "_candidate": candidate,
            }
        )
    scored.sort(key=lambda row: row["total_score"], reverse=True)
    selected = scored[: int(strategy.get("pool_size", 5))]
    quality = {
        "formal_pool": formal_pool,
        "pool_status": pool_status,
        "required_fields": required_fields,
        "coverage": coverage,
        "minimum_coverage": minimum_coverage,
        "selected_count": len(selected),
        "candidate_count": len(candidates),
    }
    return selected, quality

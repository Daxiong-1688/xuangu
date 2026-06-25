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


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _medium_return_component(value: float) -> float:
    if value < 0:
        return _bounded(value * 1.2, -12.0, 0.0)
    if value <= 5:
        return 4.0 + value * 1.6
    if value <= 20:
        return 12.0 + (value - 5.0) * 0.25
    return 15.0 - _bounded((value - 20.0) * 0.5, 0.0, 8.0)


def _long_return_component(value: float) -> float:
    if value < 0:
        return _bounded(value * 0.7, -10.0, 0.0)
    if value <= 10:
        return 3.0 + value * 0.7
    if value <= 40:
        return 10.0 + (value - 10.0) * 0.12
    return 13.0 - _bounded((value - 40.0) * 0.15, 0.0, 6.0)


def _short_return_component(value: float) -> float:
    if value < -8:
        return -7.0
    if value < 0:
        return value * 0.5
    if value <= 6:
        return 4.0 + value * 0.6
    if value <= 12:
        return 8.0 - (value - 6.0) * 0.15
    if value <= 18:
        return 6.0 - (value - 12.0) * 0.9
    return -_bounded((value - 18.0) * 0.5 + 2.0, 2.0, 8.0)


def _ma20_component(close: float, ma20: float) -> float:
    distance = (close / ma20 - 1.0) * 100.0
    if distance >= 0:
        return 4.0 + _bounded(distance * 0.45, 0.0, 5.0) - _bounded(
            (distance - 18.0) * 0.35, 0.0, 5.0
        )
    return -4.0 + _bounded(distance * 0.7, -10.0, 0.0)


def _ma_gap_component(ma20: float, ma60: float) -> float:
    gap = (ma20 / ma60 - 1.0) * 100.0
    if gap >= 0:
        return 5.0 + _bounded(gap * 0.35, 0.0, 6.0) - _bounded(
            (gap - 25.0) * 0.2, 0.0, 5.0
        )
    return -5.0 + _bounded(gap * 0.5, -10.0, 0.0)


def _position_component(close: float, high52: float) -> float:
    ratio = close / high52
    if 0.72 <= ratio <= 0.88:
        return 6.0 + (ratio - 0.72) / 0.16 * 4.0
    if 0.88 < ratio <= 0.95:
        return 9.0 - (ratio - 0.88) / 0.07 * 5.0
    if 0.65 <= ratio < 0.72:
        return 2.0 + (ratio - 0.65) / 0.07 * 4.0
    if ratio > 0.95:
        return 2.0 - _bounded((ratio - 0.95) * 80.0, 0.0, 8.0)
    return -4.0


def _rank_tiebreaker(candidate: dict[str, Any], technical_view: dict[str, Any]) -> float:
    close = safe_float(candidate.get("close"))
    ma20 = safe_float(candidate.get("ma20"))
    ma60 = safe_float(candidate.get("ma60"))
    high52 = safe_float(candidate.get("high_52w"))
    p5 = safe_float(candidate.get("pct_change_5"), 0.0) or 0.0
    p20 = safe_float(candidate.get("pct_change_20"), 0.0) or 0.0
    p60 = safe_float(candidate.get("pct_change_60"), 0.0) or 0.0
    value = float(technical_view.get("local_score", 0.0))
    value += _bounded(p20, -20.0, 30.0) * 0.08
    value += _bounded(p60, -30.0, 60.0) * 0.04
    value -= abs(p5 - 9.0) * 0.03
    if close is not None and ma20:
        value += _bounded((close / ma20 - 1.0) * 100.0, -20.0, 30.0) * 0.03
    if ma20 is not None and ma60:
        value += _bounded((ma20 / ma60 - 1.0) * 100.0, -20.0, 30.0) * 0.02
    if close is not None and high52:
        value -= abs(close / high52 - 0.82) * 2.0
    return round(value, 6)


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
    score = 45.0
    details: list[str] = []
    tags: list[str] = []

    if p20 is not None and p60 is not None:
        medium_component = _medium_return_component(p20)
        long_component = _long_return_component(p60)
        score += medium_component + long_component
        if p20 > 0 and p60 > 0:
            details.append(
                f"趋势：20日 {p20:.2f}% / 60日 {p60:.2f}%，连续动量分层加权"
            )
            tags.append("趋势延续")
        elif p20 < 0 and p60 < 0:
            details.append(
                f"趋势：20日 {p20:.2f}% / 60日 {p60:.2f}%，中期趋势同向偏弱"
            )
        else:
            details.append(
                f"趋势：20日 {p20:.2f}% / 60日 {p60:.2f}%，中短周期方向分化"
            )
    elif p20 is not None:
        score += _medium_return_component(p20)
        details.append(f"趋势：20日涨跌幅 {p20:.2f}%")

    if p5 is not None:
        short_component = _short_return_component(p5)
        score += short_component
        if 0 <= p5 <= 8:
            details.append(f"短线动量：5日 {p5:.2f}%，温和增强")
            tags.append("动量温和")
        elif 8 < p5 <= 15:
            details.append(f"短线动量：5日 {p5:.2f}%，偏强但需防追高")
            tags.append("短线偏强")
        elif p5 > 15:
            details.append(f"短线动量：5日 {p5:.2f}%，涨幅过快，短线加速风险上升")
            tags.append("短线加速")
        else:
            details.append(f"短线动量：5日 {p5:.2f}%，短期回落")

    if close is not None and ma20 is not None:
        ma20_component = _ma20_component(close, ma20)
        score += ma20_component
        distance = (close / ma20 - 1.0) * 100.0
        if close > ma20:
            details.append(f"均线：收盘价高于20日线 {distance:.2f}%")
        else:
            details.append(f"均线：收盘价低于20日线 {abs(distance):.2f}%")
    if ma20 is not None and ma60 is not None:
        gap_component = _ma_gap_component(ma20, ma60)
        score += gap_component
        gap = (ma20 / ma60 - 1.0) * 100.0
        if ma20 > ma60:
            details.append(f"均线：20日线高于60日线 {gap:.2f}%，多头结构占优")
            tags.append("均线多头")
        else:
            details.append(f"均线：20日线低于60日线 {abs(gap):.2f}%，结构尚未转强")

    if close is not None and high52:
        ratio = close / high52
        score += _position_component(close, high52)
        if 0.72 <= ratio <= 0.94:
            details.append(f"形态位置：位于52周高点 {ratio * 100:.2f}%，中位趋势区")
            tags.append("中位趋势")
        elif ratio > 0.98:
            details.append(f"形态位置：位于52周高点 {ratio * 100:.2f}%，突破失败风险放大")
            tags.append("接近前高")
        elif ratio < 0.65:
            details.append(f"形态位置：仅为52周高点 {ratio * 100:.2f}%，先按低位修复观察")
        else:
            details.append(f"形态位置：位于52周高点 {ratio * 100:.2f}%，位置分保持中性")

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
        final_score = clamp(provided * 0.25 + local_score * 0.75)
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
                "_raw_total_score": total,
                "_rank_tiebreaker": _rank_tiebreaker(candidate, technical_view),
                "_candidate": candidate,
            }
        )
    scored.sort(
        key=lambda row: (
            row.get("_raw_total_score", 0.0),
            row.get("technical_score", 0.0),
            row.get("_rank_tiebreaker", 0.0),
        ),
        reverse=True,
    )
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

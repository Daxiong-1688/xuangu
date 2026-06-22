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
    "pool_status",
    "data_quality_note",
]


def calculate_technical_score(candidate: dict[str, Any]) -> float:
    provided = safe_float(candidate.get("technical_score"))
    if provided is not None:
        return clamp(provided)
    close = safe_float(candidate.get("close"))
    ma20 = safe_float(candidate.get("ma20"))
    ma60 = safe_float(candidate.get("ma60"))
    p5 = safe_float(candidate.get("pct_change_5"))
    p20 = safe_float(candidate.get("pct_change_20"))
    high52 = safe_float(candidate.get("high_52w"))
    volume = safe_float(candidate.get("volume_ratio"), 1.0) or 1.0
    score = 45.0
    if close is not None and ma20 is not None:
        score += 12 if close > ma20 else -8
    if ma20 is not None and ma60 is not None:
        score += 14 if ma20 > ma60 else -10
    if p20 is not None:
        score += max(-12, min(15, p20 * 0.8))
    if p5 is not None and p5 > 15:
        score -= 12
    elif p5 is not None and p5 > 0:
        score += min(8, p5 * 0.7)
    if close is not None and high52:
        ratio = close / high52
        if 0.72 <= ratio <= 0.94:
            score += 8
        elif ratio > 0.98:
            score -= 7
    if volume >= 1.2:
        score += 5
    return round(clamp(score), 2)


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
        technical = calculate_technical_score(candidate)
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
        signals = candidate.get("signals", [])
        if isinstance(signals, str):
            signals = [item.strip() for item in signals.split(";") if item.strip()]
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

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from .utils import list_run_dates, parse_date, read_csv, read_json, safe_float, write_csv


RETURN_FIELDS = [
    "selection_date",
    "evaluation_date",
    "strategy_version",
    "stock_code",
    "stock_name",
    "sector",
    "horizon_days",
    "selected_price",
    "observed_price",
    "return_pct",
    "max_gain_pct",
    "max_drawdown_pct",
    "benchmark_return_pct",
    "sector_return_pct",
    "outperformed_index",
    "outperformed_sector",
    "risk_triggered",
    "reason_valid",
    "signals",
    "status",
]

AGG_FIELDS = [
    "as_of_date",
    "strategy_version",
    "horizon_days",
    "evaluated_count",
    "success_count",
    "rate_pct",
]

SIGNAL_FIELDS = [
    "as_of_date",
    "strategy_version",
    "signal",
    "horizon_days",
    "sample_count",
    "positive_count",
    "win_count",
    "positive_rate_pct",
    "win_rate_pct",
    "average_return_pct",
    "average_max_drawdown_pct",
]


def _price(
    snapshot: dict[str, Any],
    category: str,
    key: str,
    expected_date: date | None = None,
) -> float | None:
    value = snapshot.get("price_book", {}).get(category, {}).get(key)
    if isinstance(value, dict):
        trade_date = value.get("trade_date")
        if expected_date is not None and trade_date:
            try:
                if parse_date(str(trade_date)) != expected_date:
                    return None
            except ValueError:
                return None
        value = value.get("close")
    return safe_float(value)


def _return(start: float | None, end: float | None) -> float | None:
    if start in (None, 0) or end is None:
        return None
    return round((end / start - 1) * 100, 4)


def _excursions(selected_price: float, prices: list[float]) -> tuple[float, float]:
    path = [selected_price] + prices
    max_gain = max((value / selected_price - 1) * 100 for value in path)
    peak = path[0]
    max_drawdown = 0.0
    for value in path:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, (value / peak - 1) * 100)
    return round(max_gain, 4), round(max_drawdown, 4)


def build_return_tracking(
    root: Path,
    observation_periods: list[int],
    benchmark_code: str,
    risk_stop_drawdown_pct: float,
    as_of_date: date | None = None,
) -> list[dict[str, Any]]:
    run_dates = [
        value
        for value in list_run_dates(root)
        if as_of_date is None or value <= as_of_date
    ]
    snapshots = {
        value: read_json(root / "runs" / value.isoformat() / "market_data.json", {})
        for value in run_dates
    }
    rows: list[dict[str, Any]] = []
    for selection_date in run_dates:
        selections = read_csv(root / "runs" / selection_date.isoformat() / "selected_stocks.csv")
        later_dates = [value for value in run_dates if value > selection_date]
        selected_snapshot = snapshots.get(selection_date, {})
        for selection in selections:
            selected_price = safe_float(selection.get("selected_price"))
            if selected_price is None:
                continue
            code = selection.get("stock_code", "")
            sector = selection.get("sector", "")
            benchmark_start = _price(selected_snapshot, "indices", benchmark_code, selection_date)
            sector_start = _price(selected_snapshot, "sectors", sector, selection_date)
            for horizon in observation_periods:
                base = {
                    "selection_date": selection_date.isoformat(),
                    "evaluation_date": "",
                    "strategy_version": selection.get("strategy_version", ""),
                    "stock_code": code,
                    "stock_name": selection.get("stock_name", ""),
                    "sector": sector,
                    "horizon_days": horizon,
                    "selected_price": selected_price,
                    "observed_price": "",
                    "return_pct": "",
                    "max_gain_pct": "",
                    "max_drawdown_pct": "",
                    "benchmark_return_pct": "",
                    "sector_return_pct": "",
                    "outperformed_index": "",
                    "outperformed_sector": "",
                    "risk_triggered": "",
                    "reason_valid": "",
                    "signals": selection.get("signals", ""),
                    "status": "pending",
                }
                if len(later_dates) < horizon:
                    rows.append(base)
                    continue
                evaluation_date = later_dates[horizon - 1]
                window_dates = later_dates[:horizon]
                path = [
                    _price(snapshots.get(value, {}), "stocks", code, value)
                    for value in window_dates
                ]
                valid_path = [value for value in path if value is not None]
                observed = path[-1]
                if observed is None or not valid_path:
                    base["evaluation_date"] = evaluation_date.isoformat()
                    base["status"] = "price_unavailable"
                    rows.append(base)
                    continue
                return_pct = _return(selected_price, observed)
                max_gain, max_drawdown = _excursions(selected_price, valid_path)
                evaluation_snapshot = snapshots.get(evaluation_date, {})
                benchmark_return = _return(
                    benchmark_start,
                    _price(evaluation_snapshot, "indices", benchmark_code, evaluation_date),
                )
                sector_return = _return(
                    sector_start, _price(evaluation_snapshot, "sectors", sector, evaluation_date)
                )
                base.update(
                    {
                        "evaluation_date": evaluation_date.isoformat(),
                        "observed_price": observed,
                        "return_pct": return_pct,
                        "max_gain_pct": max_gain,
                        "max_drawdown_pct": max_drawdown,
                        "benchmark_return_pct": benchmark_return,
                        "sector_return_pct": sector_return,
                        "outperformed_index": (
                            "" if benchmark_return is None else return_pct > benchmark_return
                        ),
                        "outperformed_sector": (
                            "" if sector_return is None else return_pct > sector_return
                        ),
                        "risk_triggered": max_drawdown <= risk_stop_drawdown_pct,
                        "reason_valid": return_pct > 0,
                        "status": "completed",
                    }
                )
                rows.append(base)
    return rows


def _aggregate_rates(
    completed: list[dict[str, Any]],
    as_of_date: str,
    success_rule,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in completed:
        groups[(str(row["strategy_version"]), int(row["horizon_days"]))].append(row)
    rows = []
    for (version, horizon), items in sorted(groups.items()):
        successes = sum(1 for item in items if success_rule(item))
        rows.append(
            {
                "as_of_date": as_of_date,
                "strategy_version": version,
                "horizon_days": horizon,
                "evaluated_count": len(items),
                "success_count": successes,
                "rate_pct": round(successes / len(items) * 100, 2),
            }
        )
    return rows


def _signal_rows(
    completed: list[dict[str, Any]],
    as_of_date: str,
    win_threshold: float,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in completed:
        signals = [item.strip() for item in str(row.get("signals", "")).split(";") if item.strip()]
        for signal in signals:
            groups[(str(row["strategy_version"]), signal, int(row["horizon_days"]))].append(row)
    output = []
    for (version, signal, horizon), items in sorted(groups.items()):
        returns = [safe_float(item.get("return_pct"), 0.0) or 0.0 for item in items]
        drawdowns = [safe_float(item.get("max_drawdown_pct"), 0.0) or 0.0 for item in items]
        positive = sum(value > 0 for value in returns)
        wins = sum(value >= win_threshold for value in returns)
        output.append(
            {
                "as_of_date": as_of_date,
                "strategy_version": version,
                "signal": signal,
                "horizon_days": horizon,
                "sample_count": len(items),
                "positive_count": positive,
                "win_count": wins,
                "positive_rate_pct": round(positive / len(items) * 100, 2),
                "win_rate_pct": round(wins / len(items) * 100, 2),
                "average_return_pct": round(sum(returns) / len(returns), 4),
                "average_max_drawdown_pct": round(sum(drawdowns) / len(drawdowns), 4),
            }
        )
    return output


def update_all_metrics(
    root: Path,
    run_config: dict[str, Any],
    strategy: dict[str, Any],
    as_of_date: date,
) -> dict[str, Any]:
    periods = [int(value) for value in run_config.get("observation_periods", [1, 3, 5, 10])]
    benchmark = run_config.get("benchmark_code", "000300.SH")
    review_config = strategy.get("review", {})
    risk_config = strategy.get("risk", {})
    direction_threshold = float(review_config.get("direction_accuracy_threshold_pct", 0.0))
    win_threshold = float(review_config.get("win_return_threshold_pct", 1.0))
    rows = build_return_tracking(
        root,
        periods,
        benchmark,
        float(risk_config.get("risk_stop_drawdown_pct", -8.0)),
        as_of_date,
    )
    write_csv(root / "metrics" / "return_tracking.csv", RETURN_FIELDS, rows)
    completed = [row for row in rows if row.get("status") == "completed"]
    accuracy = _aggregate_rates(
        completed,
        as_of_date.isoformat(),
        lambda row: safe_float(row.get("return_pct"), -999.0) > direction_threshold,
    )
    win_rate = _aggregate_rates(
        completed,
        as_of_date.isoformat(),
        lambda row: safe_float(row.get("return_pct"), -999.0) >= win_threshold,
    )
    signals = _signal_rows(completed, as_of_date.isoformat(), win_threshold)
    write_csv(root / "metrics" / "accuracy.csv", AGG_FIELDS, accuracy)
    write_csv(root / "metrics" / "win_rate.csv", AGG_FIELDS, win_rate)
    write_csv(root / "metrics" / "signal_effectiveness.csv", SIGNAL_FIELDS, signals)
    status_counts = Counter(str(row.get("status", "")) for row in rows)
    return {
        "tracking_rows": rows,
        "completed_rows": completed,
        "status_counts": dict(status_counts),
        "accuracy": accuracy,
        "win_rate": win_rate,
        "signals": signals,
        "pending_count": status_counts.get("pending", 0),
        "price_unavailable_count": status_counts.get("price_unavailable", 0),
    }

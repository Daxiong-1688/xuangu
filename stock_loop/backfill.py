from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from .metrics import build_return_tracking
from .providers import YixinProvider
from .utils import parse_date, read_json, write_json


TRANSIENT_ERROR_MARKERS = (
    "nodename nor servname provided",
    "name or service not known",
    "temporary failure in name resolution",
    "connection reset",
    "connection refused",
    "remote end closed connection",
    "timed out",
    "timeout",
)


def backfill_yixin_price_unavailable(
    root: Path,
    source_config: dict[str, Any],
    run_config: dict[str, Any],
    strategy: dict[str, Any],
    as_of_date: date,
) -> dict[str, Any]:
    """Backfill real close prices for already-due tracking rows.

    The daily provider fetches the current day's missing tracked prices. If that
    transiently fails, old snapshots keep missing those closes and later metric
    rebuilds cannot complete the expired horizon. This function closes that loop:
    it finds `price_unavailable` rows, queries Yixin for the exact evaluation
    date, writes real closes back into the historical run snapshot, and lets the
    caller rebuild metrics afterwards.
    """

    periods = [int(value) for value in run_config.get("observation_periods", [1, 3, 5, 10])]
    benchmark = run_config.get("benchmark_code", "000300.SH")
    risk_config = strategy.get("risk", {})
    tracking_rows = build_return_tracking(
        root,
        periods,
        benchmark,
        float(risk_config.get("risk_stop_drawdown_pct", -8.0)),
        as_of_date,
    )
    unavailable = [
        row
        for row in tracking_rows
        if row.get("status") == "price_unavailable" and row.get("evaluation_date")
    ]
    result: dict[str, Any] = {
        "attempted": 0,
        "filled": 0,
        "dates": {},
        "errors": [],
        "diagnostics": [],
    }
    if not unavailable:
        return result

    yixin_config = source_config.get("yixin", {})
    provider = YixinProvider(root, yixin_config)
    script = _resolve_yixin_script(root, yixin_config)
    if not script.exists():
        result["errors"].append(f"Yixin Skill 脚本不存在：{script}")
        return result
    try:
        module = provider._load_workflow_module(script)
        _, fin_db_key = module.load_keys()
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        return result

    grouped: dict[date, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in unavailable:
        evaluation_date = parse_date(str(row["evaluation_date"]))
        code = str(row.get("stock_code", "")).strip()
        if not code:
            continue
        grouped[evaluation_date][code] = {
            "stock_code": code,
            "stock_name": str(row.get("stock_name", "")),
            "sector": str(row.get("sector", "")),
        }

    attempts = max(1, int(yixin_config.get("workflow_attempts", 3)))
    retry_delay = max(0.0, float(yixin_config.get("retry_delay_seconds", 5)))
    for evaluation_date, stocks_by_code in sorted(grouped.items()):
        snapshot_path = root / "runs" / evaluation_date.isoformat() / "market_data.json"
        snapshot = read_json(snapshot_path, {})
        if not isinstance(snapshot, dict) or not snapshot:
            result["errors"].append(f"缺少历史市场快照：{snapshot_path}")
            continue
        price_book = dict(snapshot.get("price_book", {}))
        stock_book = dict(price_book.get("stocks", {}))
        missing = [
            item
            for code, item in stocks_by_code.items()
            if not _has_close(stock_book.get(code), evaluation_date)
        ]
        if not missing:
            continue
        raw_dir = root / "data" / "raw" / "yixin" / evaluation_date.isoformat()
        raw_dir.mkdir(parents=True, exist_ok=True)
        date_result = {
            "attempted": len(missing),
            "filled": 0,
            "symbols": [item["stock_code"] for item in missing],
            "unfilled": [],
        }
        result["dates"][evaluation_date.isoformat()] = date_result
        result["attempted"] += len(missing)
        for offset in range(0, len(missing), 30):
            chunk = missing[offset : offset + 30]
            query = _price_query(evaluation_date, chunk)
            response = None
            status = None
            error = ""
            for attempt in range(1, attempts + 1):
                try:
                    status, response = module.yixin_fin_db(fin_db_key, query)
                    break
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if attempt >= attempts or not _is_transient_error(error):
                        break
                    time.sleep(retry_delay)
            document = {
                "status": status,
                "response": response,
                "query": query,
                "error": error,
                "evaluation_date": evaluation_date.isoformat(),
                "symbols": [item["stock_code"] for item in chunk],
            }
            raw_path = (
                raw_dir
                / "data"
                / f"adapter-backfill-prices-{evaluation_date.isoformat()}-{offset // 30 + 1}.json"
            )
            write_json(raw_path, document)
            if response is None:
                if error:
                    result["errors"].append(
                        f"{evaluation_date.isoformat()} 补价失败：{error}"
                    )
                for item in chunk:
                    date_result["unfilled"].append(
                        {
                            "stock_code": item["stock_code"],
                            "reason": error or "Yixin fin_db 未返回响应",
                        }
                    )
                continue
            price_points = provider._extract_price_points(module, response)
            for item in chunk:
                code = item["stock_code"]
                point = price_points.get(code, {})
                close = point.get("close")
                trade_date = point.get("trade_date")
                if trade_date and trade_date != evaluation_date.isoformat():
                    date_result["unfilled"].append(
                        {
                            "stock_code": code,
                            "reason": (
                                f"Yixin 返回交易日期 {trade_date}，不是目标复盘日期 "
                                f"{evaluation_date.isoformat()}"
                            ),
                        }
                    )
                    continue
                if close is None:
                    date_result["unfilled"].append(
                        {
                            "stock_code": code,
                            "reason": "Yixin fin_db 未返回目标日期真实收盘价",
                        }
                    )
                    continue
                stock_book[code] = {
                    "name": item.get("stock_name", ""),
                    "sector": item.get("sector", ""),
                    "close": close,
                    "trade_date": evaluation_date.isoformat(),
                    "backfill_source": "yixin_fin_db",
                    "backfill_date": evaluation_date.isoformat(),
                }
                date_result["filled"] += 1
                result["filled"] += 1
        if date_result["filled"]:
            price_book["stocks"] = stock_book
            snapshot["price_book"] = price_book
            quality = dict(snapshot.get("data_quality", {}))
            notes = list(quality.get("notes", []))
            note = (
                f"已自动回补历史观察标的收盘价：{evaluation_date.isoformat()} "
                f"{date_result['filled']}/{date_result['attempted']}。"
            )
            if note not in notes:
                notes.append(note)
            quality["notes"] = notes
            snapshot["data_quality"] = quality
            write_json(snapshot_path, snapshot)
        if date_result["unfilled"]:
            result["diagnostics"].append(
                f"{evaluation_date.isoformat()} 仍有 {len(date_result['unfilled'])} 只未补齐；"
                "Yixin fin_db 未返回目标日期真实收盘价时保留 price_unavailable。"
            )
    return result


def _resolve_yixin_script(root: Path, yixin_config: dict[str, Any]) -> Path:
    script = Path(yixin_config.get("skill_script", "")).expanduser()
    if not script.is_absolute():
        script = (root / script).resolve()
    if script.exists():
        return script
    installed_script = (
        Path.home()
        / ".codex"
        / "skills"
        / "yixin-stock-workflow"
        / "scripts"
        / "run_yixin_stock_workflow.py"
    )
    return installed_script


def _has_close(value: Any, expected_date: date | None = None) -> bool:
    if not isinstance(value, dict) or value.get("close") in (None, ""):
        return False
    trade_date = value.get("trade_date")
    if expected_date is not None and trade_date:
        try:
            return parse_date(str(trade_date)) == expected_date
        except ValueError:
            return False
    return True


def _price_query(evaluation_date: date, stocks: list[dict[str, str]]) -> str:
    labels = "、".join(
        f"{item.get('stock_code', '')} {item.get('stock_name', '')}".strip()
        for item in stocks
    )
    return (
        f"请返回以下A股在{evaluation_date.isoformat()}这个交易日的真实收盘价：{labels}。"
        "只返回股票代码、股票名称、交易日期、收盘价。"
        "不要返回成交额、市值、PE、PB、PS或其他估值字段；不要用最新价替代指定日期收盘价。"
    )


def _is_transient_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in TRANSIENT_ERROR_MARKERS)

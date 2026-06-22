from __future__ import annotations

import traceback
from datetime import date
from pathlib import Path
from typing import Any

from .config import load_project_config
from .metrics import update_all_metrics
from .providers import build_provider
from .reporting import (
    daily_report_markdown,
    generate_dashboard_html,
    generate_output_summary,
    risk_analysis_markdown,
    selection_reason_markdown,
)
from .review import (
    build_strategy_suggestions,
    generate_review_markdown,
    maybe_create_strategy_draft,
)
from .selection import SELECTED_FIELDS, select_stocks
from .utils import (
    copy_text,
    ensure_project_dirs,
    list_run_dates,
    now_text,
    read_csv,
    write_csv,
    write_json,
    write_text,
)


def collect_tracked_stocks(root: Path) -> list[dict[str, str]]:
    tracked: dict[str, dict[str, str]] = {}
    for run_date in list_run_dates(root):
        for row in read_csv(root / "runs" / run_date.isoformat() / "selected_stocks.csv"):
            code = row.get("stock_code", "")
            if code:
                tracked[code] = {
                    "stock_code": code,
                    "stock_name": row.get("stock_name", ""),
                    "sector": row.get("sector", ""),
                }
    return list(tracked.values())


def _log_text(
    started_at: str,
    status: str,
    run_date: date,
    provider_name: str,
    strategy_version: str,
    error: str = "",
) -> str:
    lines = [
        "# 运行日志",
        "",
        f"- 计划日期：{run_date.isoformat()}",
        f"- 开始时间：{started_at}",
        f"- 结束时间：{now_text()}",
        f"- 数据源：{provider_name}",
        f"- 策略版本：{strategy_version}",
        f"- 状态：{status}",
    ]
    if error:
        lines.extend(["", "## 异常", "", "```text", error[-5000:], "```"])
    return "\n".join(lines)


def run_daily(
    root: Path,
    run_date: date,
    provider_override: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    ensure_project_dirs(root)
    configs = load_project_config(root)
    strategy = configs["strategy"]
    run_config = configs["run"]
    run_dir = root / "runs" / run_date.isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = now_text()
    provider_name = provider_override or configs["data_source"].get("provider", "mock")
    try:
        provider = build_provider(root, configs["data_source"], provider_override)
        tracked = collect_tracked_stocks(root)
        market_data = provider.fetch(run_date, tracked)
        write_json(run_dir / "market_data.json", market_data)

        periods = [int(item) for item in run_config.get("observation_periods", [1, 3, 5, 10])]
        selected, quality = select_stocks(
            market_data, strategy, run_date.isoformat(), periods
        )
        write_csv(run_dir / "selected_stocks.csv", SELECTED_FIELDS, selected)
        write_text(
            run_dir / "selection_reason.md",
            selection_reason_markdown(
                run_date, selected, str(strategy.get("strategy_version", "unknown"))
            ),
        )
        write_text(
            run_dir / "risk_analysis.md",
            risk_analysis_markdown(run_date, market_data, selected, quality),
        )

        metrics = update_all_metrics(root, run_config, strategy, run_date)
        review_text = generate_review_markdown(run_date, metrics, periods)
        write_text(run_dir / "review_previous.md", review_text)
        suggestion_text, keys = build_strategy_suggestions(run_date, metrics, strategy)
        write_text(run_dir / "strategy_suggestion.md", suggestion_text)
        draft_path = maybe_create_strategy_draft(root, run_date, strategy, keys)

        report_text = daily_report_markdown(
            run_date,
            market_data,
            selected,
            strategy,
            quality,
            review_text,
            suggestion_text,
            draft_path,
        )
        write_text(run_dir / "daily_report.md", report_text)
        copy_text(run_dir / "daily_report.md", root / "output" / "latest_report.md")
        write_text(root / "output" / "summary.md", generate_output_summary(root, run_date))
        if run_config.get("write_dashboard", True):
            write_text(
                root / "output" / "dashboard.html",
                generate_dashboard_html(root, run_date),
            )
        write_text(
            run_dir / "run_log.md",
            _log_text(
                started_at,
                "success",
                run_date,
                provider.name,
                str(strategy.get("strategy_version", "unknown")),
            ),
        )
        return {
            "run_dir": run_dir,
            "selected_count": len(selected),
            "pool_status": quality["pool_status"],
            "provider": provider.name,
            "draft_path": draft_path,
        }
    except Exception:
        error = traceback.format_exc()
        write_text(
            run_dir / "run_log.md",
            _log_text(
                started_at,
                "failed",
                run_date,
                provider_name,
                str(strategy.get("strategy_version", "unknown")),
                error,
            ),
        )
        raise

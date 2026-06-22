#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_loop.config import load_project_config
from stock_loop.metrics import update_all_metrics
from stock_loop.providers import enrich_yixin_market_data_from_raw
from stock_loop.reporting import (
    daily_report_markdown,
    generate_dashboard_html,
    generate_output_summary,
    risk_analysis_markdown,
    selection_reason_markdown,
)
from stock_loop.review import (
    build_strategy_suggestions,
    generate_review_markdown,
    maybe_create_strategy_draft,
)
from stock_loop.selection import SELECTED_FIELDS, select_stocks
from stock_loop.utils import (
    copy_text,
    read_json,
    write_csv,
    write_json,
    write_text,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="使用已有运行文件重新生成日报与汇总页。")
    parser.add_argument("--date", help="目标日期，默认今天。")
    args = parser.parse_args()
    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    run_dir = ROOT / "runs" / run_date.isoformat()
    config = load_project_config(ROOT)
    market_data = read_json(run_dir / "market_data.json")
    if not market_data:
        raise SystemExit(f"缺少 {run_dir / 'market_data.json'}")
    market_data = enrich_yixin_market_data_from_raw(
        ROOT, run_date, market_data, config["data_source"]
    )
    write_json(run_dir / "market_data.json", market_data)
    periods = [int(item) for item in config["run"].get("observation_periods", [1, 3, 5, 10])]
    selected, quality = select_stocks(
        market_data, config["strategy"], run_date.isoformat(), periods
    )
    write_csv(run_dir / "selected_stocks.csv", SELECTED_FIELDS, selected)
    write_text(
        run_dir / "selection_reason.md",
        selection_reason_markdown(
            run_date,
            selected,
            str(config["strategy"].get("strategy_version", "unknown")),
        ),
    )
    write_text(
        run_dir / "risk_analysis.md",
        risk_analysis_markdown(run_date, market_data, selected, quality),
    )
    metrics = update_all_metrics(
        ROOT, config["run"], config["strategy"], run_date
    )
    review = generate_review_markdown(run_date, metrics, periods)
    write_text(run_dir / "review_previous.md", review)
    suggestion, keys = build_strategy_suggestions(
        run_date, metrics, config["strategy"]
    )
    write_text(run_dir / "strategy_suggestion.md", suggestion)
    draft_path = maybe_create_strategy_draft(
        ROOT, run_date, config["strategy"], keys
    )
    report = daily_report_markdown(
        run_date,
        market_data,
        selected,
        config["strategy"],
        quality,
        review,
        suggestion,
        draft_path,
    )
    write_text(run_dir / "daily_report.md", report)
    copy_text(run_dir / "daily_report.md", ROOT / "output" / "latest_report.md")
    write_text(ROOT / "output" / "summary.md", generate_output_summary(ROOT, run_date))
    write_text(ROOT / "output" / "dashboard.html", generate_dashboard_html(ROOT, run_date))
    print(f"report={run_dir / 'daily_report.md'}")


if __name__ == "__main__":
    main()

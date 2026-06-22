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
from stock_loop.review import (
    build_strategy_suggestions,
    generate_review_markdown,
    maybe_create_strategy_draft,
)
from stock_loop.utils import write_text


def main() -> None:
    parser = argparse.ArgumentParser(description="重新生成指定日期的复盘与策略建议。")
    parser.add_argument("--date", help="目标日期，默认今天。")
    args = parser.parse_args()
    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    config = load_project_config(ROOT)
    metrics = update_all_metrics(ROOT, config["run"], config["strategy"], run_date)
    periods = [int(item) for item in config["run"].get("observation_periods", [1, 3, 5, 10])]
    review = generate_review_markdown(run_date, metrics, periods)
    suggestion, keys = build_strategy_suggestions(run_date, metrics, config["strategy"])
    run_dir = ROOT / "runs" / run_date.isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_text(run_dir / "review_previous.md", review)
    write_text(run_dir / "strategy_suggestion.md", suggestion)
    draft = maybe_create_strategy_draft(ROOT, run_date, config["strategy"], keys)
    print(f"review={run_dir / 'review_previous.md'}")
    print(f"suggestion={run_dir / 'strategy_suggestion.md'}")
    if draft:
        print(f"strategy_draft={draft}")


if __name__ == "__main__":
    main()

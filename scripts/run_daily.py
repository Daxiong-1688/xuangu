#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_loop.daily import run_daily
from stock_loop.utils import LockUnavailable, exclusive_file_lock


def main() -> None:
    parser = argparse.ArgumentParser(description="运行每日选股、复盘、指标与报告 Loop。")
    parser.add_argument("--date", help="运行日期，格式 YYYY-MM-DD；默认今天。")
    parser.add_argument(
        "--provider",
        choices=["mock", "file", "yixin"],
        help="临时覆盖 config/data_source.yaml 中的数据源。",
    )
    parser.add_argument(
        "--skip-backfill",
        action="store_true",
        help="跳过内置历史补价；用于外部两阶段 Yixin wrapper 先生成日报再顶层补价。",
    )
    args = parser.parse_args()
    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    try:
        with exclusive_file_lock(ROOT / ".runtime" / "daily.lock"):
            result = run_daily(ROOT, run_date, args.provider, args.skip_backfill)
    except LockUnavailable as exc:
        print(str(exc))
        return
    print(f"run_dir={result['run_dir']}")
    print(f"provider={result['provider']}")
    print(f"pool_status={result['pool_status']}")
    print(f"selected_count={result['selected_count']}")
    if result.get("draft_path"):
        print(f"strategy_draft={result['draft_path']}")


if __name__ == "__main__":
    main()

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
from stock_loop.utils import ensure_project_dirs


def main() -> None:
    parser = argparse.ArgumentParser(description="从 runs/ 幂等重算全部复盘指标。")
    parser.add_argument("--date", help="指标截止日期，默认今天。")
    args = parser.parse_args()
    as_of = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    ensure_project_dirs(ROOT)
    config = load_project_config(ROOT)
    result = update_all_metrics(ROOT, config["run"], config["strategy"], as_of)
    print(f"completed_rows={len(result['completed_rows'])}")
    print(f"pending_count={result['pending_count']}")
    print(f"metrics_dir={ROOT / 'metrics'}")


if __name__ == "__main__":
    main()

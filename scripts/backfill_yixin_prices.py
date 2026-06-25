#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_loop.backfill import backfill_yixin_price_unavailable
from stock_loop.config import load_project_config
from stock_loop.utils import ensure_project_dirs, write_json


def main() -> None:
    parser = argparse.ArgumentParser(
        description="顶层运行 Yixin 历史缺价回补，并写入 runs/<date>/backfill_result.json。"
    )
    parser.add_argument("--date", help="指标截止日期，默认今天。")
    args = parser.parse_args()
    as_of = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    ensure_project_dirs(ROOT)
    config = load_project_config(ROOT)
    result = backfill_yixin_price_unavailable(
        ROOT,
        config["data_source"],
        config["run"],
        config["strategy"],
        as_of,
    )
    run_dir = ROOT / "runs" / as_of.isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "backfill_result.json", result)
    print(f"attempted={result.get('attempted', 0)}")
    print(f"filled={result.get('filled', 0)}")
    print(f"errors={len(result.get('errors', []))}")
    print(f"result={run_dir / 'backfill_result.json'}")


if __name__ == "__main__":
    main()

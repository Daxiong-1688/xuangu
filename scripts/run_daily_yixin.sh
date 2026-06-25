#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DATE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      RUN_DATE="${2:?missing value for --date}"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$RUN_DATE" ]]; then
  RUN_DATE="$(python3 - <<'PY'
from datetime import date
print(date.today().isoformat())
PY
)"
fi

RAW_DIR="$ROOT/data/raw/yixin/$RUN_DATE"
RAW_DATA_DIR="$RAW_DIR/data"
SKILL_SCRIPT="$ROOT/scripts/run_yixin_stock_workflow.py"
if [[ ! -f "$SKILL_SCRIPT" ]]; then
  SKILL_SCRIPT="$HOME/.codex/skills/yixin-stock-workflow/scripts/run_yixin_stock_workflow.py"
fi
if [[ ! -f "$SKILL_SCRIPT" ]]; then
  echo "Yixin Skill script not found: $SKILL_SCRIPT" >&2
  exit 1
fi

mkdir -p "$RAW_DATA_DIR"

if ! compgen -G "$RAW_DATA_DIR/*-selected_candidates.json" >/dev/null ||
   ! { compgen -G "$RAW_DATA_DIR/*-fin_trends_merged.json" >/dev/null || compgen -G "$RAW_DATA_DIR/*-fin_trends.json" >/dev/null; }; then
  echo "fetch_raw=$RAW_DIR"
  if python3 "$SKILL_SCRIPT" --output-dir "$RAW_DIR" --skip-image >"$RAW_DIR/adapter_stdout.log" 2>"$RAW_DIR/adapter_stderr.log"; then
    echo "raw_fetch_status=success"
  else
    echo "raw_fetch_status=failed" >&2
    tail -n 80 "$RAW_DIR/adapter_stderr.log" >&2 || true
    exit 1
  fi
else
  {
    echo "raw_fetch_status=reused"
    echo "reused_at=$(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "raw_dir=$RAW_DIR"
    echo "note=existing Yixin raw files passed required checks; no network fetch attempted"
  } >"$RAW_DIR/adapter_stdout.log"
  : >"$RAW_DIR/adapter_stderr.log"
  echo "raw_fetch_status=reused"
fi

python3 "$ROOT/scripts/run_daily.py" --date "$RUN_DATE" --provider yixin --skip-backfill
python3 "$ROOT/scripts/backfill_yixin_prices.py" --date "$RUN_DATE"
python3 "$ROOT/scripts/generate_report.py" --date "$RUN_DATE"

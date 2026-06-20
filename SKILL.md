---
name: yixin-stock-workflow
description: Run a Yixin OpenAPI based A-share stock research workflow that scans fresh market/AI hot topics, queries financial and price data, applies completeness gates, builds a technical-structure TOP 5, and exports Markdown, HTML, and PNG reports. Use when the user asks to run, package, improve, or generate an HTML/image stock-picking report with Yixin search and fin_db, especially for 智能选股, 热点追踪, A股选股, 技术结构, TOP 5, 自选股候选, or report generation workflows.
---

# Yixin Stock Workflow

Use this skill to generate an A-share research-assistant report from Yixin OpenAPI. The workflow calls:

- `search`: fresh market and AI/technology news
- `fin_db`: candidate stocks, price/trend data, growth data, and optional valuation data

The bundled script exports:

- raw JSON under `data/`
- Markdown, HTML, and optional PNG under `reports/`

## Security

Never include real API keys in this skill, reports, source code, commits, screenshots, or examples.

Users must configure their own Yixin API keys before running:

```json
{
  "search": "<search-api-key>",
  "fin_db": "<fin-db-api-key>"
}
```

Default location:

```text
~/.config/yixin-api/api-keys.json
```

Alternative environment variables:

```bash
export YIXIN_SEARCH_API_KEY="..."
export YIXIN_FIN_DB_API_KEY="..."
```

## Quick Start

From any project directory:

```bash
python3 /path/to/yixin-stock-workflow/scripts/run_yixin_stock_workflow.py --output-dir .
```

If Chrome is unavailable or image rendering is not needed:

```bash
python3 /path/to/yixin-stock-workflow/scripts/run_yixin_stock_workflow.py --output-dir . --skip-image
```

When installed in Codex:

```bash
python3 ~/.codex/skills/yixin-stock-workflow/scripts/run_yixin_stock_workflow.py --output-dir .
```

## Workflow

1. Query recent market/AI-related news with `search`.
2. Apply local freshness filters: recent dates only, useful snippets only, low-quality sources removed, duplicate titles removed.
3. Query candidate stocks and trend data with `fin_db`.
4. Check trend-field completeness. If real trend fields are incomplete, automatically run narrower supplemental `fin_db` queries for:
   - 5/20/60-day price change
   - close price with 20/60-day moving averages
   - close price, 52-week high, and distance from the 52-week high
5. If the current date is a weekend, ask trend queries as of the latest A-share trading day rather than the calendar date.
6. Merge the base trend response and supplemental trend responses before scoring.
7. If moving-average or 52-week fields are still missing after the first supplemental pass, retry once with calculation-oriented query wording. For moving averages, split candidates into chunks before requesting daily close history so API row limits do not truncate the 60-day sample.
8. Clean candidate tables: remove duplicate stocks, sparse columns, and incomplete valuation columns.
9. Apply completeness gates:
   - PE/PB is displayed and scored only when complete enough.
   - If valuation is incomplete, hide it and use growth metrics instead.
10. Generate a technical-structure TOP 5 using available trend, moving-average, 52-week-position, volume, and growth data.
11. Export Markdown, HTML, and PNG reports.

If trend fields are incomplete after supplemental queries, the workflow must not force a technical TOP 5. It should report data coverage and downgrade the output to a candidate observation pool until real trend fields can be fetched.

A formal technical TOP 5 requires enough coverage for real price change, close price, 20-day moving average, and 60-day moving average. If only one of these dimensions is available, keep the partial data visible but do not call it a formal TOP 5.

## Technical Structure Model

The TOP 5 is a research ranking, not investment advice. It combines:

- trend and momentum
- 20/60-day moving-average structure
- price position versus 52-week high
- volume/change context when available
- simplified candlestick/K-line interpretation
- simplified Chan theory structure wording
- growth metrics when valuation data is incomplete

Only real trend fields may drive technical momentum scoring:

- allowed: `pct_change`, `avg_pct_change`, explicit `涨跌幅` columns, 20/60-day moving averages, close price, and 52-week high fields
- blocked: turnover/amount, market cap (`total_mv`), PE/PB/PS, and other valuation or size fields

When a `fin_db` response mixes market price, valuation, and market-cap rows in one table, parse rows by `item_key`/`item_name` instead of treating the whole response as one metric type.

If the first broad trend query returns only close price, turnover, valuation, or market-cap fields, split the trend query into narrow requests. The supplemental requests should explicitly say not to return turnover, market cap, PE, PB, PS, or other non-trend fields when asking for涨跌幅.

If `fin_db` returns daily `pct_change` rows for a 5/20/60-day period, aggregate those daily percentage changes into a cumulative period return before scoring. Do not use the last daily row as the period return.

If `fin_db` returns daily close rows instead of moving-average columns, calculate 20-day and 60-day moving averages locally from the latest close-history sample. Keep the sample count visible in the displayed trend section.

Use cautious labels such as `趋势延续`, `回调观察`, `接近前高`, `短期涨幅偏快`, and `20日线可作为短线结构观察位`.

Avoid language such as `买入`, `卖出`, `稳赚`, `必涨`, or target prices.

## Outputs

The script prints generated paths:

```text
report=/.../reports/<run-id>-workflow-report.md
html=/.../reports/<run-id>-workflow-report.html
image=/.../reports/<run-id>-workflow-report.png
```

Use the HTML report for browser review and the PNG report for sharing.

## Maintenance Notes

- Keep API key handling in `load_keys()` only.
- Do not commit generated `data/` or `reports/` unless the user explicitly wants sample outputs.
- If a returned table has incomplete fields, prefer hiding the dimension over showing partial data.
- If Yixin returns stale search results, rely on local date filtering rather than trusting `time_range`.
- Never substitute market cap, transaction amount, or valuation fields for trend momentum. If real涨跌幅/均线/52周 fields are missing, show a data completeness note and do not publish a formal technical TOP 5.
- Report conclusions must match the actual scoring result. If no formal TOP 5 is generated, call the output a `候选观察池`, do not tell the user to add TOP 5 stocks to `watchlist.json`.

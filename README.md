# Stock Selection Loop

一个非产品化、文件驱动的选股 Skill 自动运行项目。

它只做四件事：

1. Skill 生成每日策略观察股票池；
2. Loop 在本地或服务器定时运行；
3. Agent 逻辑复盘历史观察结果并提出候选优化建议；
4. 文件夹保存每天的数据、结果、日志、指标和策略版本。

不包含前端产品、登录、用户系统、数据库优先架构、SaaS 多租户或自动交易。所有输出均为研究辅助，不构成投资建议。

## 项目结构

```text
.
├── config/                    # 正式策略、数据源和运行配置
├── skills/                    # 选股、复盘、策略迭代业务规则
├── stock_loop/                # 可复用核心模块
├── scripts/                   # 每日运行、复盘、指标和报告入口
├── data/                      # 原始、处理后和文件快照数据
├── runs/YYYY-MM-DD/           # 每日独立运行结果
├── reviews/                   # 周/月复盘与失败案例预留目录
├── metrics/                   # 幂等重算的累计指标
├── strategy_versions/         # 正式版本说明和候选 draft
└── output/                    # 最新日报、汇总和静态 dashboard
```

## 快速开始

本项目只使用 Python 标准库，需要 Python 3.9 及以上。

```bash
cd /path/to/stock-selection-loop
python3 scripts/run_daily.py
```

使用真实 Yixin 时推荐走两阶段入口，先由顶层命令采集 raw，再由 Loop
消费 raw 生成日报和复盘，避免在 Python Loop 内部嵌套联网子进程：

```bash
scripts/run_daily_yixin.sh
scripts/run_daily_yixin.sh --date 2026-06-24
```

指定日期或临时覆盖数据源：

```bash
python3 scripts/run_daily.py --date 2026-06-22
python3 scripts/run_daily.py --provider mock
python3 scripts/run_daily.py --provider file
python3 scripts/run_daily.py --provider yixin
```

当前默认使用 `yixin` 数据源。Yixin API Key 由
`~/.config/yixin-api/api-keys.json` 或环境变量提供，不会写入项目。
如需离线验证，可临时运行 `python3 scripts/run_daily.py --provider mock`。

## 每日运行内容

`python3 scripts/run_daily.py` 会：

1. 创建 `runs/YYYY-MM-DD/`；
2. 获取市场快照并写入 `market_data.json`；
3. 运行评分与风险过滤，写入 `selected_stocks.csv`；
4. 生成逐股理由和风险分析；
5. 从所有历史 `runs/` 重算 1/3/5/10 日表现；
6. 覆盖更新 `metrics/*.csv`，避免重跑重复计数；
7. 生成历史复盘和策略建议；
8. 连续多日出现同类问题时生成候选 draft；
9. 生成 `backfill_result.json`、`daily_report.md`、`daily_report.html`、`dashboard.html` 和 `run_log.md`；
10. 同步更新 `output/latest_report.md`、`latest_report.html`、`summary.md` 和静态 `dashboard.html`。

`scripts/run_daily_yixin.sh` 在此基础上增加两个外部阶段：

1. 如果 `data/raw/yixin/YYYY-MM-DD/` 缺少真实 raw，先顶层调用
   `yixin-stock-workflow` Skill 生成 raw；
2. 日报初步生成后，顶层运行 `scripts/backfill_yixin_prices.py` 补查
   到期观察股真实收盘价，再重算报告和 dashboard。

每天至少产生：

```text
runs/YYYY-MM-DD/
├── market_data.json
├── selected_stocks.csv
├── backfill_result.json
├── selection_reason.md
├── risk_analysis.md
├── review_previous.md
├── strategy_suggestion.md
├── daily_report.md
├── daily_report.html
├── dashboard.html
└── run_log.md
```

## 单独重算

```bash
# 从全部 runs 幂等重算指标
python3 scripts/update_metrics.py

# 重算指定日期复盘与策略建议
python3 scripts/review_results.py --date 2026-06-22

# 使用已有 market_data/review/suggestion 重新生成报告
python3 scripts/generate_report.py --date 2026-06-22
```

## 配置说明

### 正式策略

编辑 `config/strategy.yaml`：

- `strategy_version`：正式策略版本；
- `weights`：热点、资金、技术和风险控制权重；
- `score_thresholds`：最低总分、最低技术分、最高风险分；
- `data_quality`：正式技术观察池的数据完整性门槛；
- `risk`：回撤、过热和52周位置风险阈值；
- `review`：复盘目标、最小样本和 draft 触发规则。

配置文件采用“JSON 语法的 YAML”，这样无需安装 PyYAML。

### 数据源

编辑 `config/data_source.yaml` 的 `provider`：

- `mock`：默认。离线、确定性、用于验证 Loop。
- `file`：读取 `data/market_snapshot/YYYY-MM-DD.json`。
- `yixin`：调用已安装的 `yixin-stock-workflow` Skill。

## 接入真实行情 API

推荐两种方式。

### 方式一：先适配为文件快照

把 API 返回结果转换为 `data/market_snapshot/YYYY-MM-DD.json`，格式见 `data/market_snapshot/README.md`，然后设置：

```json
{"provider": "file"}
```

这是最简单、最好审计的接法。

### 方式二：新增 Provider

在 `stock_loop/providers.py` 中新增 `MarketDataProvider` 子类，实现：

```python
fetch(run_date, tracked_stocks) -> market_data
```

然后在 `build_provider()` 注册。真实数据至少应提供：

- 当日候选池及真实收盘价；
- 5/20/60日涨跌幅；
- 20/60日均线；
- 52周位置和成交量变化（可选但推荐）；
- 沪深300收盘值；
- 各候选所属板块指数值；
- 历史未到期观察标的的当日价格。

最后一项很重要：它让 1/3/5/10 日复盘可以持续更新，而不只跟踪当天新选出的股票。

### Yixin

`yixin` provider 默认消费已经生成的 raw，推荐通过：

```bash
scripts/run_daily_yixin.sh
```

如果 raw 缺失，`python3 scripts/run_daily.py --provider yixin` 会提示先走外部
采集入口，而不是继续在 Loop 内部嵌套启动联网子进程。

外部采集默认优先调用仓库内脚本：

```text
scripts/run_yixin_stock_workflow.py
```

因此从 GitHub clone 后不需要把脚本复制到固定的用户目录。若项目作为
Codex Skill 安装，也可以在 `config/data_source.yaml` 中改回已安装 Skill 路径。

API Key 仍由原 Skill 的 `load_keys()` 管理，只允许：

```text
~/.config/yixin-api/api-keys.json
```

或环境变量：

```bash
export YIXIN_SEARCH_API_KEY="..."
export YIXIN_FIN_DB_API_KEY="..."
```

密钥不会写入项目文件。Yixin 原始响应保存在 `data/raw/yixin/YYYY-MM-DD/`。若标准化后的真实趋势字段不足，本项目会降级为候选观察池。

## Codex 智能自动化（推荐）

这个模式由 Codex 在工作日定时进入项目，不只是启动脚本，还会：

- 使用 `yixin-stock-workflow` Skill 抓取真实数据；
- 检查行情、资讯新鲜度和核心趋势字段完整性；
- 运行每日观察池工作流；
- 复盘历史 1/3/5/10 日表现；
- 检查收益、胜率、回撤和信号有效性；
- 审阅风险分析与策略建议；
- 遇到失败或输出不一致时主动诊断和重试；
- 向用户汇报当日结果与数据缺口。

Codex 可以生成候选策略 draft，但不会自动覆盖正式
`config/strategy.yaml`。

分享给其他 Codex 用户后，对方可以在项目线程中直接说：

```text
为这个项目创建工作日 15:30 的 Codex 每日自动化：
使用 yixin-stock-workflow 运行每日 Loop，检查数据质量，
复盘历史表现并汇报策略建议，不自动修改正式策略。
```

Codex 会为对方自己的工作区创建独立自动化。API Key 仍由每个人在自己的
`~/.config/yixin-api/api-keys.json` 中配置，不应随项目分享。

## 策略版本纪律

- 正式策略唯一来源：`config/strategy.yaml`。
- 历史版本说明：`strategy_versions/`。
- 每日 CSV 和日报都记录 `strategy_version`。
- Agent 只生成建议或 `vX.Y-draft-YYYY-MM-DD.md`。
- 程序不会自动覆盖正式策略。
- 正式升级必须人工确认、回测并手工修改版本号。

## 指标口径

- 收益率：观察价到第 N 个后续运行日收盘价。
- 最大涨幅：观察窗口相对观察价的最大浮盈。
- 最大回撤：观察窗口内从历史峰值到后续价格的最大跌幅。
- 准确率：收益方向超过策略配置阈值的比例。
- 胜率：收益达到策略配置胜率门槛的比例。
- 跑赢指数/板块：与同日起点、同一终点的快照比较。
- 缺失行情：标记为 `price_unavailable`，不纳入成功或失败。

## 合规边界

- 不输出绝对化投资建议。
- 不输出交易指令、收益保证或确定性方向判断。
- 不把系统包装成面向用户的投资推荐产品。
- 不用估值、市值或成交额替代真实趋势字段。
- mock 数据仅用于工程验证。

# Yixin Stock Workflow

基于 Yixin OpenAPI 的 A 股智能选股 Codex skill。

它会扫描最近市场热点，生成候选股票池，查询可得行情/财务数据，做趋势、均线、成长和技术结构评分，并导出 Markdown、HTML 和 PNG 报告。

> 本项目仅用于投研辅助和学习演示，不构成任何买卖建议。

## Boundary

本仓库是纯 Codex skill：只负责生成当次研究报告，不保存长期预测记忆，不运行 Agent Loop，不自动学习或切换策略。

实验型 Agent Loop 已拆分到独立仓库 `Daxiong-1688/xuangu-loop`。如果只是分享给别人使用，请安装本仓库；只有需要长期复盘、策略实验和人工批准策略版本时，才使用 loop 仓库。

## Features

- 最近热点扫描：A 股市场、AI、算力、半导体、机器人、低空经济、创新药等方向。
- 热点质量解读：区分产业催化、政策/订单/业绩支撑、资金退潮、高位分化和估值过热。
- 动态候选池：根据热点生成候选股票，不固定在少数样例股票。
- 数据完整性门控：PE/PB 等估值字段不完整时不展示、不参与评分。
- 技术结构评分：趋势动量、20/60 日均线、52 周位置、成长指标、简化 K 线/缠论描述。
- 报告输出：Markdown、HTML、PNG。
- 密钥安全：不提交、不打印、不写入 API key。

## Install As Codex Skill

将本目录复制到 Codex skills 目录：

```bash
cp -R yixin-stock-workflow ~/.codex/skills/
```

然后在 Codex 中使用：

```text
$yixin-stock-workflow 帮我选股
```

## API Key Setup

创建本地配置文件：

```text
~/.config/yixin-api/api-keys.json
```

内容格式：

```json
{
  "search": "<search-api-key>",
  "fin_db": "<fin-db-api-key>"
}
```

也可以使用环境变量：

```bash
export YIXIN_SEARCH_API_KEY="..."
export YIXIN_FIN_DB_API_KEY="..."
```

## Run

```bash
python3 scripts/run_yixin_stock_workflow.py --output-dir .
```

不生成图片时：

```bash
python3 scripts/run_yixin_stock_workflow.py --output-dir . --skip-image
```

输出文件：

```text
data/
reports/
```

普通 skill 不应生成 `state/`；如果本地出现 loop 状态目录，请不要提交到本仓库。

## Security Notes

- 不要提交 `~/.config/yixin-api/api-keys.json`。
- 不要提交真实生成的 `data/` 和 `reports/`，除非已经确认不包含敏感信息。
- 不要把 loop 产生的 `state/` 或 `*.jsonl` 状态文件提交到本 skill 仓库。
- `examples/sample-report.html` 仅作为脱敏示例。

## License

MIT

# File Provider 快照格式

将真实行情适配为：

```text
data/market_snapshot/YYYY-MM-DD.json
```

然后把 `config/data_source.yaml` 的 `provider` 改为 `file`。

最小结构示例：

```json
{
  "market_as_of": "2026-06-22",
  "source": "your-api",
  "is_mock": false,
  "market": {
    "risk_level": "中",
    "indices": [
      {"code": "000300.SH", "name": "沪深300", "close": 4000.0}
    ]
  },
  "sectors": [
    {"name": "半导体", "hot_score": 72, "capital_flow_score": 68, "index_close": 1200}
  ],
  "news": [],
  "candidates": [
    {
      "stock_code": "000001.SZ",
      "stock_name": "示例公司",
      "sector": "示例板块",
      "close": 10.5,
      "pct_change_5": 2.1,
      "pct_change_20": 6.8,
      "pct_change_60": 10.2,
      "ma20": 10.1,
      "ma60": 9.6,
      "high_52w": 12.0,
      "volume_ratio": 1.25,
      "hot_sector_score": 72,
      "capital_flow_score": 66,
      "risk_score": 35,
      "signals": ["热点板块", "资金流入", "均线多头"]
    }
  ],
  "price_book": {
    "stocks": {
      "000001.SZ": {"name": "示例公司", "sector": "示例板块", "close": 10.5}
    },
    "indices": {"000300.SH": 4000.0},
    "sectors": {"示例板块": 1200.0}
  }
}
```

为了复盘历史标的，`price_book.stocks` 最好包含当前观察池和历史未到期观察池的所有代码。

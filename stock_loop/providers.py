from __future__ import annotations

import importlib.util
import json
import math
import re
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .utils import business_days, previous_business_day, read_json, safe_float


class MarketDataProvider(ABC):
    name = "base"

    def __init__(self, root: Path, config: dict[str, Any]):
        self.root = root
        self.config = config

    @abstractmethod
    def fetch(self, run_date: date, tracked_stocks: list[dict[str, str]]) -> dict[str, Any]:
        raise NotImplementedError


MOCK_UNIVERSE = [
    ("300308.SZ", "中际旭创", "AI算力", 128.0, 0.0008),
    ("300502.SZ", "新易盛", "CPO", 112.0, 0.0010),
    ("688256.SH", "寒武纪", "半导体", 185.0, 0.0005),
    ("002371.SZ", "北方华创", "半导体", 242.0, 0.0006),
    ("601138.SH", "工业富联", "AI算力", 24.0, 0.0004),
    ("002230.SZ", "科大讯飞", "人工智能", 49.0, 0.0002),
    ("300124.SZ", "汇川技术", "机器人", 58.0, 0.0005),
    ("002747.SZ", "埃斯顿", "机器人", 20.0, 0.0001),
    ("002085.SZ", "万丰奥威", "低空经济", 16.0, 0.0003),
    ("600276.SH", "恒瑞医药", "创新药", 47.0, 0.0004),
    ("300750.SZ", "宁德时代", "储能", 208.0, 0.0004),
    ("300274.SZ", "阳光电源", "储能", 92.0, 0.0005),
]


class MockProvider(MarketDataProvider):
    name = "mock"
    epoch = date(2025, 1, 2)

    def _index(self, value: date) -> int:
        return max(0, len(business_days(self.epoch, previous_business_day(value))) - 1)

    def _price(self, code: str, base: float, drift: float, value: date) -> float:
        idx = self._index(value)
        phase = sum(ord(char) for char in code) % 37
        cycle = 0.065 * math.sin((idx + phase) / 9.0)
        fast = 0.018 * math.sin((idx + phase) / 2.8)
        return round(max(base * 0.35, base * (1 + drift * idx + cycle + fast)), 2)

    def _stock_row(self, item: tuple[str, str, str, float, float], run_date: date) -> dict[str, Any]:
        code, name, sector, base, drift = item
        close = self._price(code, base, drift, run_date)
        closes_20 = [
            self._price(code, base, drift, run_date - timedelta(days=offset))
            for offset in range(1, 35)
            if (run_date - timedelta(days=offset)).weekday() < 5
        ][:20]
        closes_60 = [
            self._price(code, base, drift, run_date - timedelta(days=offset))
            for offset in range(1, 95)
            if (run_date - timedelta(days=offset)).weekday() < 5
        ][:60]
        p5 = self._price(code, base, drift, run_date - timedelta(days=7))
        p20 = self._price(code, base, drift, run_date - timedelta(days=28))
        p60 = self._price(code, base, drift, run_date - timedelta(days=84))
        high52 = max(
            self._price(code, base, drift, run_date - timedelta(days=offset))
            for offset in range(0, 366, 3)
        )
        phase = sum(ord(char) for char in code)
        hot = 55 + 25 * (0.5 + 0.5 * math.sin((self._index(run_date) + phase) / 13))
        capital = 48 + 35 * (0.5 + 0.5 * math.cos((self._index(run_date) + phase) / 11))
        risk = 25 + max(0, close / high52 - 0.9) * 240
        if (close / p5 - 1) * 100 > 15:
            risk += 18
        signals = ["热点板块"] if hot >= 65 else []
        if capital >= 62:
            signals.append("资金流入")
        if close > sum(closes_20) / len(closes_20):
            signals.append("站上20日线")
        if close > sum(closes_20) / len(closes_20) > sum(closes_60) / len(closes_60):
            signals.append("均线多头")
        if 1.05 + 0.45 * math.sin((phase + self._index(run_date)) / 7) >= 1.2:
            signals.append("成交量放大")
        return {
            "stock_code": code,
            "stock_name": name,
            "sector": sector,
            "close": close,
            "pct_change_5": round((close / p5 - 1) * 100, 2),
            "pct_change_20": round((close / p20 - 1) * 100, 2),
            "pct_change_60": round((close / p60 - 1) * 100, 2),
            "ma20": round(sum(closes_20) / len(closes_20), 2),
            "ma60": round(sum(closes_60) / len(closes_60), 2),
            "high_52w": round(high52, 2),
            "volume_ratio": round(1.05 + 0.45 * math.sin((phase + self._index(run_date)) / 7), 2),
            "hot_sector_score": round(hot, 1),
            "capital_flow_score": round(capital, 1),
            "risk_score": round(min(100, risk), 1),
            "signals": signals,
            "data_origin": "mock",
        }

    def fetch(self, run_date: date, tracked_stocks: list[dict[str, str]]) -> dict[str, Any]:
        trading_day = previous_business_day(run_date)
        candidates = [self._stock_row(item, trading_day) for item in MOCK_UNIVERSE]
        idx = self._index(trading_day)
        benchmark_close = round(3800 * (1 + 0.00025 * idx + 0.035 * math.sin(idx / 16)), 2)
        sector_names = sorted({item[2] for item in MOCK_UNIVERSE})
        sector_indices = {
            name: round(
                1000
                * (
                    1
                    + 0.00035 * idx
                    + 0.055 * math.sin((idx + sum(ord(char) for char in name)) / 14)
                ),
                2,
            )
            for name in sector_names
        }
        sectors = []
        for name in sector_names:
            rows = [row for row in candidates if row["sector"] == name]
            sectors.append(
                {
                    "name": name,
                    "hot_score": round(sum(row["hot_sector_score"] for row in rows) / len(rows), 1),
                    "capital_flow_score": round(
                        sum(row["capital_flow_score"] for row in rows) / len(rows), 1
                    ),
                    "index_close": sector_indices[name],
                }
            )
        return {
            "schema_version": "1.0",
            "run_date": run_date.isoformat(),
            "market_as_of": trading_day.isoformat(),
            "source": self.name,
            "is_mock": True,
            "market": {
                "risk_level": "中",
                "indices": [
                    {
                        "code": "000300.SH",
                        "name": "沪深300",
                        "close": benchmark_close,
                    }
                ],
            },
            "sectors": sectors,
            "capital_flow": {
                "summary": "离线 mock：板块资金分仅用于验证工作流，不代表真实资金流。",
                "top_sectors": [
                    item["name"]
                    for item in sorted(
                        sectors, key=lambda row: row["capital_flow_score"], reverse=True
                    )[:3]
                ],
            },
            "news": [
                {
                    "title": f"{trading_day.isoformat()} 模拟市场热点快照",
                    "published_at": f"{trading_day.isoformat()} 14:30:00",
                    "summary": "该条目为离线测试数据。接入真实数据源后替换。",
                }
            ],
            "candidates": candidates,
            "price_book": {
                "stocks": {
                    row["stock_code"]: {
                        "name": row["stock_name"],
                        "sector": row["sector"],
                        "close": row["close"],
                    }
                    for row in candidates
                },
                "indices": {"000300.SH": benchmark_close},
                "sectors": sector_indices,
            },
            "data_quality": {
                "candidate_count": len(candidates),
                "notes": ["当前为确定性 mock 数据；所有结论仅用于工作流测试。"],
            },
        }


class FileProvider(MarketDataProvider):
    name = "file"

    def fetch(self, run_date: date, tracked_stocks: list[dict[str, str]]) -> dict[str, Any]:
        pattern = self.config.get("snapshot_pattern", "data/market_snapshot/{date}.json")
        path = self.root / pattern.format(date=run_date.isoformat())
        data = read_json(path)
        if not isinstance(data, dict):
            raise RuntimeError(f"未找到或无法读取市场快照：{path}")
        data.setdefault("source", self.name)
        data.setdefault("is_mock", False)
        data.setdefault("run_date", run_date.isoformat())
        data.setdefault("market_as_of", run_date.isoformat())
        data.setdefault("candidates", [])
        data.setdefault("price_book", {"stocks": {}, "indices": {}, "sectors": {}})
        return data


class YixinProvider(MarketDataProvider):
    name = "yixin"

    def _normalize_trade_date(self, value: Any) -> str | None:
        text = str(value or "").strip()
        if not text or "->" in text:
            return None
        zh_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
        if zh_match:
            year, month, day = zh_match.groups()
            return f"{year}-{int(month):02d}-{int(day):02d}"
        match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", text)
        if not match:
            return None
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"

    def _row_trade_date(self, row: dict[str, Any]) -> str | None:
        for key in (
            "交易日期",
            "截止交易日期",
            "trade_date",
            "日期",
            "time_scope_value",
        ):
            trade_date = self._normalize_trade_date(row.get(key))
            if trade_date:
                return trade_date
        return None

    def _row_close_value(self, module, row: dict[str, Any]) -> float | None:
        direct_close = module.direct_close_value(row)
        if direct_close is not None:
            return safe_float(direct_close)
        item_key, item_name, _ = module.normalized_row_key_name(row)
        value = module.row_metric_value(row)
        if item_key == "close" or "收盘价" in item_name or "当前股价" in item_name:
            return safe_float(value)
        return None

    def _row_close_priority(self, row: dict[str, Any]) -> int:
        keys = " ".join(str(key) for key in row.keys())
        if "收盘价(元)" in keys and "复权" not in keys:
            return 3
        if "倒数交易日序号" in row:
            return 2
        return 1

    def _load_workflow_module(self, script: Path):
        spec = importlib.util.spec_from_file_location("installed_yixin_stock_workflow", script)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载 Yixin Skill 脚本：{script}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _extract_closes(self, module, response: dict[str, Any]) -> dict[str, float]:
        return {
            code: float(point["close"])
            for code, point in self._extract_price_points(module, response).items()
            if point.get("close") is not None
        }

    def _extract_price_points(self, module, response: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            code: {
                "close": float(item["close"]),
                "trade_date": item.get("_close_date"),
            }
            for code, item in self._extract_metrics(module, response).items()
            if item.get("close") is not None
        }

    def _extract_metrics(self, module, response: dict[str, Any]) -> dict[str, dict[str, float]]:
        metrics: dict[str, dict[str, Any]] = {}
        for section in module.extract_fin_sections(response):
            for row in module.rows_to_dicts(section.get("content", "")):
                code = module.row_stock_code(row)
                if not code:
                    continue
                item = metrics.setdefault(code, {})
                close_value = self._row_close_value(module, row)
                trade_date = self._row_trade_date(row)
                if close_value is not None and trade_date:
                    item.setdefault("_close_history", []).append(
                        (trade_date, close_value, self._row_close_priority(row))
                    )
                    item["_close_date"] = trade_date
                module.apply_market_metric_row(item, row, use_valuation=False)
                module.apply_momentum_row(item, row, query=section.get("query", ""))
        for item in metrics.values():
            for field in ("short_momentum", "medium_momentum", "long_momentum"):
                daily_changes = item.get(f"_{field}_daily_changes", [])
                cumulative = module.cumulative_percent(daily_changes)
                if cumulative is not None:
                    item[field] = cumulative
            close_history = item.get("_close_history", [])
            dated_closes: dict[str, tuple[float, int]] = {}
            for entry in close_history:
                if len(entry) >= 3:
                    day, close, priority = entry[:3]
                else:
                    day, close = entry[:2]
                    priority = 1
                normalized_day = self._normalize_trade_date(day)
                if not normalized_day or close is None:
                    continue
                existing = dated_closes.get(normalized_day)
                if existing is None or int(priority) > existing[1]:
                    dated_closes[normalized_day] = (close, int(priority))
            latest_pairs = sorted(
                ((day, close_priority[0]) for day, close_priority in dated_closes.items()),
                key=lambda pair: pair[0],
                reverse=True,
            )
            latest_first = [close for _, close in latest_pairs]
            if latest_pairs:
                item["close"] = latest_pairs[0][1]
                item["_close_date"] = latest_pairs[0][0]
            if len(latest_first) >= 20:
                item["ma20"] = sum(latest_first[:20]) / 20
            if len(latest_first) >= 60:
                item["ma60"] = sum(latest_first[:60]) / 60
        return metrics

    def _fetch_tracked_prices(
        self,
        module,
        run_date: date,
        tracked_stocks: list[dict[str, str]],
        raw_dir: Path,
    ) -> dict[str, dict[str, Any]]:
        if not tracked_stocks:
            return {}
        _, fin_db_key = module.load_keys()
        prices: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(tracked_stocks), 30):
            chunk = tracked_stocks[offset : offset + 30]
            labels = "、".join(
                f"{item.get('stock_code', '')} {item.get('stock_name', '')}".strip()
                for item in chunk
            )
            query = (
                f"请返回以下A股在{run_date.isoformat()}最近交易日的收盘价：{labels}。"
                "只返回股票代码、股票名称、交易日期、收盘价，不要返回成交额、市值、PE、PB或PS。"
            )
            status, response = module.yixin_fin_db(fin_db_key, query)
            document = {"status": status, "response": response, "query": query}
            path = raw_dir / "data" / f"adapter-tracked-prices-{offset // 30 + 1}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            prices.update(self._extract_price_points(module, response))
        return prices

    def _load_latest_response(self, raw_dir: Path, pattern: str) -> dict[str, Any]:
        files = sorted((raw_dir / "data").glob(pattern))
        if not files:
            return {}
        document = json.loads(files[-1].read_text(encoding="utf-8"))
        return document.get("response", {})

    def _market_context(
        self,
        module,
        raw_dir: Path,
        selected: list[dict[str, Any]],
    ) -> dict[str, Any]:
        market_response = self._load_latest_response(
            raw_dir, "*-search_market_hotspots.json"
        )
        ai_response = self._load_latest_response(raw_dir, "*-search_ai_news.json")
        market_items = module.fresh_search_items(market_response)
        ai_items = module.fresh_search_items(ai_response)
        combined = module.combine_fresh_news(market_items, ai_items, limit=20)
        hotspot_rows = module.interpret_hotspots(combined)

        news = []
        useful_news = []
        for item in combined:
            title = module.compact_text(item.get("title", ""))
            snippet = module.compact_text(item.get("snippet", ""))
            if (
                "股票行情中心" in title
                or title.startswith("A股资源(")
                or re.search(r":\d+(?:\.\d+)?\s+[+-]?\d+(?:\.\d+)?%", title)
                or "手机号验证码登录" in snippet
            ):
                continue
            useful_news.append(item)
        for item in useful_news[:12]:
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            news.append(
                {
                    "title": module.compact_text(item.get("title", "")),
                    "published_at": item.get("_published_at") or item.get("date", ""),
                    "summary": module.compact_text(item.get("snippet", ""))[:360],
                    "link": item.get("link", ""),
                    "source_name": extra.get("siteName", ""),
                }
            )

        index_patterns = (
            ("000001.SH", "上证指数", (r"沪指报\s*(\d+(?:\.\d+)?)", r"上证指数报\s*(\d+(?:\.\d+)?)")),
            ("399001.SZ", "深证成指", (r"深证成指报\s*(\d+(?:\.\d+)?)",)),
            ("399006.SZ", "创业板指", (r"创业板指报\s*(\d+(?:\.\d+)?)",)),
        )
        indices = []
        for code, name, patterns in index_patterns:
            found = None
            found_at = ""
            for item in combined:
                text = f"{item.get('title', '')} {item.get('snippet', '')}"
                for pattern in patterns:
                    match = re.search(pattern, text)
                    if match:
                        found = safe_float(match.group(1))
                        found_at = item.get("_published_at") or item.get("date", "")
                        break
                if found is not None:
                    break
            if found is not None:
                indices.append(
                    {
                        "code": code,
                        "name": name,
                        "close": found,
                        "as_of": found_at,
                        "source": "Yixin 搜索资讯文本提取",
                    }
                )

        themes = {str(row.get("主题", "")) for row in hotspot_rows}
        for item in selected:
            theme = str(item.get("所属主题", "")).strip()
            if theme and theme not in themes:
                hotspot_rows.append(
                    {
                        "主题": theme,
                        "热点质量分": 50.0,
                        "质量判断": item.get("热点质量", "待确认"),
                        "支撑因素": item.get("热点触发", "候选池命中"),
                        "风险信号": item.get("主要风险", "待持续跟踪"),
                        "选股处理": item.get("热点处理", "不因热点直接加分"),
                    }
                )
                themes.add(theme)

        sectors = []
        for row in hotspot_rows:
            theme = str(row.get("主题", "待确认"))
            related = [
                item
                for item in combined
                if theme in f"{item.get('title', '')} {item.get('snippet', '')}"
            ]
            text = " ".join(
                f"{item.get('title', '')} {item.get('snippet', '')}"
                for item in related
            )
            positive_terms = (
                "资金回流",
                "主力资金流入",
                "放量",
                "涨停",
                "领涨",
                "走强",
                "上调",
            )
            negative_terms = (
                "资金流出",
                "主力资金流出",
                "高位兑现",
                "退潮",
                "跌停",
                "走弱",
                "跳水",
                "调整",
            )
            positive_hits = sum(term in text for term in positive_terms)
            negative_hits = sum(term in text for term in negative_terms)
            sentiment_score = max(
                20.0,
                min(80.0, 50.0 + positive_hits * 6.0 - negative_hits * 8.0),
            )
            sectors.append(
                {
                    "name": theme,
                    "hot_score": safe_float(row.get("热点质量分"), 50.0),
                    "capital_flow_score": round(sentiment_score, 1),
                    "capital_flow_is_inferred": True,
                    "quality": row.get("质量判断", "待确认"),
                    "support": row.get("支撑因素", ""),
                    "risk_signal": row.get("风险信号", ""),
                    "action": row.get("选股处理", ""),
                    "news_count": len(related),
                    "index_close": None,
                }
            )
        sectors.sort(
            key=lambda item: safe_float(item.get("hot_score"), 0.0) or 0.0,
            reverse=True,
        )

        all_text = " ".join(
            f"{item.get('title', '')} {item.get('snippet', '')}"
            for item in combined
        )
        risk_terms = (
            "超4200只个股下跌",
            "赚钱效应非常差",
            "高开低走",
            "跳水",
            "脆弱性",
            "资金流出",
            "跌停",
            "不追高",
        )
        relief_terms = ("指数翻红", "资金回流", "集体上涨", "情绪企稳")
        risk_hits = [term for term in risk_terms if term in all_text]
        relief_hits = [term for term in relief_terms if term in all_text]
        risk_score = max(
            0.0, min(100.0, 45.0 + len(risk_hits) * 6.0 - len(relief_hits) * 4.0)
        )
        if risk_score >= 70:
            risk_level = "高"
        elif risk_score >= 58:
            risk_level = "中高"
        elif risk_score >= 38:
            risk_level = "中"
        else:
            risk_level = "低"
        risk_reason = (
            "；".join(risk_hits[:4])
            if risk_hits
            else "未从新鲜资讯中识别到显著市场风险词"
        )
        top_sectors = [item["name"] for item in sectors[:3]]
        capital_summary = (
            "Yixin 搜索资讯未提供统一结构化资金流表；当前“资金/情绪分”"
            "根据新鲜资讯中的资金流入流出、放量、涨停、走强走弱等词谨慎推断，"
            "不等同于交易所或专业终端资金流数据。"
        )
        return {
            "market": {
                "risk_level": risk_level,
                "risk_score": round(risk_score, 1),
                "risk_reason": risk_reason,
                "indices": indices,
            },
            "sectors": sectors,
            "capital_flow": {
                "summary": capital_summary,
                "top_sectors": top_sectors,
                "is_inferred": True,
            },
            "news": news,
            "hotspot_rows": hotspot_rows,
            "fresh_news_count": len(combined),
        }

    def _build_candidates(
        self,
        selected: list[dict[str, Any]],
        trend_metrics: dict[str, dict[str, Any]],
        formal_rows: list[dict[str, Any]],
        partial_rows: list[dict[str, Any]],
        market_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        technical_rows = {
            str(row.get("股票代码", "")): row
            for row in (formal_rows or partial_rows)
        }
        sector_by_name = {
            str(item.get("name", "")): item
            for item in market_context.get("sectors", [])
        }
        sector_items = list(market_context.get("sectors", []))

        def sector_context_for(sector_name: str) -> dict[str, Any]:
            exact = sector_by_name.get(sector_name, {})
            exact_has_signal = (
                safe_float(exact.get("hot_score"), 50.0) != 50.0
                or safe_float(exact.get("capital_flow_score"), 50.0) != 50.0
                or safe_float(exact.get("news_count"), 0.0)
            )
            if exact and exact_has_signal:
                return exact
            fuzzy = []
            for item in sector_items:
                theme = str(item.get("name", "")).strip()
                if not theme or theme == sector_name:
                    continue
                if theme in sector_name or sector_name in theme:
                    fuzzy.append(item)
            if fuzzy:
                return sorted(
                    fuzzy,
                    key=lambda item: (
                        safe_float(item.get("news_count"), 0.0) or 0.0,
                        safe_float(item.get("hot_score"), 0.0) or 0.0,
                        len(str(item.get("name", ""))),
                    ),
                    reverse=True,
                )[0]
            return exact

        candidates = []
        for base in selected:
            code = str(base.get("股票代码", ""))
            name = str(base.get("股票名称", ""))
            if not code or not name:
                continue
            metrics = trend_metrics.get(code, {})
            technical = technical_rows.get(code, {})
            sector_name = base.get("所属主题", "待确认")
            sector_context = sector_context_for(str(sector_name))
            close = safe_float(metrics.get("close"))
            ma20 = safe_float(metrics.get("ma20"))
            ma60 = safe_float(metrics.get("ma60"))
            p5 = safe_float(metrics.get("short_momentum"))
            high52 = safe_float(metrics.get("high_52w"))
            signals = ["热点板块"]
            if close is not None and ma20 is not None and close > ma20:
                signals.append("站上20日线")
            if (
                close is not None
                and ma20 is not None
                and ma60 is not None
                and close > ma20 > ma60
            ):
                signals.append("均线多头")
            if safe_float(sector_context.get("capital_flow_score"), 50.0) >= 62:
                signals.append("资讯情绪积极")
            risk_score = 35.0
            if p5 is not None and p5 > 15:
                risk_score += 18
            if close is not None and high52 and close / high52 >= 0.95:
                risk_score += 15
            if "偏高" in str(technical.get("位置风险", "")):
                risk_score = max(risk_score, 65.0)
            candidates.append(
                {
                    "stock_code": code,
                    "stock_name": name,
                    "sector": sector_name,
                    "trade_date": metrics.get("_close_date"),
                    "close": close,
                    "pct_change_5": metrics.get("short_momentum"),
                    "pct_change_20": metrics.get("medium_momentum"),
                    "pct_change_60": metrics.get("long_momentum"),
                    "ma20": metrics.get("ma20"),
                    "ma60": metrics.get("ma60"),
                    "high_52w": metrics.get("high_52w"),
                    "hot_sector_score": safe_float(
                        sector_context.get("hot_score"),
                        65 if base.get("热点质量") == "高质量热点" else 55,
                    ),
                    "capital_flow_score": safe_float(
                        sector_context.get("capital_flow_score"), 50
                    ),
                    "capital_flow_is_inferred": bool(
                        market_context.get("capital_flow", {}).get("is_inferred")
                    ),
                    "technical_score": safe_float(technical.get("技术结构分")),
                    "risk_score": round(min(100.0, risk_score), 1),
                    "signals": signals,
                    "reason_from_source": (
                        technical.get("入选理由")
                        or base.get("热点触发")
                        or base.get("主营关联度")
                        or ""
                    ),
                    "risk_from_source": (
                        technical.get("主要风险") or base.get("主要风险") or ""
                    ),
                    "source_structure_status": technical.get("结构状态", ""),
                    "source_momentum_summary": technical.get("趋势动量", ""),
                    "source_volume_price": technical.get("量价K线", ""),
                    "source_chan_structure": technical.get("缠论结构", ""),
                    "source_position_risk": technical.get("位置风险", ""),
                    "source_follow_up": technical.get("后续观察点", ""),
                    "source_supplement": technical.get("补充维度", ""),
                    "yixin_technical_top5": code in technical_rows,
                    "data_origin": "yixin",
                }
            )
        return candidates

    def fetch(self, run_date: date, tracked_stocks: list[dict[str, str]]) -> dict[str, Any]:
        if run_date != date.today():
            raise RuntimeError("Yixin provider 只支持当天运行；历史回放请使用 file provider。")
        script = Path(self.config.get("skill_script", "")).expanduser()
        if not script.is_absolute():
            script = (self.root / script).resolve()
        if not script.exists():
            installed_script = (
                Path.home()
                / ".codex"
                / "skills"
                / "yixin-stock-workflow"
                / "scripts"
                / "run_yixin_stock_workflow.py"
            )
            if installed_script.exists():
                script = installed_script
        if not script.exists():
            raise RuntimeError(f"Yixin Skill 脚本不存在：{script}")
        raw_dir = self.root / "data" / "raw" / "yixin" / run_date.isoformat()
        raw_dir.mkdir(parents=True, exist_ok=True)
        selected_files = sorted((raw_dir / "data").glob("*-selected_candidates.json"))
        trend_files = sorted((raw_dir / "data").glob("*-fin_trends_merged.json"))
        if not trend_files:
            trend_files = sorted((raw_dir / "data").glob("*-fin_trends.json"))
        reuse_existing = bool(self.config.get("reuse_existing_raw", True))
        raw_output_complete = bool(selected_files and trend_files)
        command = [sys.executable, str(script), "--output-dir", str(raw_dir)]
        if self.config.get("skip_image", True):
            command.append("--skip-image")
        if not (reuse_existing and raw_output_complete):
            if self.config.get("require_external_raw", False):
                command_text = " ".join(str(part) for part in command)
                raise RuntimeError(
                    "Yixin raw 产物缺失，且当前配置要求外部顶层采集，"
                    "避免在 Loop 内部嵌套联网子进程。请先运行：\n"
                    f"  {command_text}\n"
                    "或使用项目封装入口：\n"
                    f"  scripts/run_daily_yixin.sh --date {run_date.isoformat()}"
                )
            attempts = max(1, int(self.config.get("workflow_attempts", 3)))
            retry_delay = max(0.0, float(self.config.get("retry_delay_seconds", 5)))
            transient_markers = (
                "nodename nor servname provided",
                "name or service not known",
                "temporary failure in name resolution",
                "connection reset",
                "connection refused",
                "remote end closed connection",
                "timed out",
                "timeout",
            )
            stdout_parts: list[str] = []
            stderr_parts: list[str] = []
            completed = None
            for attempt in range(1, attempts + 1):
                completed = subprocess.run(
                    command, capture_output=True, text=True, check=False
                )
                stdout_parts.append(
                    f"===== attempt {attempt}/{attempts} =====\n{completed.stdout}"
                )
                stderr_parts.append(
                    f"===== attempt {attempt}/{attempts} =====\n{completed.stderr}"
                )
                if completed.returncode == 0:
                    break
                error_text = completed.stderr.lower()
                is_transient = any(
                    marker in error_text for marker in transient_markers
                )
                if not is_transient or attempt == attempts:
                    break
                time.sleep(retry_delay * attempt)
            (raw_dir / "adapter_stdout.log").write_text(
                "\n".join(stdout_parts), encoding="utf-8"
            )
            (raw_dir / "adapter_stderr.log").write_text(
                "\n".join(stderr_parts), encoding="utf-8"
            )
            assert completed is not None
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Yixin 工作流执行失败：{completed.stderr[-1200:]}"
                )
            selected_files = sorted(
                (raw_dir / "data").glob("*-selected_candidates.json")
            )
            trend_files = sorted(
                (raw_dir / "data").glob("*-fin_trends_merged.json")
            )
            if not trend_files:
                trend_files = sorted((raw_dir / "data").glob("*-fin_trends.json"))
            raw_capture_mode = "nested_workflow"
        else:
            raw_capture_mode = "external_or_reused_raw"
        if not selected_files or not trend_files:
            raise RuntimeError("Yixin 工作流缺少结构化候选或趋势输出。")

        selected = json.loads(selected_files[-1].read_text(encoding="utf-8"))
        trend_document = json.loads(trend_files[-1].read_text(encoding="utf-8"))
        response = trend_document.get("response", {})
        module = self._load_workflow_module(script)
        module.EXPECTED_STOCK_COUNT = max(5, len(selected))
        formal_rows = module.formal_technical_top5_rows(response)
        partial_rows = module.build_local_technical_top5(response)
        quality = module.technical_data_quality(response)
        market_context = self._market_context(module, raw_dir, selected)
        trend_metrics = self._extract_metrics(module, response)
        price_points = {
            code: {
                "close": float(item["close"]),
                "trade_date": item.get("_close_date"),
            }
            for code, item in trend_metrics.items()
            if item.get("close") is not None
        }
        missing_tracked_stocks = [
            item
            for item in tracked_stocks
            if item.get("stock_code") not in price_points
        ]
        tracked_price_error = ""
        try:
            tracked_prices = self._fetch_tracked_prices(
                module, run_date, missing_tracked_stocks, raw_dir
            )
        except Exception as exc:
            tracked_prices = {}
            tracked_price_error = f"{type(exc).__name__}: {exc}"
        price_points.update(tracked_prices)
        trade_dates = sorted(
            {
                str(point.get("trade_date"))
                for point in price_points.values()
                if point.get("trade_date")
            }
        )
        market_as_of = trade_dates[-1] if trade_dates else run_date.isoformat()
        selected_by_code = {row.get("股票代码"): row for row in selected}
        tracked_by_code = {row.get("stock_code"): row for row in tracked_stocks}
        candidates = self._build_candidates(
            selected, trend_metrics, formal_rows, partial_rows, market_context
        )
        return {
            "schema_version": "1.0",
            "run_date": run_date.isoformat(),
            "market_as_of": market_as_of,
            "source": self.name,
            "is_mock": False,
            "market": market_context["market"],
            "sectors": market_context["sectors"],
            "capital_flow": market_context["capital_flow"],
            "news": market_context["news"],
            "candidates": candidates,
            "price_book": {
                "stocks": {
                    code: {
                        "name": (
                            selected_by_code.get(code, {}).get("股票名称")
                            or tracked_by_code.get(code, {}).get("stock_name", "")
                        ),
                        "sector": (
                            selected_by_code.get(code, {}).get("所属主题")
                            or tracked_by_code.get(code, {}).get("sector", "")
                        ),
                        "close": point.get("close"),
                        "trade_date": point.get("trade_date"),
                    }
                    for code, point in price_points.items()
                },
                "indices": {},
                "sectors": {},
            },
            "data_quality": {
                "formal_top5_available": bool(formal_rows),
                "yixin_quality": quality,
                "notes": [
                    "Yixin 原始响应已保存。",
                    (
                        "Yixin raw 来源：外部顶层采集或复用已有产物。"
                        if raw_capture_mode == "external_or_reused_raw"
                        else "Yixin raw 来源：Loop 内部兼容采集。"
                    ),
                    f"已标准化 {market_context['fresh_news_count']} 条新鲜资讯和 "
                    f"{len(market_context['sectors'])} 个热点方向。",
                    "资金/情绪分为资讯文本推断值，不冒充结构化真实资金流。",
                    "若标准化字段覆盖不足，本项目会降级为候选观察池，不强行发布正式排名。",
                    *(
                        [
                            "历史观察标的补充收盘价获取失败；相关到期记录将标记为"
                            f" price_unavailable。原因：{tracked_price_error}"
                        ]
                        if tracked_price_error
                        else []
                    ),
                ],
            },
            "raw_output_dir": str(raw_dir.relative_to(self.root)),
            "raw_capture_mode": raw_capture_mode,
        }


def enrich_yixin_market_data_from_raw(
    root: Path,
    run_date: date,
    market_data: dict[str, Any],
    source_config: dict[str, Any],
) -> dict[str, Any]:
    if market_data.get("source") != "yixin":
        return market_data
    provider = YixinProvider(root, source_config.get("yixin", {}))
    script = Path(provider.config.get("skill_script", "")).expanduser()
    if not script.is_absolute():
        script = (root / script).resolve()
    if not script.exists():
        installed_script = (
            Path.home()
            / ".codex"
            / "skills"
            / "yixin-stock-workflow"
            / "scripts"
            / "run_yixin_stock_workflow.py"
        )
        if installed_script.exists():
            script = installed_script
    raw_dir = root / "data" / "raw" / "yixin" / run_date.isoformat()
    if not script.exists() or not raw_dir.exists():
        return market_data
    selected_files = sorted((raw_dir / "data").glob("*-selected_candidates.json"))
    trend_files = sorted((raw_dir / "data").glob("*-fin_trends_merged.json"))
    if not trend_files:
        trend_files = sorted((raw_dir / "data").glob("*-fin_trends.json"))
    if not selected_files or not trend_files:
        return market_data
    module = provider._load_workflow_module(script)
    selected = json.loads(selected_files[-1].read_text(encoding="utf-8"))
    trend_document = json.loads(trend_files[-1].read_text(encoding="utf-8"))
    response = trend_document.get("response", {})
    module.EXPECTED_STOCK_COUNT = max(5, len(selected))
    formal_rows = module.formal_technical_top5_rows(response)
    partial_rows = module.build_local_technical_top5(response)
    trend_metrics = provider._extract_metrics(module, response)
    context = provider._market_context(module, raw_dir, selected)
    candidates = provider._build_candidates(
        selected, trend_metrics, formal_rows, partial_rows, context
    )
    enriched = dict(market_data)
    enriched.update(
        {
            "market": context["market"],
            "sectors": context["sectors"],
            "capital_flow": context["capital_flow"],
            "news": context["news"],
            "candidates": candidates,
        }
    )
    price_book = dict(enriched.get("price_book", {}))
    stock_book = dict(price_book.get("stocks", {}))
    for item in candidates:
        if item.get("close") is None:
            continue
        stock_book[item["stock_code"]] = {
            "name": item["stock_name"],
            "sector": item["sector"],
            "close": item["close"],
            "trade_date": item.get("trade_date"),
        }
    trade_dates = sorted(
        {
            str(item.get("trade_date"))
            for item in stock_book.values()
            if isinstance(item, dict) and item.get("trade_date")
        }
    )
    if trade_dates:
        enriched["market_as_of"] = trade_dates[-1]
    price_book["stocks"] = stock_book
    price_book["indices"] = {
        item["code"]: item["close"]
        for item in context["market"].get("indices", [])
        if item.get("code") and item.get("close") is not None
    }
    enriched["price_book"] = price_book
    quality = dict(enriched.get("data_quality", {}))
    notes = [
        note
        for note in quality.get("notes", [])
        if not str(note).startswith("已标准化")
        and not str(note).startswith("完整候选池保留")
        and "资金/情绪分" not in str(note)
    ]
    notes.extend(
        [
            f"已标准化 {context['fresh_news_count']} 条新鲜资讯和 "
            f"{len(context['sectors'])} 个热点方向。",
            f"完整候选池保留 {len(candidates)} 只；最终观察池由 Loop 二次评分选出。",
            "资金/情绪分为资讯文本推断值，不冒充结构化真实资金流。",
        ]
    )
    quality["notes"] = notes
    enriched["data_quality"] = quality
    return enriched


def build_provider(root: Path, source_config: dict[str, Any], override: str | None = None):
    provider_name = override or source_config.get("provider", "mock")
    if provider_name == "mock":
        return MockProvider(root, source_config.get("mock", {}))
    if provider_name == "file":
        return FileProvider(root, source_config.get("file", {}))
    if provider_name == "yixin":
        return YixinProvider(root, source_config.get("yixin", {}))
    raise RuntimeError(f"未知数据源 provider：{provider_name}")

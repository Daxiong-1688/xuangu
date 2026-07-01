import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from html import escape
from pathlib import Path


ROOT = Path.cwd()
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
CONFIG_PATH = Path(os.environ.get("YIXIN_API_KEYS_FILE", Path.home() / ".config" / "yixin-api" / "api-keys.json"))
CHROME_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
NEWS_LOOKBACK_DAYS = 3
EXPECTED_STOCK_COUNT = 11
MAX_CANDIDATES_FOR_TRENDS = 25
TREND_COMPLETENESS_MIN_RATIO = 0.6
BLOCKED_NEWS_DOMAINS = (
    "guba.eastmoney.com",
    "xyhndec.cn",
)
DEFAULT_HOT_THEMES = (
    "AI算力",
    "人工智能",
    "半导体",
    "机器人",
    "低空经济",
    "创新药",
    "储能",
    "CPO",
)
THEME_KEYWORDS = (
    "人工智能",
    "AI",
    "算力",
    "光模块",
    "CPO",
    "服务器",
    "液冷",
    "半导体",
    "芯片",
    "存储",
    "先进封装",
    "光刻",
    "机器人",
    "自动化",
    "低空",
    "飞行汽车",
    "无人机",
    "创新药",
    "医药",
    "CXO",
    "储能",
    "电力",
    "高端制造",
)
POSITIVE_HOTSPOT_TERMS = (
    "政策",
    "订单",
    "业绩",
    "景气",
    "资本开支",
    "Capex",
    "需求",
    "涨停",
    "突破",
    "国产替代",
    "产业链",
    "加速",
    "落地",
)
NEGATIVE_HOTSPOT_TERMS = (
    "退潮",
    "回调",
    "高位",
    "资金流出",
    "减持",
    "估值过高",
    "跌幅居前",
    "谨慎",
    "调整",
    "分化",
    "套现",
    "欺诈",
)
THEME_STOCK_UNIVERSE = {
    "AI算力": [
        ("300308.SZ", "中际旭创"),
        ("300502.SZ", "新易盛"),
        ("300394.SZ", "天孚通信"),
        ("601138.SH", "工业富联"),
        ("000977.SZ", "浪潮信息"),
        ("000938.SZ", "紫光股份"),
        ("002463.SZ", "沪电股份"),
        ("002281.SZ", "光迅科技"),
    ],
    "CPO": [
        ("300308.SZ", "中际旭创"),
        ("300502.SZ", "新易盛"),
        ("300394.SZ", "天孚通信"),
        ("002281.SZ", "光迅科技"),
        ("300570.SZ", "太辰光"),
        ("688205.SH", "德科立"),
    ],
    "半导体": [
        ("688256.SH", "寒武纪"),
        ("002371.SZ", "北方华创"),
        ("688012.SH", "中微公司"),
        ("688041.SH", "海光信息"),
        ("688981.SH", "中芯国际"),
        ("688072.SH", "拓荆科技"),
        ("600584.SH", "长电科技"),
        ("603986.SH", "兆易创新"),
    ],
    "人工智能": [
        ("688256.SH", "寒武纪"),
        ("002230.SZ", "科大讯飞"),
        ("688111.SH", "金山办公"),
        ("300033.SZ", "同花顺"),
        ("603019.SH", "中科曙光"),
        ("000977.SZ", "浪潮信息"),
    ],
    "机器人": [
        ("300024.SZ", "机器人"),
        ("300124.SZ", "汇川技术"),
        ("002747.SZ", "埃斯顿"),
        ("688017.SH", "绿的谐波"),
        ("603728.SH", "鸣志电器"),
        ("601689.SH", "拓普集团"),
    ],
    "低空经济": [
        ("002085.SZ", "万丰奥威"),
        ("000099.SZ", "中信海直"),
        ("001696.SZ", "宗申动力"),
        ("002389.SZ", "航天彩虹"),
        ("688070.SH", "纵横股份"),
        ("002625.SZ", "光启技术"),
    ],
    "创新药": [
        ("603259.SH", "药明康德"),
        ("600276.SH", "恒瑞医药"),
        ("002821.SZ", "凯莱英"),
        ("300347.SZ", "泰格医药"),
        ("002422.SZ", "科伦药业"),
        ("300760.SZ", "迈瑞医疗"),
    ],
    "储能": [
        ("300750.SZ", "宁德时代"),
        ("300274.SZ", "阳光电源"),
        ("300014.SZ", "亿纬锂能"),
        ("688390.SH", "固德威"),
        ("300827.SZ", "上能电气"),
        ("300068.SZ", "南都电源"),
    ],
    "存储芯片": [
        ("603986.SH", "兆易创新"),
        ("688008.SH", "澜起科技"),
        ("688525.SH", "佰维存储"),
        ("688123.SH", "聚辰股份"),
        ("001309.SZ", "德明利"),
    ],
}


def load_keys():
    search_key = os.environ.get("YIXIN_SEARCH_API_KEY") or os.environ.get("SEARCH_API_KEY")
    fin_db_key = os.environ.get("YIXIN_FIN_DB_API_KEY") or os.environ.get("FIN_DB_API_KEY")
    if search_key and fin_db_key:
        return search_key, fin_db_key

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    try:
        return data["search"], data["fin_db"]
    except KeyError as exc:
        raise SystemExit(
            "Missing Yixin API key mapping. Configure ~/.config/yixin-api/api-keys.json "
            "as {\"search\":\"...\",\"fin_db\":\"...\"}, or set YIXIN_SEARCH_API_KEY "
            "and YIXIN_FIN_DB_API_KEY."
        ) from exc


def configure_output_dir(output_dir):
    global ROOT, DATA_DIR, REPORT_DIR
    ROOT = Path(output_dir).expanduser().resolve()
    DATA_DIR = ROOT / "data"
    REPORT_DIR = ROOT / "reports"


def post_json(url, api_key, payload, timeout=120, retries=2):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-KEY": api_key,
        },
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                return response.status, json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                raise SystemExit("额度已用完，请联系销售升级：https://www.billionsintelligence.com")
            if exc.code in {502, 503, 504} and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc
        except TimeoutError:
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            raise

    raise RuntimeError("request failed after retries")


def yixin_search(api_key, query, count=10):
    return post_json(
        "https://openapi.billionsintelligence.com/api/v2/search",
        api_key,
        {
            "query": query,
            "source": "web",
            "search_mode": "advanced",
            "count": count,
            "time_range": "past 3 days",
        },
        timeout=120,
    )


def yixin_fin_db(api_key, query):
    return post_json(
        "https://openapi.billionsintelligence.com/api/v1/fin_db",
        api_key,
        {"query": query, "data_sources": ["auto"]},
        timeout=240,
    )


def extract_search_items(search_response):
    items = []
    for result in search_response.get("result", []):
        for item in result.get("content", []):
            if item.get("title") or item.get("snippet"):
                items.append(item)
    return items


def parse_item_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).replace(tzinfo=None)
    except ValueError:
        pass

    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def latest_a_share_trade_datetime(now=None):
    current = now or datetime.now()
    if current.weekday() == 5:
        current -= timedelta(days=1)
    elif current.weekday() == 6:
        current -= timedelta(days=2)
    return current


def chinese_date(value):
    return f"{value.year}年{value.month}月{value.day}日"


def filter_fresh_news(items, today=None, lookback_days=NEWS_LOOKBACK_DAYS):
    today = today or datetime.now()
    start = today - timedelta(days=lookback_days)
    end = today + timedelta(days=1)
    filtered = []
    seen_titles = set()

    for item in items:
        published_at = parse_item_datetime(item.get("date"))
        if published_at is None or published_at < start or published_at > end:
            continue

        title = compact_text(item.get("title", ""))
        snippet = compact_text(item.get("snippet", ""))
        link = item.get("link", "")
        if any(domain in link for domain in BLOCKED_NEWS_DOMAINS):
            continue
        if not title or not snippet:
            continue

        normalized_title = re.sub(r"\W+", "", title.lower())
        if normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)

        filtered.append(
            {
                **item,
                "_published_at": published_at.isoformat(),
                "_has_link": bool(link),
            }
        )

    filtered.sort(key=lambda item: (item["_published_at"], item["_has_link"]), reverse=True)
    return filtered


def fresh_search_items(search_response):
    return filter_fresh_news(extract_search_items(search_response))


def combine_fresh_news(*item_groups, limit=12):
    combined = []
    seen_titles = set()
    for group in item_groups:
        for item in group:
            title = compact_text(item.get("title", ""))
            normalized_title = re.sub(r"\W+", "", title.lower())
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            combined.append(item)
    combined.sort(key=lambda item: item.get("_published_at", ""), reverse=True)
    return combined[:limit]


def compact_text(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def first_table_rows(text, limit=12):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells:
            rows.append(cells)
    if len(rows) <= 1:
        return rows
    return [rows[0]] + rows[1 : limit + 1]


def markdown_rows(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def rows_to_dicts(text):
    rows = markdown_rows(text)
    if len(rows) < 2:
        return []
    headers = rows[0]
    dicts = []
    for row in rows[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        dicts.append(dict(zip(headers, padded[: len(headers)])))
    return dicts


def drop_markdown_columns(markdown_text, blocked_keywords):
    rows = markdown_rows(markdown_text)
    if len(rows) < 2:
        return markdown_text
    headers = rows[0]
    keep_indexes = [
        idx
        for idx, header in enumerate(headers)
        if not any(keyword in header for keyword in blocked_keywords)
    ]
    filtered_rows = [[row[idx] if idx < len(row) else "" for idx in keep_indexes] for row in rows]
    lines = [
        "| " + " | ".join(filtered_rows[0]) + " |",
        "| " + " | ".join("---" for _ in filtered_rows[0]) + " |",
    ]
    for row in filtered_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def clean_missing_cell(value):
    text = compact_text(value)
    return text in {"", "-", "None", "none", "NULL", "null", "暂无"}


def normalize_stock_code(value):
    text = compact_text(value).upper()
    match = re.search(r"(\d{6})\.(SH|SZ|BJ)", text)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    match = re.search(r"\b(\d{6})\b", text)
    if not match:
        return ""
    code = match.group(1)
    if code.startswith(("60", "68", "90")):
        suffix = "SH"
    elif code.startswith(("00", "30", "20")):
        suffix = "SZ"
    elif code.startswith(("43", "83", "87", "92")):
        suffix = "BJ"
    else:
        suffix = ""
    return f"{code}.{suffix}" if suffix else code


def row_stock_code(row):
    for key in ("股票代码", "证券代码", "wind_code", "代码"):
        code = normalize_stock_code(row.get(key, ""))
        if code:
            return code
    for value in row.values():
        code = normalize_stock_code(value)
        if code:
            return code
    return ""


def row_stock_name(row):
    for key in ("股票名称", "证券简称", "matched_company_name", "公司名称", "简称", "名称"):
        name = compact_text(row.get(key, ""))
        if name and not normalize_stock_code(name):
            return re.sub(r"(股份有限公司|科技股份有限公司|集团股份有限公司)$", "", name)
    return ""


def row_theme(row):
    for key in ("所属主题", "热点主题", "申万行业分类", "申万行业", "所属行业", "行业", "主营关联度"):
        value = compact_text(row.get(key, ""))
        if value:
            return value[:80]
    return "热点关联"


def dedupe_markdown_by_column(markdown_text, column_name):
    rows = markdown_rows(markdown_text)
    if len(rows) < 2 or column_name not in rows[0]:
        return markdown_text
    key_index = rows[0].index(column_name)
    kept = [rows[0]]
    seen = set()
    for row in rows[1:]:
        key = row[key_index] if key_index < len(row) else ""
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    lines = [
        "| " + " | ".join(kept[0]) + " |",
        "| " + " | ".join("---" for _ in kept[0]) + " |",
    ]
    for row in kept[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def drop_sparse_markdown_columns(markdown_text, max_missing_ratio=0.35):
    rows = markdown_rows(markdown_text)
    if len(rows) < 3:
        return markdown_text
    headers = rows[0]
    body = rows[1:]
    keep_indexes = []
    protected = {"Index", "股票代码", "股票名称", "所属主题", "申万行业"}
    for idx, header in enumerate(headers):
        if header in protected:
            keep_indexes.append(idx)
            continue
        values = [row[idx] if idx < len(row) else "" for row in body]
        missing_ratio = sum(clean_missing_cell(value) for value in values) / max(1, len(values))
        if missing_ratio <= max_missing_ratio:
            keep_indexes.append(idx)
    filtered_rows = [[row[idx] if idx < len(row) else "" for idx in keep_indexes] for row in rows]
    lines = [
        "| " + " | ".join(filtered_rows[0]) + " |",
        "| " + " | ".join("---" for _ in filtered_rows[0]) + " |",
    ]
    for row in filtered_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def markdown_from_dict_rows(rows, headers):
    kept_rows = []
    for row in rows:
        values = [compact_text(row.get(header, "")) for header in headers]
        if any(not clean_missing_cell(value) for value in values):
            kept_rows.append(values)
    if not kept_rows:
        return ""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in kept_rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def compact_pct_change_range_markdown(section, rows):
    grouped = {}
    for row in rows:
        if row_item_key(row).lower() != "pct_change":
            continue
        value = extract_short_momentum(row)
        code = row_stock_code(row)
        name = clean_stock_name(row_stock_name(row))
        if value is None or not code:
            continue
        item = grouped.setdefault(code, {"股票代码": code, "股票名称": name, "values": [], "dates": []})
        item["values"].append(value)
        date = compact_text(row.get("time_scope_value", ""))
        if date:
            item["dates"].append(date)
    if not grouped:
        return ""

    field = momentum_field_for_text(section["query"])
    label_by_field = {
        "short_momentum": "5日累计涨跌幅(%)",
        "medium_momentum": "20日累计涨跌幅(%)",
        "long_momentum": "60日累计涨跌幅(%)",
    }
    value_label = label_by_field.get(field, "区间累计涨跌幅(%)")
    output_rows = []
    for item in grouped.values():
        cumulative = cumulative_percent(item["values"])
        dates = sorted(item["dates"])
        output_rows.append(
            {
                "股票代码": item["股票代码"],
                "股票名称": item["股票名称"],
                "统计区间": f"{dates[0]}->{dates[-1]}" if dates else "",
                value_label: f"{cumulative:.2f}" if cumulative is not None else "暂无",
                "样本数": len(item["values"]),
            }
        )
    output_rows.sort(key=lambda row: row["股票代码"])
    return markdown_from_dict_rows(output_rows, ["股票代码", "股票名称", "统计区间", value_label, "样本数"])


def compact_close_history_markdown(rows):
    grouped = {}
    for row in rows:
        if row_item_key(row).lower() != "close":
            continue
        value = row_metric_value(row)
        code = row_stock_code(row)
        name = clean_stock_name(row_stock_name(row))
        date = compact_text(row.get("time_scope_value", ""))
        if value is None or not code or not date:
            continue
        item = grouped.setdefault(code, {"股票代码": code, "股票名称": name, "history": []})
        item["history"].append((date, value))
    if not grouped:
        return ""

    output_rows = []
    for item in grouped.values():
        latest_first = [
            close
            for _, close in sorted(item["history"], key=lambda pair: pair[0], reverse=True)
        ]
        dates = sorted(date for date, _ in item["history"])
        ma20 = sum(latest_first[:20]) / 20 if len(latest_first) >= 20 else None
        ma60 = sum(latest_first[:60]) / 60 if len(latest_first) >= 60 else None
        output_rows.append(
            {
                "股票代码": item["股票代码"],
                "股票名称": item["股票名称"],
                "统计区间": f"{dates[0]}->{dates[-1]}" if dates else "",
                "最新收盘价(元)": f"{latest_first[0]:.2f}" if latest_first else "暂无",
                "本地20日均线(元)": f"{ma20:.2f}" if ma20 is not None else "暂无",
                "本地60日均线(元)": f"{ma60:.2f}" if ma60 is not None else "暂无",
                "样本数": len(latest_first),
            }
        )
    output_rows.sort(key=lambda row: row["股票代码"])
    return markdown_from_dict_rows(
        output_rows,
        ["股票代码", "股票名称", "统计区间", "最新收盘价(元)", "本地20日均线(元)", "本地60日均线(元)", "样本数"],
    )


def compact_fin_section_content(section):
    rows = rows_to_dicts(section["content"])
    if not rows:
        return ""

    if "涨跌幅" in section["query"] and any(row_item_key(row).lower() == "pct_change" for row in rows):
        compacted = compact_pct_change_range_markdown(section, rows)
        if compacted:
            return compacted

    if any(row_item_key(row).lower() == "close" and "range" in compact_text(row.get("subject_type", "")) for row in rows):
        compacted = compact_close_history_markdown(rows)
        if compacted:
            return compacted

    if {"wind_code", "item_name", "item_value"}.issubset(rows[0].keys()):
        compact_rows = []
        for row in rows:
            value = first_present(row, ("item_value", "指标值", "value"))
            if value is None:
                continue
            compact_rows.append(
                {
                    "股票代码": row_stock_code(row),
                    "股票名称": clean_stock_name(row_stock_name(row)),
                    "指标": row_item_name(row),
                    "数值": compact_text(value),
                    "单位": compact_text(row.get("item_unit", "")),
                    "时间": compact_text(row.get("time_scope_value", "")),
                }
            )
        return markdown_from_dict_rows(compact_rows, ["股票代码", "股票名称", "指标", "数值", "单位", "时间"])

    content = drop_markdown_columns(
        section["content"],
        (
            "Index",
            "entity_order",
            "comp_code",
            "source_table",
            "subject_type",
            "time_scope_type",
            "item_group",
            "item_key",
            "value_type",
            "rank_no",
            "context_type",
            "context_value",
        ),
    )
    return drop_sparse_markdown_columns(content, max_missing_ratio=0.2)


def parse_number(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def first_present(row, keys):
    for key in keys:
        value = row.get(key)
        if value is not None and not clean_missing_cell(value):
            return value
    return None


def first_key_containing(row, *needles):
    for key, value in row.items():
        if all(needle in key for needle in needles) and not clean_missing_cell(value):
            return value
    return None


def row_item_key(row):
    return compact_text(row.get("item_key") or row.get("指标代码") or row.get("指标") or "")


def row_item_name(row):
    return compact_text(row.get("item_name") or row.get("指标名称") or row_item_key(row))


TREND_MOMENTUM_KEYS = {"pct_change", "avg_pct_change"}
TREND_MOMENTUM_NAME_KEYWORDS = ("涨跌幅", "区间平均涨跌幅")
TREND_MOMENTUM_DIRECT_COLUMNS = (
    "最近5个交易日涨跌幅(%)",
    "最近5日涨跌幅(%)",
    "5日涨跌幅(%)",
    "近5日涨跌幅(%)",
    "最近20日涨跌幅(%)",
    "20日涨跌幅(%)",
    "近20日涨跌幅(%)",
    "最近60日涨跌幅(%)",
    "60日涨跌幅(%)",
    "近60日涨跌幅(%)",
    "涨跌幅(%)",
    "区间平均涨跌幅",
)
NON_MOMENTUM_KEYS = {
    "amount",
    "sum_amount",
    "avg_amount",
    "close",
    "open",
    "high",
    "low",
    "high_52w",
    "low_52w",
    "total_mv",
    "float_mv",
    "pe_ttm",
    "pb_lf",
    "ps_ttm",
}


def row_metric_value(row):
    return parse_number(first_present(row, ("item_value", "指标值", "value", "数值")))


def normalized_row_key_name(row):
    item_key = row_item_key(row).lower()
    item_name = row_item_name(row)
    return item_key, item_name, f"{item_key} {item_name}".lower()


def is_sane_percent(value, limit=80):
    return value is not None and -limit <= value <= limit


def cumulative_percent(values):
    multiplier = 1.0
    used = 0
    for value in values:
        if value is None:
            continue
        multiplier *= 1 + value / 100
        used += 1
    if not used:
        return None
    return (multiplier - 1) * 100


def direct_number(row, exact_keys=(), contains_all=()):
    value = first_present(row, exact_keys)
    if value is None and contains_all:
        value = first_key_containing(row, *contains_all)
    return parse_number(value)


def direct_close_value(row):
    return direct_number(
        row,
        (
            "收盘价_元",
            "当前股价_元",
            "当前收盘价_元",
            "当日收盘价(元)",
            "收盘价(元)",
            "当前股价(元)",
        ),
        ("收盘价",),
    )


def direct_ma20_value(row):
    return direct_number(
        row,
        ("20日均线价格(元)", "20日均线(元)", "20日均线_元"),
        ("20日均线",),
    )


def direct_ma60_value(row):
    return direct_number(
        row,
        ("60日均线价格(元)", "60日均线(元)", "60日均线_元"),
        ("60日均线",),
    )


def direct_high_52w_value(row):
    return direct_number(
        row,
        (
            "过去52周最高价_元",
            "52周最高价(元)",
            "52周最高价_元",
            "近1年最高价(元)",
            "过去52周最高价(元)",
        ),
        ("52周", "最高"),
    ) or direct_number(row, contains_all=("1年", "最高"))


def momentum_field_for_text(text):
    text = compact_text(text)
    has_5 = bool(re.search(r"((最近|近)5(日|个交易日)|5(日|个交易日)(的)?(区间)?涨跌幅)", text))
    has_20 = bool(re.search(r"((最近|近)20(日|个交易日)|20(日|个交易日)(的)?(区间)?涨跌幅)", text))
    has_60 = bool(re.search(r"((最近|近)60(日|个交易日)|60(日|个交易日)(的)?(区间)?涨跌幅)", text))
    if sum([has_5, has_20, has_60]) > 1:
        return "short_momentum"
    if has_60:
        return "long_momentum"
    if has_20:
        return "medium_momentum"
    return "short_momentum"


def momentum_field_for_row(row, query=""):
    row_text = " ".join([row_item_key(row), row_item_name(row), " ".join(row.keys())])
    if re.search(r"((最近|近)(5|20|60)(日|个交易日)|(5|20|60)(日|个交易日)(的)?(区间)?涨跌幅)", row_text):
        return momentum_field_for_text(row_text)
    return momentum_field_for_text(query)


def extract_short_momentum(row):
    direct_value = parse_number(first_present(row, TREND_MOMENTUM_DIRECT_COLUMNS))
    if is_sane_percent(direct_value):
        return direct_value

    item_key, item_name, normalized = normalized_row_key_name(row)
    if item_key in NON_MOMENTUM_KEYS:
        return None
    if item_key not in TREND_MOMENTUM_KEYS and not any(keyword in item_name for keyword in TREND_MOMENTUM_NAME_KEYWORDS):
        return None
    value = row_metric_value(row)
    unit = compact_text(row.get("item_unit", ""))
    if unit and unit != "%" and "percent" not in compact_text(row.get("value_type", "")).lower():
        return None
    if not is_sane_percent(value):
        return None
    return value


def apply_momentum_row(item, row, query=""):
    value = extract_short_momentum(row)
    if value is None:
        return
    field = momentum_field_for_row(row, query=query)
    item_key = row_item_key(row).lower()
    time_scope_type = compact_text(row.get("time_scope_type", ""))
    subject_type = compact_text(row.get("subject_type", ""))
    if item_key == "pct_change" and time_scope_type == "trade_date" and "range" in subject_type:
        item.setdefault(f"_{field}_daily_changes", []).append(value)
        return
    item[field] = value
    if field == "short_momentum":
        item["short_momentum"] = value


def apply_market_metric_row(item, row, use_valuation=False):
    item_key, item_name, normalized = normalized_row_key_name(row)
    value = row_metric_value(row)
    time_scope_type = compact_text(row.get("time_scope_type", ""))
    subject_type = compact_text(row.get("subject_type", ""))

    close = direct_close_value(row)
    ma20 = direct_ma20_value(row)
    ma60 = direct_ma60_value(row)
    high_52w = direct_high_52w_value(row)
    if close is not None:
        item["close"] = close
    if ma20 is not None:
        item["ma20"] = ma20
    if ma60 is not None:
        item["ma60"] = ma60
    if high_52w is not None:
        item["high_52w"] = high_52w

    if value is not None:
        if item_key == "close" and time_scope_type == "trade_date" and "range" in subject_type:
            date = compact_text(row.get("time_scope_value", ""))
            item.setdefault("_close_history", []).append((date, value))
            return
        if item_key == "close" or "收盘价" in item_name or "当前股价" in item_name:
            item["close"] = value
        elif item_key in {"ma20", "avg_close_20d"} or "20日均线" in item_name:
            item["ma20"] = value
        elif item_key in {"ma60", "avg_close_60d"} or "60日均线" in item_name:
            item["ma60"] = value
        elif item_key in {"high_52w", "max_high"} or "52周" in item_name or "1年最高" in item_name or "区间最高价" in item_name:
            item["high_52w"] = value
        elif use_valuation and (item_key == "pe_ttm" or "市盈率" in item_name):
            item["pe_ttm"] = value
        elif use_valuation and (item_key == "pb_lf" or "市净率" in item_name):
            item["pb"] = value

    ma20_distance = parse_number(row.get("偏离20日均线_百分比"))
    ma60_distance = parse_number(row.get("偏离60日均线_百分比"))
    distance_52w_high = parse_number(row.get("距离52周高点位置_百分比") or row.get("距52周最高价距离(%)"))
    if ma20_distance is not None:
        item["ma20_distance"] = ma20_distance
    if ma60_distance is not None:
        item["ma60_distance"] = ma60_distance
    if distance_52w_high is not None:
        item["distance_52w_high"] = distance_52w_high


def technical_data_quality(fin_trends_response):
    source_rows = []
    name_to_key = {}
    for section in extract_fin_sections(fin_trends_response):
        for row in rows_to_dicts(section["content"]):
            code = row_stock_code(row)
            name = clean_stock_name(row_stock_name(row))
            if code and name:
                name_to_key[name] = code
            source_rows.append((section["query"], row))

    coverage = {}
    for query, row in source_rows:
        code = row_stock_code(row)
        name = clean_stock_name(row_stock_name(row))
        key = code or name_to_key.get(name) or name
        if not key:
            continue
        item = coverage.setdefault(
            key,
            {
                "code": code or key,
                "name": name,
                "momentum": False,
                "momentum_5d": False,
                "momentum_20d": False,
                "momentum_60d": False,
                "ma20": False,
                "ma60": False,
                "close": False,
                "high_52w": False,
                "close_history": [],
            },
        )
        if extract_short_momentum(row) is not None:
            item["momentum"] = True
            field = momentum_field_for_row(row, query=query)
            if field == "short_momentum":
                item["momentum_5d"] = True
            elif field == "medium_momentum":
                item["momentum_20d"] = True
            elif field == "long_momentum":
                item["momentum_60d"] = True
        item_key, item_name, _ = normalized_row_key_name(row)
        value = row_metric_value(row)
        time_scope_type = compact_text(row.get("time_scope_type", ""))
        subject_type = compact_text(row.get("subject_type", ""))
        if item_key == "close" and time_scope_type == "trade_date" and "range" in subject_type and value is not None:
            item["close_history"].append((compact_text(row.get("time_scope_value", "")), value))
        elif direct_close_value(row) is not None or item_key == "close" or "收盘价" in item_name or "当前股价" in item_name:
            item["close"] = True
        if direct_ma20_value(row) is not None or item_key in {"ma20", "avg_close_20d"} or "20日均线" in item_name:
            item["ma20"] = True
        if direct_ma60_value(row) is not None or item_key in {"ma60", "avg_close_60d"} or "60日均线" in item_name:
            item["ma60"] = True
        if direct_high_52w_value(row) is not None or item_key in {"high_52w", "max_high"} or "52周" in item_name or "1年最高" in item_name or "区间最高价" in item_name:
            item["high_52w"] = True
    for item in coverage.values():
        close_history = item.get("close_history", [])
        if close_history:
            item["close"] = True
        if len(close_history) >= 20:
            item["ma20"] = True
        if len(close_history) >= 60:
            item["ma60"] = True
    total = len(coverage)
    return {
        "total": total,
        "momentum": sum(1 for item in coverage.values() if item["momentum"]),
        "momentum_5d": sum(1 for item in coverage.values() if item["momentum_5d"]),
        "momentum_20d": sum(1 for item in coverage.values() if item["momentum_20d"]),
        "momentum_60d": sum(1 for item in coverage.values() if item["momentum_60d"]),
        "ma20": sum(1 for item in coverage.values() if item["ma20"]),
        "ma60": sum(1 for item in coverage.values() if item["ma60"]),
        "close": sum(1 for item in coverage.values() if item["close"]),
        "high_52w": sum(1 for item in coverage.values() if item["high_52w"]),
    }


def technical_data_quality_note(fin_trends_response):
    quality = technical_data_quality(fin_trends_response)
    total = quality["total"]
    if total == 0:
        return "数据完整性：本轮未识别到可用于技术评分的股票代码。"
    return (
        "数据完整性："
        f"识别候选 {total} 只；"
        f"真实涨跌幅覆盖 {quality['momentum']} 只；"
        f"5/20/60日涨跌幅覆盖 {quality['momentum_5d']}/{quality['momentum_20d']}/{quality['momentum_60d']} 只；"
        f"20日均线覆盖 {quality['ma20']} 只；"
        f"60日均线覆盖 {quality['ma60']} 只；"
        f"收盘价覆盖 {quality['close']} 只；"
        f"52周高点覆盖 {quality['high_52w']} 只。"
        "脚本已禁止把成交额、总市值、PE/PB/PS 等非趋势字段替代为趋势动量。"
    )


def format_momentum_summary(short_momentum, medium_momentum, long_momentum):
    parts = []
    if short_momentum is not None:
        parts.append(f"5日 {short_momentum:.2f}%")
    if medium_momentum is not None:
        parts.append(f"20日 {medium_momentum:.2f}%")
    if long_momentum is not None:
        parts.append(f"60日 {long_momentum:.2f}%")
    return " / ".join(parts) if parts else "暂无"


def trend_quality_is_sufficient(fin_trends_response):
    quality = technical_data_quality(fin_trends_response)
    total = max(quality.get("total", 0), EXPECTED_STOCK_COUNT, 1)
    required = trend_required_count(total)
    return (
        quality.get("momentum", 0) >= required
        and quality.get("close", 0) >= required
        and quality.get("ma20", 0) >= required
        and quality.get("ma60", 0) >= required
    )


def formal_technical_top5_rows(fin_trends_response):
    rows = build_local_technical_top5(fin_trends_response)
    if not rows or not trend_quality_is_sufficient(fin_trends_response):
        return []
    return rows


def clean_stock_name(value):
    text = compact_text(value)
    for suffix in (
        "科技股份有限公司",
        "集团股份有限公司",
        "股份有限公司",
        "有限责任公司",
        "有限公司",
    ):
        text = text.replace(suffix, "")
    text = text.replace("中科", "").replace("成都", "").replace("苏州", "").replace("无锡", "")
    text = text.replace("深圳市", "").replace("浙江", "").replace("富士康", "")
    return text


def find_metric_by_name(metrics, name):
    target = clean_stock_name(name)
    for item in metrics.values():
        item_name = clean_stock_name(item.get("name", ""))
        short_name = clean_stock_name(item.get("short_name", ""))
        if target and (target in item_name or item_name in target or target == short_name):
            return item
    return None


def markdown_table_to_html(text, limit=12):
    rows = first_table_rows(text, limit=limit)
    if not rows:
        return f"<p>{escape(compact_text(text)[:1200])}</p>"
    header = rows[0]
    body = rows[1:]
    html = ["<div class=\"table-wrap\"><table><thead><tr>"]
    html.extend(f"<th>{escape(cell)}</th>" for cell in header)
    html.append("</tr></thead><tbody>")
    for row in body:
        html.append("<tr>")
        html.extend(f"<td>{escape(cell)}</td>" for cell in row)
        html.append("</tr>")
    html.append("</tbody></table></div>")
    return "".join(html)


def compact_valuation_markdown(fin_trends_response):
    valuation_by_code = collect_valuation_metrics(fin_trends_response)
    if not valuation_has_coverage(valuation_by_code):
        return ""

    headers = ["股票代码", "股票名称", "市盈率(TTM)", "市净率(LF)"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for code, item in sorted(valuation_by_code.items()):
        if item.get("pe_ttm") is None and item.get("pb") is None:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    code,
                    item["name"],
                    f"{item['pe_ttm']:g}" if item.get("pe_ttm") is not None else "暂无",
                    f"{item['pb']:g}" if item.get("pb") is not None else "暂无",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def collect_valuation_metrics(fin_trends_response):
    valuation_by_code = {}
    for section in extract_fin_sections(fin_trends_response):
        if not any(keyword in section["query"] for keyword in ("市盈率", "市净率", "估值")):
            continue
        for row in rows_to_dicts(section["content"]):
            code = row_stock_code(row)
            name = row_stock_name(row)
            item_key = row_item_key(row)
            item_name = row_item_name(row)
            value = parse_number(first_present(row, ("item_value", "指标值", "value")))
            if not code or not name or value is None:
                continue
            item = valuation_by_code.setdefault(code, {"name": clean_stock_name(name)})
            normalized_key = compact_text(item_key or item_name).lower()
            normalized_name = compact_text(item_name or item_key).lower()
            if "pe" in normalized_key or "市盈率" in normalized_name:
                item["pe_ttm"] = value
            elif "pb" in normalized_key or "市净率" in normalized_name:
                item["pb"] = value
    return valuation_by_code


def valuation_has_coverage(valuation_by_code, min_coverage=0.8):
    usable = [
        item
        for item in valuation_by_code.values()
        if item.get("pe_ttm") is not None or item.get("pb") is not None
    ]
    return len(usable) >= EXPECTED_STOCK_COUNT * min_coverage


def valuation_is_complete(valuation_by_code):
    return valuation_has_coverage(valuation_by_code)


def collect_growth_metrics(fin_trends_response):
    growth_by_code = {}
    for section in extract_fin_sections(fin_trends_response):
        if not any(keyword in section["query"] for keyword in ("营业收入", "净利润", "同比")):
            continue
        for row in rows_to_dicts(section["content"]):
            code = row_stock_code(row)
            name = row_stock_name(row)
            if not code or not name:
                continue
            item = growth_by_code.setdefault(code, {"name": clean_stock_name(name)})
            item_name = row_item_name(row)
            value = parse_number(first_present(row, ("item_value", "指标值", "value")))
            revenue_value = parse_number(
                first_present(row, ("营业收入同比增速(%)", "营业收入同比增速_百分号", "营收同比(%)"))
                or first_key_containing(row, "营业收入", "同比")
                or first_key_containing(row, "营收", "同比")
            )
            profit_value = parse_number(
                first_present(row, ("净利润同比增速(%)", "净利润同比增速_百分号", "净利润同比(%)"))
                or first_key_containing(row, "净利润", "同比")
            )
            if revenue_value is not None:
                item["revenue_yoy"] = revenue_value
            if profit_value is not None:
                item["profit_yoy"] = profit_value
            if value is None:
                continue
            if "营业收入" in item_name or row.get("item_key") == "yoy_or":
                item["revenue_yoy"] = value
            elif "净利润" in item_name or row.get("item_key") in {"yoyprofit", "yoy_net_profit"}:
                item["profit_yoy"] = value
    return growth_by_code


def compact_growth_markdown(fin_trends_response):
    growth_by_code = collect_growth_metrics(fin_trends_response)
    complete = {
        code: item
        for code, item in growth_by_code.items()
        if item.get("revenue_yoy") is not None and item.get("profit_yoy") is not None
    }
    if len(complete) < EXPECTED_STOCK_COUNT * 0.8:
        return ""
    headers = ["股票代码", "股票名称", "营收同比(%)", "净利润同比(%)"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for code, item in sorted(complete.items()):
        lines.append(
            "| "
            + " | ".join(
                [
                    code,
                    item["name"],
                    f"{item['revenue_yoy']:g}",
                    f"{item['profit_yoy']:g}",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def section_has_enough_coverage(markdown_text, expected=EXPECTED_STOCK_COUNT, min_coverage=0.8):
    rows = rows_to_dicts(markdown_text)
    if not rows:
        return False
    codes = set()
    names = set()
    for row in rows:
        code = row.get("证券代码") or row.get("股票代码") or row.get("wind_code")
        name = row.get("证券简称") or row.get("股票名称") or row.get("matched_company_name") or row.get("公司名称")
        if code:
            codes.add(code)
        elif name:
            names.add(clean_stock_name(name))
    return (len(codes) if codes else len(names)) >= expected * min_coverage


def display_fin_sections(fin_response):
    sections = []
    for section in extract_fin_sections(fin_response):
        is_valuation = any(keyword in section["query"] for keyword in ("市盈率", "市净率", "估值"))
        is_growth = any(keyword in section["query"] for keyword in ("营业收入", "净利润", "同比"))
        if is_valuation or is_growth:
            continue
        content = compact_fin_section_content(section)
        if content and section_has_enough_coverage(content):
            sections.append({**section, "content": content})
    return sections


def candidate_display_markdown(fin_candidates_response, valuation_allowed=False):
    sections = extract_fin_sections(fin_candidates_response)
    if not sections:
        return ""
    content = sections[0]["content"]
    if not valuation_allowed:
        content = drop_markdown_columns(content, ("市盈率", "市净率", "估值"))
    content = dedupe_markdown_by_column(content, "股票代码")
    content = drop_sparse_markdown_columns(content)
    return content


def extract_fin_sections(fin_response):
    sections = []
    for item in fin_response.get("result", []):
        query = compact_text(item.get("query", ""))
        content = item.get("content", "")
        status = item.get("status", "")
        source = item.get("source", "")
        sections.append(
            {
                "query": query,
                "content": content,
                "status": status,
                "source": source,
            }
        )
    return sections


def fin_section_title(query, content=""):
    if "涨跌幅" in query:
        return "最近涨跌幅"
    if "20日均线" in query or "60日均线" in query:
        if "20日均线" not in content and "60日均线" not in content:
            return "当前股价"
        return "均线与当前股价"
    if "成交额" in query:
        return "成交额变化"
    if "52周" in query or "一年最高" in query or "1年最高" in query:
        return "52周价格位置"
    if any(keyword in query for keyword in ("市盈率", "市净率", "估值")):
        return "估值指标"
    if any(keyword in query for keyword in ("营业收入", "净利润", "同比")):
        return "成长与业绩"
    return "金融数据查询结果"


def build_local_technical_top5(fin_trends_response):
    metrics = {}
    sections = extract_fin_sections(fin_trends_response)
    valuation_by_code = collect_valuation_metrics(fin_trends_response)
    use_valuation = valuation_is_complete(valuation_by_code)
    growth_by_code = collect_growth_metrics(fin_trends_response)

    for section in sections:
        query = section["query"]
        rows = rows_to_dicts(section["content"])
        if "涨跌幅" in query:
            for row in rows:
                name = row_stock_name(row)
                code = row_stock_code(row)
                if not name or not code:
                    continue
                item = metrics.setdefault(code, {"code": code, "name": name})
                item["short_name"] = clean_stock_name(name)
                apply_market_metric_row(item, row, use_valuation=use_valuation)
                apply_momentum_row(item, row, query=query)
        elif "20日均线" in query and "60日均线" in query:
            for row in rows:
                name = row_stock_name(row)
                code = row_stock_code(row)
                item_key = row_item_key(row)
                item_name = row_item_name(row)
                value = row_metric_value(row)
                ma20 = direct_ma20_value(row)
                ma60 = direct_ma60_value(row)
                close = direct_close_value(row)
                if not name:
                    continue
                item = metrics.setdefault(code, {"code": code, "name": name}) if code else find_metric_by_name(metrics, name)
                if item is None:
                    continue
                item["short_name"] = clean_stock_name(name)
                apply_market_metric_row(item, row, use_valuation=use_valuation)
                if value is not None:
                    normalized = f"{item_key} {item_name}".lower()
                    if "ma20" in normalized or "20日均线" in normalized:
                        ma20 = value
                    elif "ma60" in normalized or "60日均线" in normalized:
                        ma60 = value
                    elif item_key == "close" or "收盘价" in item_name or "当前股价" in item_name:
                        close = value
                if ma20 is not None:
                    item["ma20"] = ma20
                if ma60 is not None:
                    item["ma60"] = ma60
                if close is not None:
                    item["close"] = close
                item["above_ma20"] = "上方" in row.get("与20日均线位置关系", "") or (
                    item.get("close") is not None and item.get("ma20") is not None and item["close"] > item["ma20"]
                )
                item["above_ma60"] = "上方" in row.get("与60日均线位置关系", "") or (
                    item.get("close") is not None and item.get("ma60") is not None and item["close"] > item["ma60"]
                )
                ma20_distance = parse_number(row.get("偏离20日均线_百分比"))
                ma60_distance = parse_number(row.get("偏离60日均线_百分比"))
                distance_52w_high = parse_number(row.get("距离52周高点位置_百分比") or row.get("距52周最高价距离(%)"))
                if ma20_distance is not None:
                    item["ma20_distance"] = ma20_distance
                if ma60_distance is not None:
                    item["ma60_distance"] = ma60_distance
                if distance_52w_high is not None:
                    item["distance_52w_high"] = distance_52w_high
        elif "52周最高价" in query:
            for row in rows:
                name = row_stock_name(row)
                code = row_stock_code(row)
                item = metrics.setdefault(code, {"code": code, "name": name}) if code else find_metric_by_name(metrics, name)
                if item is not None:
                    apply_market_metric_row(item, row, use_valuation=use_valuation)
                    item_key = row_item_key(row)
                    item_name = row_item_name(row)
                    value = row_metric_value(row)
                    direct_distance = parse_number(row.get("距52周最高价距离(%)") or row.get("距离52周高点位置_百分比"))
                    if direct_distance is not None:
                        item["distance_52w_high"] = direct_distance
                    elif value is not None:
                        normalized = f"{item_key} {item_name}".lower()
                        if item_key == "close" or "收盘价" in item_name or "当前股价" in item_name:
                            item["close"] = value
                        elif "high_52w" in normalized or "52周" in item_name or "1年最高" in item_name:
                            item["high_52w"] = value
        elif any(keyword in query for keyword in ("收盘价", "当前股价", "最高价", "移动平均线")):
            for row in rows:
                name = row_stock_name(row)
                code = row_stock_code(row)
                if not name and not code:
                    continue
                item = metrics.setdefault(code, {"code": code, "name": name}) if code else find_metric_by_name(metrics, name)
                if item is None:
                    continue
                if name:
                    item["short_name"] = clean_stock_name(name)
                    item["name"] = item.get("name") or name
                apply_market_metric_row(item, row, use_valuation=use_valuation)
        elif use_valuation and any(keyword in query for keyword in ("市盈率", "市净率", "估值")):
            for row in rows:
                code = row_stock_code(row)
                name = row_stock_name(row)
                item_key = row_item_key(row)
                item_name = row_item_name(row)
                value = row_metric_value(row)
                if value is None:
                    continue
                item = metrics.setdefault(code, {"code": code, "name": name}) if code else find_metric_by_name(metrics, name)
                if item is None:
                    continue
                normalized_key = compact_text(item_key or item_name).lower()
                normalized_name = compact_text(item_name or item_key).lower()
                if "pe" in normalized_key or "市盈率" in normalized_name:
                    item["pe_ttm"] = value
                elif "pb" in normalized_key or "市净率" in normalized_name:
                    item["pb"] = value

    for item in metrics.values():
        for field in ("short_momentum", "medium_momentum", "long_momentum"):
            daily_changes = item.get(f"_{field}_daily_changes")
            cumulative = cumulative_percent(daily_changes or [])
            if cumulative is not None:
                item[field] = cumulative
        close_history = item.get("_close_history", [])
        if close_history:
            latest_first = [
                close
                for _, close in sorted(
                    ((date, close) for date, close in close_history if date and close is not None),
                    key=lambda pair: pair[0],
                    reverse=True,
                )
            ]
            if latest_first:
                item["close"] = latest_first[0]
            if len(latest_first) >= 20:
                item["ma20"] = sum(latest_first[:20]) / 20
            if len(latest_first) >= 60:
                item["ma60"] = sum(latest_first[:60]) / 60
        if item.get("close") is not None and item.get("ma20") is not None:
            item["above_ma20"] = item["close"] > item["ma20"]
        if item.get("close") is not None and item.get("ma60") is not None:
            item["above_ma60"] = item["close"] > item["ma60"]

    rows = []
    for item in metrics.values():
        if item.get("distance_52w_high") is None and item.get("close") and item.get("high_52w"):
            item["distance_52w_high"] = (item["close"] / item["high_52w"] - 1) * 100
        short_momentum = item.get("short_momentum")
        medium_momentum = item.get("medium_momentum")
        long_momentum = item.get("long_momentum")
        momentum = short_momentum if short_momentum is not None else medium_momentum
        ma20 = item.get("ma20")
        ma60 = item.get("ma60")
        above_ma20 = item.get("above_ma20")
        above_ma60 = item.get("above_ma60")
        distance_52w_high = item.get("distance_52w_high")
        pe_ttm = item.get("pe_ttm")
        pb = item.get("pb")
        growth = growth_by_code.get(item["code"], {})
        revenue_yoy = growth.get("revenue_yoy")
        profit_yoy = growth.get("profit_yoy")
        if momentum is None and (ma20 is None or ma60 is None):
            continue

        score = 58.0
        reasons = []
        risks = []

        if momentum is not None:
            if 0 <= momentum <= 6:
                score += 18 + momentum * 1.5
                reasons.append("短线动量温和增强" if short_momentum is not None else "阶段动量温和增强")
            elif 6 < momentum <= 12:
                score += 18
                reasons.append("短线强势但需防追高" if short_momentum is not None else "阶段强势但需防追高")
                risks.append("短期涨幅偏快" if short_momentum is not None else "阶段涨幅偏快")
            elif momentum < 0:
                score += max(-8, momentum * 2)
                risks.append("短线动量偏弱" if short_momentum is not None else "阶段动量偏弱")
            else:
                score += 8
                risks.append("短期过热风险上升" if short_momentum is not None else "阶段过热风险上升")

        if medium_momentum is not None and long_momentum is not None:
            if medium_momentum > 0 and long_momentum > 0:
                score += 5
                reasons.append("20/60日趋势同向为正")
            elif medium_momentum < 0 and long_momentum < 0:
                score -= 6
                risks.append("20/60日趋势同向偏弱")
        elif medium_momentum is not None:
            if medium_momentum > 0:
                score += 2
            elif medium_momentum < 0:
                score -= 2

        if ma20 is not None and ma60 is not None:
            if ma20 > ma60 and above_ma20 and above_ma60:
                score += 14
                reasons.append("站上20/60日均线且20日线高于60日线")
                structure = "趋势延续"
            elif ma20 > ma60 and above_ma60:
                score += 6
                reasons.append("中期均线仍偏多")
                risks.append("短线低于20日线")
                structure = "回调观察"
            else:
                score -= 10
                risks.append("均线结构偏弱或股价低于关键均线")
                structure = "回调观察"
        else:
            structure = "数据待确认"
            risks.append("均线数据不完整")

        if distance_52w_high is not None:
            if distance_52w_high > -5:
                score -= 5
                risks.append("距离52周高点较近")
                position_risk = "接近前高"
            elif distance_52w_high < -30:
                score -= 2
                risks.append("距离前高较远，需确认修复持续性")
                position_risk = "低位修复"
            else:
                score += 4
                position_risk = "中位趋势"
        else:
            position_risk = "待确认"

        if momentum is not None and momentum > 0 and ma20 is not None and ma60 is not None and ma20 > ma60 and above_ma20:
            chan = "疑似中枢上沿突破/三买观察"
            candle = "趋势K线偏强，需用OHLC确认具体形态"
            support = "20日线可作为短线结构观察位"
        elif momentum is not None and momentum < 0 and ma20 is not None and ma60 is not None and ma20 > ma60:
            chan = "上涨中枢内回踩观察"
            candle = "回调阶段，观察是否缩量企稳"
            support = "关注60日线支撑是否有效"
        else:
            chan = "中枢/笔结构待确认"
            candle = "K线结构待OHLC确认"
            support = "等待重新站稳关键均线"

        if not risks:
            risks.append("若放量跌破20日线，技术结构转弱")

        valuation = []
        supplement = []
        if use_valuation and pe_ttm is not None:
            valuation.append(f"PE {pe_ttm:g}")
            if pe_ttm > 80:
                score -= 4
                risks.append("PE估值偏高")
            elif pe_ttm > 0 and pe_ttm < 35:
                score += 2
                reasons.append("PE估值相对温和")
        if use_valuation and pb is not None:
            valuation.append(f"PB {pb:g}")
            if pb > 10:
                score -= 2
                risks.append("PB估值偏高")
        if not use_valuation:
            if revenue_yoy is not None:
                supplement.append(f"营收同比 {revenue_yoy:g}%")
            if profit_yoy is not None:
                supplement.append(f"净利同比 {profit_yoy:g}%")
            if revenue_yoy is not None and revenue_yoy > 30:
                score += 3
                reasons.append("营收增长较快")
            if profit_yoy is not None and profit_yoy > 30:
                score += 3
                reasons.append("利润增长较快")
            if profit_yoy is not None and profit_yoy < 0:
                score -= 5
                risks.append("净利润同比下滑")

        score = round(max(0, min(100, score)), 1)
        rows.append(
            {
                "排名": 0,
                "股票代码": item["code"],
                "股票名称": re.sub(r"(股份有限公司|科技股份有限公司|集团股份有限公司)$", "", item["name"]),
                "综合研究分": score,
                "技术结构分": score,
                "结构状态": structure,
                "补充维度": " / ".join(valuation or supplement) if (valuation or supplement) else "暂无",
                "趋势动量": format_momentum_summary(short_momentum, medium_momentum, long_momentum),
                "量价K线": candle,
                "缠论结构": chan,
                "位置风险": position_risk,
                "入选理由": "；".join(reasons[:3]) or "趋势结构待确认",
                "主要风险": "；".join(risks[:3]),
                "后续观察点": support,
            }
        )

    rows.sort(key=lambda row: row["综合研究分"], reverse=True)
    rows = rows[:5]
    for idx, row in enumerate(rows, 1):
        row["排名"] = idx
    return rows


def technical_top5_markdown(fin_trends_response):
    partial_rows = build_local_technical_top5(fin_trends_response)
    rows = partial_rows if trend_quality_is_sufficient(fin_trends_response) else []
    if not rows:
        opening = "暂无足够趋势数据生成技术结构 TOP 5。"
        if partial_rows:
            opening = "趋势核心字段覆盖未达到正式技术结构 TOP 5 门槛，暂不发布正式排名。"
        return "\n\n".join(
            [
                opening,
                technical_data_quality_note(fin_trends_response),
                "建议：继续补齐真实涨跌幅、收盘价、20/60日均线和52周位置；在补数达标前，本轮只作为候选观察池，不输出正式技术 TOP5。",
            ]
        )
    headers = [
        "排名",
        "股票代码",
        "股票名称",
        "综合研究分",
        "技术结构分",
        "结构状态",
        "补充维度",
        "趋势动量",
        "量价K线",
        "缠论结构",
        "位置风险",
        "入选理由",
        "主要风险",
        "后续观察点",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(header, "")) for header in headers) + " |")
    lines.extend(
        [
            "",
            technical_data_quality_note(fin_trends_response),
            "",
            "说明：该 TOP 5 由脚本基于可得趋势和均线数据本地计算。K线和缠论结构为简化框架判断，后续如果 fin_db 能稳定返回完整 OHLCV，将升级为更严格的分型、笔、中枢和蜡烛图识别。",
        ]
    )
    return "\n".join(lines)


def detect_themes(items):
    keywords = [
        "AI算力",
        "人工智能",
        "半导体",
        "机器人",
        "CPO",
        "低空经济",
        "创新药",
        "储能",
        "存储芯片",
        "先进封装",
    ]
    counts = {key: 0 for key in keywords}
    for item in items:
        text = f"{item.get('title', '')} {item.get('snippet', '')}"
        for key in keywords:
            if key in text:
                counts[key] += 1
    ranked = sorted(((key, value) for key, value in counts.items() if value), key=lambda x: -x[1])
    return ranked[:6]


def interpret_hotspots(items):
    raw_themes = detect_themes(items)
    if not raw_themes:
        raw_themes = [(theme, 0) for theme in DEFAULT_HOT_THEMES[:4]]

    analyses = []
    for theme, count in raw_themes:
        related_items = [
            item
            for item in items
            if theme in f"{item.get('title', '')} {item.get('snippet', '')}"
        ]
        text = " ".join(f"{item.get('title', '')} {item.get('snippet', '')}" for item in related_items)
        positive_hits = [term for term in POSITIVE_HOTSPOT_TERMS if term in text]
        negative_hits = [term for term in NEGATIVE_HOTSPOT_TERMS if term in text]
        source_count = len(related_items)
        recent_count = 0
        for item in related_items:
            published = parse_item_datetime(item.get("_published_at") or item.get("date"))
            if published and published >= datetime.now() - timedelta(days=1):
                recent_count += 1

        score = 45 + count * 8 + min(12, len(positive_hits) * 4) + min(10, recent_count * 3)
        score -= min(24, len(negative_hits) * 6)
        score = max(0, min(100, score))

        if score >= 75 and not negative_hits:
            quality = "高质量热点"
            action = "可进入重点候选池"
        elif score >= 60:
            quality = "可跟踪热点"
            action = "进入候选池但降低追高权重"
        elif negative_hits:
            quality = "分化/过热热点"
            action = "只观察龙头和低位修复，不因热点直接加分"
        else:
            quality = "弱确认热点"
            action = "暂不作为核心选股依据"

        if negative_hits:
            risk = "、".join(negative_hits[:3])
        else:
            risk = "暂无明显退潮信号"
        if positive_hits:
            support = "、".join(positive_hits[:3])
        else:
            support = "缺少明确业绩/政策催化"

        analyses.append(
            {
                "主题": theme,
                "热度次数": count,
                "近24小时": recent_count,
                "来源数": source_count,
                "热点质量分": round(score, 1),
                "质量判断": quality,
                "支撑因素": support,
                "风险信号": risk,
                "选股处理": action,
            }
        )

    analyses.sort(key=lambda row: row["热点质量分"], reverse=True)
    return analyses


def hotspot_interpretation_markdown(rows):
    if not rows:
        return "暂无足够热点信息进行质量解读。"
    headers = ["主题", "热点质量分", "质量判断", "支撑因素", "风险信号", "选股处理"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(header, "")) for header in headers) + " |")
    lines.extend(
        [
            "",
            "说明：热点只作为第一层过滤，不等同于投资价值。出现退潮、高位、资金流出、估值过高等信号时，候选股会降权，必须再通过趋势、成长、估值完整性和风险检查。",
        ]
    )
    return "\n".join(lines)


def latest_theme_names(payloads):
    ai_items = fresh_search_items(payloads["search_ai_news"][1])
    market_items = fresh_search_items(payloads["search_market_hotspots"][1])
    interpreted = interpret_hotspots(combine_fresh_news(market_items, ai_items, limit=20))
    names = [
        row["主题"]
        for row in interpreted
        if row["热点质量分"] >= 55 and row["质量判断"] != "弱确认热点"
    ]
    for theme in DEFAULT_HOT_THEMES:
        if theme not in names:
            names.append(theme)
    return names[:8]


def build_candidate_query(themes):
    theme_text = "、".join(themes)
    return (
        f"当前日期为{datetime.now().strftime('%Y年%m月%d日')}。请根据最近3天A股市场热点和产业催化，"
        f"围绕{theme_text}等方向筛选20到30只值得进一步研究的A股上市公司。"
        "这里只需要候选名单，不要查询行情、涨跌幅、财务、估值或成交额。"
        "必须只返回表格，列为：股票代码、股票名称、所属主题、热点触发、主营关联度、主要风险。"
        "不要返回全市场列表，不要返回退市股、ST股、北交所股票，不要给买入卖出建议。"
    )


def candidate_rows_from_response(fin_candidates_response, themes=None, limit=MAX_CANDIDATES_FOR_TRENDS):
    themes = themes or DEFAULT_HOT_THEMES
    sections = extract_fin_sections(fin_candidates_response)
    if any(section["status"] != "success" or "SQL代码执行失败" in section["content"] for section in sections):
        return curated_candidate_rows(themes, limit=limit)

    rows = []
    seen = set()
    theme_terms = set(THEME_KEYWORDS)
    for theme in themes:
        theme_terms.add(theme)
        for part in re.split(r"[/、\s]+", theme):
            if part:
                theme_terms.add(part)

    for section in sections:
        for row in rows_to_dicts(section["content"]):
            headers = set(row.keys())
            if not headers.intersection({"所属主题", "热点主题", "申万行业分类", "申万行业", "所属行业", "行业", "主营关联度"}):
                continue
            code = row_stock_code(row)
            name = row_stock_name(row)
            if not code or not name or code in seen:
                continue
            if code.endswith(".BJ") or "ST" in name.upper() or "退" in name:
                continue

            row_text = compact_text(" ".join(str(value) for value in row.values()))
            score = 0
            for term in theme_terms:
                if term and term in row_text:
                    score += 3
            for key in ("热点触发", "近期催化", "主营关联度", "近期趋势", "成长质量"):
                if not clean_missing_cell(row.get(key, "")):
                    score += 2
            if any(term in row_text for term in ("光模块", "CPO", "算力", "半导体", "机器人", "低空", "创新药", "储能")):
                score += 4
            if "风险" in row_text and not clean_missing_cell(row_text):
                score += 1

            rows.append(
                {
                    "股票代码": code,
                    "股票名称": name,
                    "所属主题": row_theme(row),
                    "热点触发": compact_text(row.get("热点触发") or row.get("近期催化") or "")[:120],
                    "主营关联度": compact_text(row.get("主营关联度") or row.get("基本面概况") or "")[:120],
                    "主要风险": compact_text(row.get("主要风险") or row.get("风险") or "")[:120],
                    "_score": score,
                }
            )
            seen.add(code)

    rows.sort(key=lambda row: row["_score"], reverse=True)
    useful = [row for row in rows if row["_score"] > 0]
    selected = (useful or rows)[:limit]
    if selected:
        return selected
    return curated_candidate_rows(themes, limit=limit)


def apply_hotspot_quality_to_candidates(rows, hotspot_rows):
    quality_by_theme = {row["主题"]: row for row in hotspot_rows}
    adjusted = []
    for row in rows:
        theme = row.get("所属主题", "")
        matched = None
        for name, info in quality_by_theme.items():
            if name in theme or theme in name:
                matched = info
                break
        if matched:
            row = dict(row)
            row["热点质量"] = matched["质量判断"]
            row["热点处理"] = matched["选股处理"]
            row["_score"] = row.get("_score", 0) + max(-2, int((matched["热点质量分"] - 60) / 15))
            if matched["质量判断"] == "分化/过热热点":
                row["主要风险"] = compact_text(row.get("主要风险", "") + "；热点存在分化或过热信号")
            adjusted.append(row)
        else:
            row = dict(row)
            row["热点质量"] = "待确认"
            row["热点处理"] = "不因热点直接加分"
            adjusted.append(row)
    adjusted.sort(key=lambda item: item.get("_score", 0), reverse=True)
    return adjusted


def candidate_rows_markdown(rows):
    if not rows:
        return ""
    headers = ["股票代码", "股票名称", "所属主题", "热点质量", "热点处理", "热点触发", "主营关联度", "主要风险"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(compact_text(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def curated_candidate_rows(themes, limit=MAX_CANDIDATES_FOR_TRENDS):
    rows = []
    seen = set()
    selected_themes = list(themes or DEFAULT_HOT_THEMES)
    for default_theme in DEFAULT_HOT_THEMES:
        if default_theme not in selected_themes:
            selected_themes.append(default_theme)

    for theme in selected_themes:
        matching_keys = [key for key in THEME_STOCK_UNIVERSE if key in theme or theme in key]
        if not matching_keys and ("AI" in theme or "算力" in theme):
            matching_keys = ["AI算力", "人工智能"]
        if not matching_keys and "芯片" in theme:
            matching_keys = ["半导体", "存储芯片"]
        for key in matching_keys:
            for code, name in THEME_STOCK_UNIVERSE.get(key, []):
                if code in seen:
                    continue
                rows.append(
                    {
                        "股票代码": code,
                        "股票名称": name,
                        "所属主题": key,
                        "热点触发": f"最近热点扫描命中：{theme}",
                        "主营关联度": f"{name}与{key}产业链相关",
                        "主要风险": "需结合估值、业绩兑现和技术位置二次确认",
                        "_score": 1,
                    }
                )
                seen.add(code)
                if len(rows) >= limit:
                    return rows
    return rows[:limit]


def candidate_stock_text(candidate_rows):
    if not candidate_rows:
        return "中际旭创、工业富联、新易盛、天孚通信、寒武纪、北方华创、中微公司、汇川技术、机器人、万丰奥威、药明康德"
    return "、".join(f"{row['股票名称']}({row['股票代码']})" for row in candidate_rows)


def chunked_rows(rows, size):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def build_trend_query(candidate_rows):
    stock_text = candidate_stock_text(candidate_rows)
    return (
        f"请对以下A股候选股票进行横向比较：{stock_text}。"
        "查询最近5日、20日、60日涨跌幅，20日/60日均线趋势，成交额变化，距离52周高点位置，"
        "市盈率或市净率等估值水平，营业收入同比和净利润同比增速。"
        "请尽量使用完整表格返回，并标记趋势状态：强趋势、低位修复、回调观察、高位谨慎或趋势破坏。"
        "如果某些估值字段缺失，请保留其他完整字段，不要编造数字。"
    )


def trend_required_count(total):
    return max(1, int(total * TREND_COMPLETENESS_MIN_RATIO))


def build_supplemental_trend_queries(candidate_rows, fin_trends_response):
    quality = technical_data_quality(fin_trends_response)
    total = max(len(candidate_rows), quality.get("total", 0), 1)
    required = trend_required_count(total)
    stock_text = candidate_stock_text(candidate_rows)
    market_date = chinese_date(latest_a_share_trade_datetime())
    queries = []

    if quality.get("momentum_5d", 0) < required:
        queries.append(
            (
                "momentum_5d",
                f"查询{stock_text}截至{market_date}最近5个交易日的涨跌幅或区间平均涨跌幅。"
                "只返回表格，列为：股票代码、股票名称、统计区间、5日涨跌幅(%)。"
                "不要返回成交额、总市值、市盈率、市净率或其他非涨跌幅字段。",
            )
        )
    if quality.get("momentum_20d", 0) < required:
        queries.append(
            (
                "momentum_20d",
                f"查询{stock_text}截至{market_date}最近20个交易日的涨跌幅或区间平均涨跌幅。"
                "只返回表格，列为：股票代码、股票名称、统计区间、20日涨跌幅(%)。"
                "不要返回成交额、总市值、市盈率、市净率或其他非涨跌幅字段。",
            )
        )
    if quality.get("momentum_60d", 0) < required:
        queries.append(
            (
                "momentum_60d",
                f"查询{stock_text}截至{market_date}最近60个交易日的涨跌幅或区间平均涨跌幅。"
                "只返回表格，列为：股票代码、股票名称、统计区间、60日涨跌幅(%)。"
                "不要返回成交额、总市值、市盈率、市净率或其他非涨跌幅字段。",
            )
        )
    if quality.get("ma20", 0) < required or quality.get("ma60", 0) < required:
        queries.append(
            (
                "moving_average",
                f"查询{stock_text}在{market_date}的20日均线和60日均线价格，以及当日收盘价。"
                "必须返回完整表格，列为：股票代码、股票名称、交易日期、收盘价(元)、20日均线(元)、60日均线(元)。",
            )
        )
    if quality.get("high_52w", 0) < required:
        queries.append(
            (
                "high_52w",
                f"查询{stock_text}在{market_date}的当前股价、过去52周最高价。"
                "必须返回完整表格，列为：股票代码、股票名称、交易日期、收盘价(元)、过去52周最高价(元)。",
            )
        )

    return queries


def build_retry_trend_queries(candidate_rows, fin_trends_response):
    quality = technical_data_quality(fin_trends_response)
    total = max(len(candidate_rows), quality.get("total", 0), 1)
    required = trend_required_count(total)
    stock_text = candidate_stock_text(candidate_rows)
    market_date = chinese_date(latest_a_share_trade_datetime())
    queries = []
    if quality.get("ma20", 0) < required or quality.get("ma60", 0) < required:
        for index, chunk in enumerate(chunked_rows(candidate_rows, 10), 1):
            chunk_text = candidate_stock_text(chunk)
            queries.append(
                (
                    f"moving_average_history_{index}",
                    f"查询{chunk_text}截至{market_date}最近70个交易日的每日收盘价，用于本地计算20日均线和60日均线。"
                    "只返回表格，列为：股票代码、股票名称、交易日期、收盘价(元)。不要返回成交额、市值或估值。",
                )
            )
    if quality.get("high_52w", 0) < required:
        queries.append(
            (
                "high_52w_retry",
                f"查询{stock_text}在{market_date}前52周内的最高价，以及{market_date}的收盘价。"
                "只输出汇总表，不输出每日明细。列名固定为：股票代码、股票名称、交易日期、收盘价_元、过去52周最高价_元、距离52周高点位置_百分比。",
            )
        )
    return queries


def merge_fin_responses(base_response, supplemental_responses):
    merged = dict(base_response)
    result = list(base_response.get("result", []))
    success = bool(base_response.get("success", True))
    for response in supplemental_responses:
        result.extend(response.get("result", []))
        success = success and bool(response.get("success", True))
    merged["success"] = success
    merged["result"] = result
    return merged


def run_supplemental_trend_queries(fin_db_key, run_id, candidate_rows, base_response):
    queries = build_supplemental_trend_queries(candidate_rows, base_response)
    records = []
    responses = []

    def run_query(label, query):
        print(f"running fin_trends_supplement_{label}...", flush=True)
        record = {"label": label, "query": query}
        safe_label = re.sub(r"[^a-z0-9_]+", "_", label.lower())
        try:
            status, response = yixin_fin_db(fin_db_key, query)
            record["status"] = status
            records.append(record)
            responses.append(response)
            with (DATA_DIR / f"{run_id}-fin_trends_supplement_{safe_label}.json").open("w", encoding="utf-8") as file:
                json.dump({"status": status, "response": response}, file, ensure_ascii=False, indent=2)
            time.sleep(1)
        except Exception as exc:
            record["error"] = str(exc)
            records.append(record)
            with (DATA_DIR / f"{run_id}-fin_trends_supplement_{safe_label}_error.json").open("w", encoding="utf-8") as file:
                json.dump(record, file, ensure_ascii=False, indent=2)
            print(f"warning: supplemental trend query {label} failed: {exc}", file=sys.stderr, flush=True)

    for label, query in queries:
        run_query(label, query)

    merged = merge_fin_responses(base_response, responses)
    retry_queries = build_retry_trend_queries(candidate_rows, merged)
    for label, query in retry_queries:
        run_query(label, query)

    return merge_fin_responses(base_response, responses), records


def make_html_report(run_id, payloads):
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ai_items = fresh_search_items(payloads["search_ai_news"][1])
    market_items = fresh_search_items(payloads["search_market_hotspots"][1])
    combined = combine_fresh_news(market_items, ai_items, limit=12)
    themes = detect_themes(combined)
    hotspot_rows = interpret_hotspots(combined)
    hotspot_markdown = hotspot_interpretation_markdown(hotspot_rows)
    valuation_allowed = valuation_is_complete(collect_valuation_metrics(payloads["fin_trends"][1]))
    selected_candidates = payloads.get("selected_candidates", [])
    candidate_markdown = candidate_rows_markdown(selected_candidates) or candidate_display_markdown(
        payloads["fin_candidates"][1], valuation_allowed=valuation_allowed
    )
    trend_sections = display_fin_sections(payloads["fin_trends"][1])
    formal_top5_rows = formal_technical_top5_rows(payloads["fin_trends"][1])
    technical_markdown = technical_top5_markdown(payloads["fin_trends"][1])
    valuation_markdown = compact_valuation_markdown(payloads["fin_trends"][1])
    growth_markdown = compact_growth_markdown(payloads["fin_trends"][1])
    supplement_count = len(payloads.get("fin_trend_supplements", []))
    if formal_top5_rows:
        conclusion_done = f"热点发现、候选池、趋势补数、技术结构 TOP5 已生成。补充查询 {supplement_count} 条。"
        conclusion_next = "将 TOP5 作为人工复核清单，结合盘面、公告和个人风险偏好再判断。"
    else:
        conclusion_done = f"热点发现、候选池和财务数据已完成；趋势覆盖仍不足，当前仅作为候选观察池。补充查询 {supplement_count} 条。"
        conclusion_next = "先修复或改写趋势字段查询，等真实涨跌幅和均线覆盖达标后再发布正式 TOP5。"

    theme_cards = []
    for name, count in themes:
        heat = min(95, 60 + count * 8)
        theme_cards.append(
            f"""
            <article class="metric">
              <span>{escape(name)}</span>
              <strong>{heat}</strong>
              <small>出现 {count} 次</small>
            </article>
            """
        )
    if not theme_cards:
        theme_cards.append(
            """
            <article class="metric">
              <span>热点识别</span>
              <strong>待确认</strong>
              <small>需要二次过滤</small>
            </article>
            """
        )

    news_html = []
    for item in combined[:8]:
        title = escape(item.get("title", "无标题"))
        link = item.get("link", "")
        date = escape(item.get("_published_at") or item.get("date", ""))
        snippet = escape(compact_text(item.get("snippet", ""))[:180])
        title_html = f"<a href=\"{escape(link)}\">{title}</a>" if link else title
        news_html.append(
            f"""
            <li>
              <div class="news-title">{title_html}</div>
              <div class="meta">{date}</div>
              <p>{snippet}</p>
            </li>
            """
        )
    if not news_html:
        news_html.append(
            """
            <li>
              <div class="news-title">最近3天暂无通过本地硬过滤的热点资讯</div>
              <div class="meta">请扩大时间范围或调整关键词</div>
              <p>工作流已经过滤掉旧日期、无摘要、无有效时间的搜索结果，避免把过期消息放入报告。</p>
            </li>
            """
        )

    candidate_html = ""
    if candidate_markdown:
        candidate_html = markdown_table_to_html(candidate_markdown, limit=12)
    trend_html = "".join(
        f"""
        <section class="subsection">
          <h3>{escape(fin_section_title(section["query"], section["content"]))}</h3>
          <div class="meta">{escape(section["source"])} · {escape(section["status"])}</div>
          {markdown_table_to_html(section["content"], limit=max(80, EXPECTED_STOCK_COUNT * 2))}
        </section>
        """
        for section in trend_sections
    )
    technical_html = markdown_table_to_html(technical_markdown, limit=5)
    hotspot_html = markdown_table_to_html(hotspot_markdown, limit=8)
    valuation_html = markdown_table_to_html(valuation_markdown, limit=max(40, EXPECTED_STOCK_COUNT)) if valuation_markdown else ""
    growth_html = markdown_table_to_html(growth_markdown, limit=max(40, EXPECTED_STOCK_COUNT)) if growth_markdown else ""

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>智能选股工作流报告 {escape(run_id)}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --ink: #14171f;
      --muted: #657083;
      --line: #d9dee7;
      --panel: #ffffff;
      --accent: #126b5a;
      --accent-2: #c2410c;
      --soft: #eef7f4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.55;
    }}
    .page {{
      width: 1180px;
      margin: 0 auto;
      padding: 36px 36px 52px;
    }}
    header {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 24px;
      align-items: end;
      padding-bottom: 22px;
      border-bottom: 2px solid var(--ink);
    }}
    h1 {{
      margin: 0;
      font-size: 40px;
      line-height: 1.12;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 16px;
    }}
    .stamp {{
      text-align: right;
      color: var(--muted);
      font-size: 14px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin: 22px 0;
    }}
    .metric {{
      min-height: 112px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metric span, .metric small {{ display: block; color: var(--muted); }}
    .metric strong {{ display: block; margin: 8px 0; font-size: 34px; color: var(--accent); }}
    .section {{
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 22px;
    }}
    h2 {{ margin: 0 0 14px; font-size: 22px; }}
    h3 {{ margin: 18px 0 6px; font-size: 16px; }}
    .news-list {{ margin: 0; padding: 0; list-style: none; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .news-list li {{ background: #fbfcfd; border: 1px solid var(--line); border-radius: 8px; padding: 14px; min-height: 132px; }}
    .news-title {{ font-weight: 700; }}
    a {{ color: var(--accent); text-decoration: none; }}
    .meta {{ margin: 4px 0 8px; color: var(--muted); font-size: 12px; }}
    p {{ margin: 0; color: #303846; }}
    .table-wrap {{ width: 100%; overflow: hidden; border: 1px solid var(--line); border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); vertical-align: top; overflow-wrap: anywhere; }}
    th {{ text-align: left; background: var(--soft); color: #20372f; }}
    tr:last-child td {{ border-bottom: 0; }}
    .callout {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 12px;
    }}
    .callout div {{
      border-left: 4px solid var(--accent);
      background: #fbfcfd;
      padding: 12px 14px;
    }}
    .risk {{ border-left-color: var(--accent-2) !important; }}
    .score-note {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-bottom: 14px;
    }}
    .score-note div {{
      background: #fbfcfd;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      color: var(--muted);
      font-size: 12px;
    }}
    .score-note strong {{ display: block; color: var(--ink); font-size: 14px; }}
    footer {{
      margin-top: 18px;
      color: var(--muted);
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div>
        <h1>智能选股工作流报告</h1>
        <div class="subtitle">热点扫描 · 候选股票池 · 历史趋势 · 风险提示 · 最近3天硬过滤</div>
      </div>
      <div class="stamp">
        <div>Run ID：{escape(run_id)}</div>
        <div>{escape(generated_at)}</div>
        <div>A股 · 最近3天有效资讯</div>
      </div>
    </header>

    <section class="grid">
      {''.join(theme_cards)}
    </section>

    <section class="section">
      <h2>自动热点扫描</h2>
      <ol class="news-list">
        {''.join(news_html)}
      </ol>
    </section>

    <section class="section">
      <h2>热点解读与筛选门槛</h2>
      {hotspot_html}
    </section>

    <section class="section">
      <h2>技术结构层与 TOP 5</h2>
      <div class="score-note">
        <div><strong>趋势/动量</strong>均线、相对强弱、ROC、MACD/RSI状态</div>
        <div><strong>量价/K线</strong>放量突破、缩量回踩、长上影/长下影</div>
        <div><strong>缠论结构</strong>分型、笔、中枢、突破回踩、背驰风险</div>
        <div><strong>位置/风险</strong>支撑压力、52周位置、波动率、回撤</div>
      </div>
      {technical_html}
    </section>

    <section class="section">
      <h2>候选股票池</h2>
      {candidate_html}
    </section>

    {f'<section class="section"><h2>估值指标</h2>{valuation_html}</section>' if valuation_html else ''}

    {f'<section class="section"><h2>成长与业绩指标</h2>{growth_html}</section>' if growth_html else ''}

    <section class="section">
      <h2>历史股价与趋势</h2>
      {trend_html}
    </section>

    <section class="section">
      <h2>本轮结论</h2>
      <div class="callout">
        <div><strong>已跑通</strong><p>{escape(conclusion_done)}</p></div>
        <div><strong>下一步</strong><p>{escape(conclusion_next)}</p></div>
        <div class="risk"><strong>合规边界</strong><p>报告仅作投研辅助，不构成买卖建议。</p></div>
      </div>
    </section>
    <footer>由 Yixin search + fin_db 工作流生成。API key 已从本地私密配置读取，未写入报告。</footer>
  </main>
</body>
</html>
"""
    return html


def render_png_from_html(html_path, png_path):
    if not CHROME_PATH.exists():
        print(f"warning: Chrome not found at {CHROME_PATH}; skip png render", file=sys.stderr)
        return False
    cmd = [
        str(CHROME_PATH),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--window-size=1180,4200",
        f"--screenshot={png_path}",
        html_path.as_uri(),
    ]
    subprocess.run(cmd, check=True)
    return True


def make_report(run_id, payloads):
    ai_items = fresh_search_items(payloads["search_ai_news"][1])
    market_items = fresh_search_items(payloads["search_market_hotspots"][1])
    combined = combine_fresh_news(market_items, ai_items, limit=12)
    hotspot_text = hotspot_interpretation_markdown(interpret_hotspots(combined))
    valuation_allowed = valuation_is_complete(collect_valuation_metrics(payloads["fin_trends"][1]))
    selected_candidates = payloads.get("selected_candidates", [])
    candidates_text = candidate_rows_markdown(selected_candidates) or candidate_display_markdown(
        payloads["fin_candidates"][1], valuation_allowed=valuation_allowed
    )
    trend_sections = display_fin_sections(payloads["fin_trends"][1])
    trend_text = "\n\n".join(
        f"### {fin_section_title(section['query'], section['content'])}\n\n{section['content']}" for section in trend_sections
    )
    formal_top5_rows = formal_technical_top5_rows(payloads["fin_trends"][1])
    technical_text = technical_top5_markdown(payloads["fin_trends"][1])
    valuation_text = compact_valuation_markdown(payloads["fin_trends"][1])
    growth_text = compact_growth_markdown(payloads["fin_trends"][1])
    supplement_count = len(payloads.get("fin_trend_supplements", []))
    if formal_top5_rows:
        conclusion_lines = [
            f"- 本轮已完成：热点扫描、热点质量解读、候选方向识别、候选股/趋势/财务数据查询、技术结构评估和 TOP 5 输出；自动补充趋势查询 {supplement_count} 条。",
            "- 下一步建议：把 TOP 5 作为人工复核清单，结合盘面、公告和个人风险偏好再判断。",
            "- 如果金融数据返回里某些字段缺失，本次报告会把这些字段标记为“暂无数据”，不硬编数字。",
        ]
    else:
        conclusion_lines = [
            f"- 本轮已完成：热点扫描、热点质量解读、候选方向识别、候选股/财务数据查询；自动补充趋势查询 {supplement_count} 条后仍未达到正式 TOP5 的趋势覆盖门槛。",
            "- 当前输出定位：候选观察池，不发布正式技术 TOP5，不作为已确认名单。",
            "- 下一步建议：继续收窄 fin_db 趋势字段查询，优先补齐真实 5/20/60 日涨跌幅、20/60 日均线和 52 周高点位置。",
        ]

    lines = [
        "# 智能选股工作流试跑报告",
        "",
        f"- 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 范围：A股，最近3天资讯 + 可得金融数据",
        f"- 候选池：根据最新热点动态筛选 {len(selected_candidates) if selected_candidates else '若干'} 只，不再固定少数股票",
        "- 说明：这是投研辅助报告，不构成买卖建议。",
        "",
        "## 1. 自动热点扫描",
        "",
    ]

    for idx, item in enumerate(combined[:10], 1):
        title = item.get("title", "无标题")
        date = item.get("_published_at") or item.get("date", "")
        link = item.get("link", "")
        snippet = compact_text(item.get("snippet", ""))[:220]
        if link:
            lines.append(f"{idx}. [{title}]({link})")
        else:
            lines.append(f"{idx}. {title}")
        lines.append(f"   - 时间：{date}")
        if snippet:
            lines.append(f"   - 摘要：{snippet}")
    if not combined:
        lines.append("最近3天暂无通过本地硬过滤的热点资讯。已过滤旧日期、无摘要、无有效时间的搜索结果。")

    lines.extend(
        [
            "",
            "## 2. 热点解读与筛选门槛",
            "",
            hotspot_text,
            "",
            "## 3. 技术结构层与 TOP 5",
            "",
            technical_text,
            "",
            "## 4. 候选股票池查询结果",
            "",
            candidates_text[:5000],
            "",
            "## 5. 估值指标",
            "",
            valuation_text or "估值指标覆盖不完整，本轮不展示、不参与评分。",
            "",
            "## 6. 成长与业绩指标",
            "",
            growth_text or "成长与业绩指标覆盖不完整，本轮不展示、不参与评分。",
            "",
            "## 7. 历史股价与趋势查询结果",
            "",
            trend_text,
            "",
            "## 8. 本轮流程结论",
            "",
            *conclusion_lines,
        ]
    )
    return "\n".join(lines) + "\n"


def main():
    global EXPECTED_STOCK_COUNT
    parser = argparse.ArgumentParser(description="Generate a Yixin-powered A-share stock research workflow report.")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory for data/ and reports/ outputs. Defaults to current working directory.",
    )
    parser.add_argument(
        "--skip-image",
        action="store_true",
        help="Generate Markdown and HTML only; skip Chrome-based PNG rendering.",
    )
    args = parser.parse_args()
    configure_output_dir(args.output_dir)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    search_key, fin_db_key = load_keys()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    payloads = {}

    print("running search_market_hotspots...", flush=True)
    status, response = yixin_search(
        search_key,
        "A股 今日热点 板块 政策 利好 资金流向 涨停原因 人工智能 半导体 机器人 低空经济 创新药",
        count=12,
    )
    payloads["search_market_hotspots"] = (status, response)
    with (DATA_DIR / f"{run_id}-search_market_hotspots.json").open("w", encoding="utf-8") as file:
        json.dump({"status": status, "response": response}, file, ensure_ascii=False, indent=2)
    time.sleep(1)

    print("running search_ai_news...", flush=True)
    status, response = yixin_search(
        search_key,
        "AI 人工智能 最新消息 大模型 算力 芯片 机器人 应用 政策 A股 相关公司",
        count=12,
    )
    payloads["search_ai_news"] = (status, response)
    with (DATA_DIR / f"{run_id}-search_ai_news.json").open("w", encoding="utf-8") as file:
        json.dump({"status": status, "response": response}, file, ensure_ascii=False, indent=2)
    time.sleep(1)

    themes = latest_theme_names(payloads)
    hotspot_rows = interpret_hotspots(
        combine_fresh_news(
            fresh_search_items(payloads["search_market_hotspots"][1]),
            fresh_search_items(payloads["search_ai_news"][1]),
            limit=20,
        )
    )
    print("running fin_candidates...", flush=True)
    status, response = yixin_fin_db(fin_db_key, build_candidate_query(themes))
    payloads["fin_candidates"] = (status, response)
    with (DATA_DIR / f"{run_id}-fin_candidates.json").open("w", encoding="utf-8") as file:
        json.dump({"status": status, "response": response}, file, ensure_ascii=False, indent=2)
    selected_candidates = candidate_rows_from_response(response, themes=themes)
    selected_candidates = apply_hotspot_quality_to_candidates(selected_candidates, hotspot_rows)
    payloads["selected_candidates"] = selected_candidates
    EXPECTED_STOCK_COUNT = max(5, len(selected_candidates))
    with (DATA_DIR / f"{run_id}-selected_candidates.json").open("w", encoding="utf-8") as file:
        json.dump(selected_candidates, file, ensure_ascii=False, indent=2)
    print(f"selected_candidates={len(selected_candidates)}", flush=True)
    time.sleep(1)

    print("running fin_trends...", flush=True)
    status, response = yixin_fin_db(fin_db_key, build_trend_query(selected_candidates))
    with (DATA_DIR / f"{run_id}-fin_trends.json").open("w", encoding="utf-8") as file:
        json.dump({"status": status, "response": response}, file, ensure_ascii=False, indent=2)

    response, supplement_records = run_supplemental_trend_queries(fin_db_key, run_id, selected_candidates, response)
    payloads["fin_trends"] = (status, response)
    payloads["fin_trend_supplements"] = supplement_records
    if supplement_records:
        with (DATA_DIR / f"{run_id}-fin_trends_merged.json").open("w", encoding="utf-8") as file:
            json.dump({"status": status, "response": response, "supplements": supplement_records}, file, ensure_ascii=False, indent=2)
    time.sleep(1)

    report = make_report(run_id, payloads)
    report_path = REPORT_DIR / f"{run_id}-workflow-report.md"
    report_path.write_text(report, encoding="utf-8")
    html = make_html_report(run_id, payloads)
    html_path = REPORT_DIR / f"{run_id}-workflow-report.html"
    html_path.write_text(html, encoding="utf-8")
    png_path = REPORT_DIR / f"{run_id}-workflow-report.png"
    rendered = False if args.skip_image else render_png_from_html(html_path, png_path)
    print(f"report={report_path}")
    print(f"html={html_path}")
    if rendered:
        print(f"image={png_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

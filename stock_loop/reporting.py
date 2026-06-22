from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from typing import Any

from .utils import (
    list_run_dates,
    markdown_table,
    pct,
    read_csv,
    read_json,
    safe_float,
    write_text,
)


def selection_reason_markdown(
    run_date: date,
    selected: list[dict[str, Any]],
    strategy_version: str,
) -> str:
    lines = [
        "# 观察股票池入选理由",
        "",
        f"- 日期：{run_date.isoformat()}",
        f"- 策略版本：{strategy_version}",
        "- 定位：研究观察池，不构成投资建议。",
        "",
    ]
    if not selected:
        lines.append("本轮没有标的通过数据完整性与风险过滤。")
        return "\n".join(lines)
    for index, item in enumerate(selected, 1):
        candidate = item.get("_candidate", {})
        lines.extend(
            [
                f"## {index}. {item['stock_name']}（{item['stock_code']}）",
                "",
                f"- 所属方向：{item['sector']}",
                f"- 综合研究分：{item['total_score']}",
                f"- 热点逻辑：热点质量分 {item['hot_sector_score']}；"
                + ("具备热点确认。" if item["hot_sector_score"] >= 65 else "热点仍需确认。"),
                (
                    f"- 资讯情绪逻辑：资讯情绪推断分 {item['capital_flow_score']}；"
                    if candidate.get("capital_flow_is_inferred")
                    else f"- 资金逻辑：资金维度分 {item['capital_flow_score']}；"
                )
                + ("相对积极。" if item["capital_flow_score"] >= 62 else "暂未形成强确认。"),
                f"- 技术结构：技术分 {item['technical_score']}；"
                + _technical_description(candidate),
                f"- 风险点：风险分 {item['risk_score']}（{item['risk_level']}）；"
                + str(candidate.get("risk_from_source") or _risk_description(candidate)),
                f"- 观察重点：{item['reason_summary']}。",
                "",
            ]
        )
    return "\n".join(lines)


def _technical_description(candidate: dict[str, Any]) -> str:
    close = safe_float(candidate.get("close"))
    ma20 = safe_float(candidate.get("ma20"))
    ma60 = safe_float(candidate.get("ma60"))
    if close is None or ma20 is None or ma60 is None:
        return "均线或收盘价字段不完整，只保留为候选观察。"
    if close > ma20 > ma60:
        return "收盘价位于20日线之上，且20日线高于60日线，属于趋势延续观察。"
    if close > ma20:
        return "收盘价位于20日线之上，但中期结构仍需确认。"
    return "当前处于回调观察状态，20日线可作为短线结构观察位。"


def _risk_description(candidate: dict[str, Any]) -> str:
    p5 = safe_float(candidate.get("pct_change_5"))
    close = safe_float(candidate.get("close"))
    high52 = safe_float(candidate.get("high_52w"))
    risks = []
    if p5 is not None and p5 > 15:
        risks.append("短期涨幅偏快")
    if close is not None and high52 and close / high52 >= 0.95:
        risks.append("接近前高，波动可能放大")
    return "、".join(risks) if risks else "需持续观察热点退潮、量价背离和市场风险偏好变化"


def risk_analysis_markdown(
    run_date: date,
    market_data: dict[str, Any],
    selected: list[dict[str, Any]],
    quality: dict[str, Any],
) -> str:
    high_risk = [item for item in selected if item["risk_level"] == "高"]
    lines = [
        "# 风险分析",
        "",
        f"- 日期：{run_date.isoformat()}",
        f"- 市场整体风险：{market_data.get('market', {}).get('risk_level', '待确认')}",
        f"- 数据源：{market_data.get('source', 'unknown')}",
        f"- 数据状态：{'mock，仅用于流程验证' if market_data.get('is_mock') else '真实/外部快照'}",
        "",
        "## 数据完整性风险",
        "",
        f"- 当前池状态：{quality.get('pool_status')}",
        f"- 核心字段覆盖：{quality.get('coverage')}",
    ]
    if not quality.get("formal_pool"):
        lines.append("- 核心趋势字段未达到门槛，本轮不称为正式技术 TOP 5，只输出候选观察池。")
    lines.extend(
        [
            "",
            "## 个股与组合风险",
            "",
            f"- 高风险标的数量：{len(high_risk)}",
            "- 观察池可能集中于相近热门方向，存在主题共振回撤风险。",
            "- 历史收益、指数和板块对比依赖连续每日快照；缺失日期会降低复盘完整性。",
            "",
            "## 策略风险",
            "",
            "- 热点、资金、技术结构均可能在收盘后发生变化，评分不是确定性预测。",
            "- 简化 K 线和缠论描述只用于结构化研究，不能替代完整 OHLCV 分析。",
            "- 不使用成交额、市值、PE/PB 等字段替代真实涨跌幅、均线或52周位置。",
            "- 系统只生成策略观察和风险提示，不输出交易指令或目标价。",
        ]
    )
    return "\n".join(lines)


def daily_report_markdown(
    run_date: date,
    market_data: dict[str, Any],
    selected: list[dict[str, Any]],
    strategy: dict[str, Any],
    quality: dict[str, Any],
    review_text: str,
    suggestion_text: str,
    draft_path: Path | None,
) -> str:
    sectors = sorted(
        market_data.get("sectors", []),
        key=lambda item: safe_float(item.get("hot_score"), 0.0) or 0.0,
        reverse=True,
    )
    flow_is_inferred = bool(
        market_data.get("capital_flow", {}).get("is_inferred")
    )
    flow_column_name = "资金/情绪分（资讯推断）" if flow_is_inferred else "资金分"
    lines = [
        f"# {run_date.isoformat()} 选股 Skill 每日报告",
        "",
        f"- 策略版本：{strategy.get('strategy_version', 'unknown')}",
        f"- 数据源：{market_data.get('source', 'unknown')}",
        f"- 行情日期：{market_data.get('market_as_of', run_date.isoformat())}",
        f"- 观察池状态：{quality.get('pool_status')}",
        "- 声明：本报告为研究辅助输出，不构成投资建议。",
        "",
        "## 今日市场概览",
        "",
        f"- 市场风险等级：{market_data.get('market', {}).get('risk_level', '待确认')}",
        f"- 资金摘要：{market_data.get('capital_flow', {}).get('summary', '暂无')}",
        f"- 数据完整性：{quality.get('coverage')}",
        "",
        "### 热点方向",
        "",
    ]
    if sectors:
        lines.append(
            markdown_table(
                ["方向", "热点分", flow_column_name],
                [
                    [item.get("name"), item.get("hot_score"), item.get("capital_flow_score")]
                    for item in sectors[:8]
                ],
            )
        )
    else:
        lines.append("暂无标准化板块数据。")
    lines.extend(["", "## 今日观察股票池", ""])
    if selected:
        lines.append(
            markdown_table(
                ["代码", "名称", "方向", "观察价", "综合分", "技术分", "风险", "理由摘要"],
                [
                    [
                        item["stock_code"],
                        item["stock_name"],
                        item["sector"],
                        item["selected_price"],
                        item["total_score"],
                        item["technical_score"],
                        item["risk_level"],
                        item["reason_summary"],
                    ]
                    for item in selected
                ],
            )
        )
    else:
        lines.append("本轮没有标的通过过滤条件。")
    lines.extend(
        [
            "",
            "## 风险提示",
            "",
            "- 关注市场整体波动、热点退潮、资金方向反转和个股短期涨幅偏快。",
            "- 数据不完整时只保留候选观察，不强行形成正式技术排名。",
            "",
            "## 历史复盘摘要",
            "",
            _section_body(review_text, "## 分周期表现", "## 重点成功与失败案例"),
            "",
            "## 策略优化建议",
            "",
            _section_body(suggestion_text, "## 建议", "## 变更纪律"),
        ]
    )
    if draft_path:
        lines.extend(
            [
                "",
                "## 候选策略草案",
                "",
                f"已生成 `{draft_path.name}`，但未修改正式策略，需人工确认。",
            ]
        )
    lines.extend(
        [
            "",
            "## 相关文件",
            "",
            "- `market_data.json`：市场结构化快照",
            "- `selected_stocks.csv`：观察股票池",
            "- `selection_reason.md`：逐股理由",
            "- `risk_analysis.md`：风险分析",
            "- `review_previous.md`：历史复盘",
            "- `strategy_suggestion.md`：策略建议",
        ]
    )
    return "\n".join(lines)


def _section_body(text: str, start: str, end: str) -> str:
    if start not in text:
        return text[:1500]
    body = text.split(start, 1)[1]
    if end in body:
        body = body.split(end, 1)[0]
    return body.strip()


def generate_output_summary(root: Path, latest_date: date) -> str:
    accuracy = read_csv(root / "metrics" / "accuracy.csv")
    win_rate = read_csv(root / "metrics" / "win_rate.csv")
    lines = [
        "# 选股 Loop 汇总",
        "",
        f"- 最新运行日期：{latest_date.isoformat()}",
        f"- 最新日报：`runs/{latest_date.isoformat()}/daily_report.md`",
        "- 正式策略不会被自动修改；候选草案位于 `strategy_versions/`。",
        "",
        "## 最新累计指标",
        "",
    ]
    if accuracy:
        lines.append(
            markdown_table(
                ["策略版本", "周期", "样本", "方向准确率"],
                [
                    [
                        row["strategy_version"],
                        row["horizon_days"],
                        row["evaluated_count"],
                        f"{row['rate_pct']}%",
                    ]
                    for row in accuracy
                ],
            )
        )
    else:
        lines.append("暂无已到期样本。")
    lines.extend(["", "## 胜率", ""])
    if win_rate:
        lines.append(
            markdown_table(
                ["策略版本", "周期", "样本", "胜率"],
                [
                    [
                        row["strategy_version"],
                        row["horizon_days"],
                        row["evaluated_count"],
                        f"{row['rate_pct']}%",
                    ]
                    for row in win_rate
                ],
            )
        )
    else:
        lines.append("暂无已到期样本。")
    return "\n".join(lines)


def generate_dashboard_html(root: Path, latest_date: date) -> str:
    run_dir = root / "runs" / latest_date.isoformat()
    selections = read_csv(run_dir / "selected_stocks.csv")
    market_data = read_json(run_dir / "market_data.json", {})
    accuracy = read_csv(root / "metrics" / "accuracy.csv")
    win_rate = read_csv(root / "metrics" / "win_rate.csv")
    return_tracking = read_csv(root / "metrics" / "return_tracking.csv")
    signal_effectiveness = read_csv(root / "metrics" / "signal_effectiveness.csv")
    strategy_version = selections[0].get("strategy_version", "unknown") if selections else "unknown"
    pool_status = selections[0].get("pool_status", "暂无观察池") if selections else "暂无观察池"
    candidates = market_data.get("candidates", [])
    candidates_by_code = {
        str(item.get("stock_code", "")): item for item in candidates
    }
    sectors = sorted(
        market_data.get("sectors", []),
        key=lambda item: safe_float(item.get("hot_score"), 0.0) or 0.0,
        reverse=True,
    )
    indices = market_data.get("market", {}).get("indices", [])
    news = market_data.get("news", [])
    pending_count = sum(row.get("status") == "pending" for row in return_tracking)
    completed_count = sum(row.get("status") == "completed" for row in return_tracking)
    run_count = len(list_run_dates(root))

    def h(value: Any) -> str:
        return html.escape(str("" if value is None else value))

    def number(value: Any, suffix: str = "", fallback: str = "暂无") -> str:
        parsed = safe_float(value)
        return fallback if parsed is None else f"{parsed:.2f}{suffix}"

    def bullet_sections(path: Path) -> list[tuple[str, list[str]]]:
        if not path.exists():
            return []
        sections: list[tuple[str, list[str]]] = []
        title = "摘要"
        items: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("## "):
                if items:
                    sections.append((title, items))
                title = line[3:].strip()
                items = []
            elif line.startswith("- "):
                items.append(line[2:].strip())
            elif re.match(r"^\d+\.\s+", line):
                items.append(re.sub(r"^\d+\.\s+", "", line).strip())
        if items:
            sections.append((title, items))
        return sections

    def section_cards(path: Path, tone: str = "") -> str:
        sections_data = bullet_sections(path)
        if not sections_data:
            return '<div class="empty">暂无结构化内容。</div>'
        return "".join(
            f'<article class="text-card {tone}"><h3>{h(title)}</h3><ul>'
            + "".join(f"<li>{h(item)}</li>" for item in items)
            + "</ul></article>"
            for title, items in sections_data
        )

    def stock_reason_map(path: Path) -> dict[str, list[str]]:
        if not path.exists():
            return {}
        result: dict[str, list[str]] = {}
        for block in path.read_text(encoding="utf-8").split("\n## ")[1:]:
            lines = block.splitlines()
            if not lines or "（" not in lines[0] or "）" not in lines[0]:
                continue
            code = lines[0].rsplit("（", 1)[-1].split("）", 1)[0]
            result[code] = [
                line.strip()[2:]
                for line in lines[1:]
                if line.strip().startswith("- ")
            ]
        return result

    def score_bar(label: str, value: Any, color: str = "blue") -> str:
        score = max(0.0, min(100.0, safe_float(value, 0.0) or 0.0))
        return (
            f'<div class="score-line"><span>{h(label)}</span>'
            f'<div class="track"><i class="{color}" style="width:{score:.1f}%"></i></div>'
            f"<b>{score:.1f}</b></div>"
        )

    stock_cards = []
    reason_details = stock_reason_map(run_dir / "selection_reason.md")
    for rank, row in enumerate(selections, 1):
        candidate = candidates_by_code.get(row.get("stock_code", ""), {})
        signals = [
            item.strip()
            for item in row.get("signals", "").split(";")
            if item.strip()
        ]
        risk_class = {"低": "low", "中": "medium", "高": "high"}.get(
            row.get("risk_level", ""), "medium"
        )
        logic_items = reason_details.get(row.get("stock_code", ""), [])
        stock_cards.append(
            f"""
<article class="stock-card">
  <div class="stock-head">
    <div><span class="rank">#{rank}</span><h3>{h(row.get("stock_name"))}</h3>
    <p>{h(row.get("stock_code"))} · {h(row.get("sector"))}</p></div>
    <div class="total-score"><strong>{h(row.get("total_score"))}</strong><small>综合研究分</small></div>
  </div>
  <div class="chips">
    <span class="chip risk-{risk_class}">风险 {h(row.get("risk_level"))}</span>
    {''.join(f'<span class="chip">{h(signal)}</span>' for signal in signals)}
  </div>
  <div class="stock-facts">
    <div><small>观察价</small><b>{number(row.get("selected_price"))}</b></div>
    <div><small>5日变化</small><b>{number(candidate.get("pct_change_5"), "%")}</b></div>
    <div><small>20日变化</small><b>{number(candidate.get("pct_change_20"), "%")}</b></div>
    <div><small>60日变化</small><b>{number(candidate.get("pct_change_60"), "%")}</b></div>
    <div><small>MA20</small><b>{number(candidate.get("ma20"))}</b></div>
    <div><small>MA60</small><b>{number(candidate.get("ma60"))}</b></div>
  </div>
  <div class="score-stack">
    {score_bar("热点", row.get("hot_sector_score"), "orange")}
    {score_bar("情绪" if candidate.get("capital_flow_is_inferred") else "资金", row.get("capital_flow_score"), "green")}
    {score_bar("技术", row.get("technical_score"), "blue")}
    {score_bar("风险", row.get("risk_score"), "red")}
  </div>
  <p class="reason">{h(row.get("reason_summary"))}</p>
  <div class="logic"><h4>完整入选逻辑</h4><ul>
    {''.join(f'<li>{h(item)}</li>' for item in logic_items) or '<li>暂无更多结构化说明。</li>'}
  </ul></div>
  <details><summary>查看数据质量与观察规则</summary>
    <p>{h(row.get("data_quality_note"))}</p>
    <p>观察周期：{h(row.get("observation_period"))}；策略版本：{h(row.get("strategy_version"))}</p>
  </details>
</article>"""
        )
    stock_cards_html = "".join(stock_cards) or '<div class="empty">本轮没有标的通过过滤条件。</div>'

    flow_header = (
        "资金/情绪分（资讯推断）"
        if market_data.get("capital_flow", {}).get("is_inferred")
        else "资金分"
    )
    sector_rows = "".join(
        f"<tr><td><b>{h(item.get('name'))}</b></td>"
        f"<td>{score_bar('', item.get('hot_score'), 'orange')}</td>"
        f"<td>{score_bar('', item.get('capital_flow_score'), 'green')}</td>"
        f"<td>{number(item.get('index_close'))}</td></tr>"
        for item in sectors
    ) or "<tr><td colspan='4'>暂无板块数据</td></tr>"

    candidate_rows = "".join(
        f"<tr><td>{h(item.get('stock_code'))}</td><td><b>{h(item.get('stock_name'))}</b></td>"
        f"<td>{h(item.get('sector'))}</td><td>{number(item.get('close'))}</td>"
        f"<td>{number(item.get('pct_change_5'), '%')}</td>"
        f"<td>{number(item.get('pct_change_20'), '%')}</td>"
        f"<td>{number(item.get('ma20'))}</td><td>{number(item.get('ma60'))}</td>"
        f"<td>{number(item.get('volume_ratio'))}</td><td>{number(item.get('risk_score'))}</td></tr>"
        for item in candidates
    ) or "<tr><td colspan='10'>暂无候选池数据</td></tr>"

    accuracy_map = {
        (row.get("strategy_version", ""), row.get("horizon_days", "")): row
        for row in accuracy
    }
    win_map = {
        (row.get("strategy_version", ""), row.get("horizon_days", "")): row
        for row in win_rate
    }
    metric_keys = sorted(
        set(accuracy_map) | set(win_map),
        key=lambda item: (item[0], int(item[1] or 0)),
    )
    metric_rows = "".join(
        f"<tr><td>{h(version)}</td><td>{h(horizon)}日</td>"
        f"<td>{h((accuracy_map.get((version, horizon)) or win_map.get((version, horizon)) or {}).get('evaluated_count', 0))}</td>"
        f"<td>{number(accuracy_map.get((version, horizon), {}).get('rate_pct'), '%')}</td>"
        f"<td>{number(win_map.get((version, horizon), {}).get('rate_pct'), '%')}</td></tr>"
        for version, horizon in metric_keys
    ) or (
        f"<tr><td colspan='5'><div class='empty compact'>暂无已到期样本。"
        f"当前有 {pending_count} 条记录等待 1/3/5/10 个交易日观察完成。</div></td></tr>"
    )

    signal_rows = "".join(
        f"<tr><td><b>{h(row.get('signal'))}</b></td><td>{h(row.get('horizon_days'))}日</td>"
        f"<td>{h(row.get('sample_count'))}</td>"
        f"<td>{number(row.get('positive_rate_pct'), '%')}</td>"
        f"<td>{number(row.get('win_rate_pct'), '%')}</td>"
        f"<td>{number(row.get('average_return_pct'), '%')}</td>"
        f"<td>{number(row.get('average_max_drawdown_pct'), '%')}</td></tr>"
        for row in signal_effectiveness
    ) or "<tr><td colspan='7'>样本尚未到期，暂无信号有效性统计。</td></tr>"

    news_html = "".join(
        f"<article class='news-item'><time>{h(item.get('published_at'))}</time>"
        f"<h3>"
        + (
            f"<a href='{h(item.get('link'))}' target='_blank' rel='noreferrer'>{h(item.get('title'))}</a>"
            if item.get("link")
            else h(item.get("title"))
        )
        + f"</h3><p>{h(item.get('summary'))}</p></article>"
        for item in news
    ) or "<div class='empty'>暂无新闻快照。</div>"

    index_text = " / ".join(
        f"{item.get('name', item.get('code', '指数'))} {number(item.get('close'))}"
        for item in indices
    ) or "暂无指数数据"
    source_label = market_data.get("source", "unknown")
    mock_notice = (
        '<div class="notice warning"><b>当前是 mock 数据</b><span>页面内容完整，但数值只用于验证工作流。切换 Yixin 或真实行情快照后，同一页面会展示真实数据。</span></div>'
        if market_data.get("is_mock")
        else '<div class="notice"><b>外部行情数据</b><span>请结合数据源时间与完整性说明阅读结果。</span></div>'
    )
    file_links = "".join(
        f'<a href="../runs/{latest_date.isoformat()}/{filename}">{label}<span>↗</span></a>'
        for filename, label in [
            ("daily_report.md", "完整日报"),
            ("market_data.json", "市场原始快照"),
            ("selected_stocks.csv", "观察池 CSV"),
            ("selection_reason.md", "逐股入选理由"),
            ("risk_analysis.md", "风险分析"),
            ("review_previous.md", "历史复盘"),
            ("strategy_suggestion.md", "策略建议"),
            ("run_log.md", "运行日志"),
        ]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{latest_date.isoformat()} · Stock Selection Loop</title>
<style>
:root{{--ink:#151714;--muted:#6b7068;--paper:#f3f2ea;--card:#fffefa;--line:#d9d9cf;--blue:#3557ff;--orange:#ff7a1a;--green:#21a46b;--red:#e4493f;--yellow:#f4d34a}}
*{{box-sizing:border-box}} html{{scroll-behavior:smooth}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;margin:0;background:var(--paper);color:var(--ink);line-height:1.6}}
a{{color:inherit}} .shell{{max-width:1280px;margin:auto;padding:0 28px 72px}}
.topbar{{position:sticky;top:0;z-index:20;background:rgba(243,242,234,.94);backdrop-filter:blur(16px);border-bottom:1px solid var(--line)}}
.topbar-inner{{max-width:1280px;margin:auto;padding:13px 28px;display:flex;align-items:center;justify-content:space-between;gap:20px}}
.brand{{font-weight:850;letter-spacing:-.02em}} nav{{display:flex;gap:18px;overflow:auto;white-space:nowrap}} nav a{{font-size:13px;text-decoration:none;color:var(--muted)}} nav a:hover{{color:var(--blue)}}
.hero{{padding:64px 0 34px;border-bottom:2px solid var(--ink);display:grid;grid-template-columns:1.4fr .6fr;gap:28px;align-items:end}}
.eyebrow{{font-size:12px;letter-spacing:.18em;font-weight:800;color:var(--blue)}} h1{{font-size:clamp(42px,7vw,86px);line-height:.96;letter-spacing:-.065em;margin:13px 0 20px}}
.hero p{{max-width:720px;color:var(--muted);font-size:17px}} .meta{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line);border:1px solid var(--line)}}
.meta div{{background:var(--card);padding:15px}} .meta small,.kpi small,.stock-facts small,.total-score small{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}
.meta b{{font-size:15px}} .notice{{display:flex;gap:16px;align-items:center;margin:24px 0;padding:14px 18px;background:#e9f3ff;border-left:4px solid var(--blue)}}
.notice.warning{{background:#fff3cd;border-color:var(--orange)}} .notice span{{color:#555b53;font-size:14px}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:24px 0 64px}} .kpi{{background:var(--card);border:1px solid var(--line);padding:20px}}
.kpi strong{{display:block;font-size:30px;line-height:1.1;margin-top:6px}} section{{scroll-margin-top:70px;margin:68px 0}}
.section-head{{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:22px;border-bottom:1px solid var(--line);padding-bottom:12px}}
.section-head h2{{font-size:30px;letter-spacing:-.04em;margin:0}} .section-head p{{margin:0;color:var(--muted);font-size:14px;max-width:620px}}
.stock-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}} .stock-card{{background:var(--card);border:1px solid var(--line);padding:24px}}
.stock-head{{display:flex;justify-content:space-between;gap:18px}} .stock-head h3{{display:inline;font-size:24px;margin:0 0 0 8px}} .stock-head p{{margin:3px 0 0;color:var(--muted)}}
.rank{{font:800 12px ui-monospace,monospace;color:var(--blue)}} .total-score{{text-align:right}} .total-score strong{{font-size:36px;line-height:1}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:18px 0}} .chip{{padding:4px 9px;border-radius:99px;background:#ecece5;font-size:12px}}
.risk-low{{background:#dff5e8;color:#087c49}} .risk-medium{{background:#fff0bd;color:#8a5d00}} .risk-high{{background:#ffe0dc;color:#a62219}}
.stock-facts{{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);margin:16px 0}} .stock-facts div{{padding:10px 12px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}}
.stock-facts b{{font-size:15px}} .score-stack{{display:grid;gap:7px}} .score-line{{display:grid;grid-template-columns:42px 1fr 38px;align-items:center;gap:9px;font-size:12px}}
.score-line b{{font:700 11px ui-monospace,monospace;text-align:right}} .track{{height:7px;background:#e8e8e1;overflow:hidden}} .track i{{display:block;height:100%}}
.track .blue{{background:var(--blue)}} .track .orange{{background:var(--orange)}} .track .green{{background:var(--green)}} .track .red{{background:var(--red)}}
.reason{{border-top:1px solid var(--line);padding-top:15px;margin-top:17px;font-weight:700}} .logic{{background:#f2f2eb;padding:13px 15px;margin:14px 0}}
.logic h4{{font-size:12px;letter-spacing:.08em;margin:0 0 7px;text-transform:uppercase}} .logic ul{{margin:0;padding-left:18px}} .logic li{{font-size:13px;margin:4px 0;color:#464b44}}
details{{font-size:13px;color:var(--muted)}} summary{{cursor:pointer;color:var(--ink);font-weight:700}}
.market-grid{{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(300px,.75fr);gap:16px;align-items:start}}
.panel{{background:var(--card);border:1px solid var(--line);padding:22px;min-width:0;align-self:start}}
.panel-head{{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:16px}}
.panel-head h3{{margin:0}} .panel-head span{{color:var(--muted);font-size:12px;white-space:nowrap}}
.news-list{{max-height:520px;overflow-y:auto;overscroll-behavior:contain;padding-right:10px;scrollbar-gutter:stable}}
.news-list::-webkit-scrollbar{{width:8px}} .news-list::-webkit-scrollbar-track{{background:#ecece5}}
.news-list::-webkit-scrollbar-thumb{{background:#bdbdb4;border-radius:10px}}
.news-item{{padding:15px 0;border-bottom:1px solid var(--line)}} .news-item:first-child{{padding-top:0}} .news-item:last-child{{border:0}}
.news-item time{{font:700 11px ui-monospace,monospace;color:var(--blue)}} .news-item h3{{font-size:16px;line-height:1.45;margin:5px 0}}
.news-item h3 a{{text-decoration-thickness:1px;text-underline-offset:3px}}
.news-item p{{color:var(--muted);font-size:14px;margin:0;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:4;overflow:hidden}}
.table-wrap{{overflow:auto;border:1px solid var(--line);background:var(--card)}} table{{width:100%;border-collapse:collapse;min-width:720px}}
th,td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;vertical-align:middle}} th{{font-size:11px;letter-spacing:.07em;text-transform:uppercase;background:#eeeee6;position:sticky;top:0}}
td .score-line{{min-width:140px}} .text-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}} .text-card{{background:var(--card);border:1px solid var(--line);padding:22px}}
.text-card h3{{margin:0 0 12px;font-size:17px}} .text-card ul{{padding-left:19px;margin:0}} .text-card li{{margin:7px 0;color:#464b44}}
.text-card.risk{{border-top:4px solid var(--orange)}} .text-card.idea{{border-top:4px solid var(--blue)}} .empty{{padding:32px;text-align:center;color:var(--muted);background:var(--card);border:1px dashed var(--line)}}
.empty.compact{{padding:12px;border:0}} .file-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}} .file-grid a{{display:flex;justify-content:space-between;text-decoration:none;background:var(--card);border:1px solid var(--line);padding:15px}}
.file-grid a:hover{{border-color:var(--blue);color:var(--blue)}} footer{{border-top:2px solid var(--ink);padding-top:24px;color:var(--muted);font-size:13px}}
@media(max-width:900px){{.hero,.market-grid{{grid-template-columns:1fr}}.kpis{{grid-template-columns:repeat(2,1fr)}}.stock-grid,.text-grid{{grid-template-columns:1fr}}.file-grid{{grid-template-columns:repeat(2,1fr)}}.news-list{{max-height:460px}}}}
@media(max-width:560px){{.shell,.topbar-inner{{padding-left:16px;padding-right:16px}}.hero{{padding-top:42px}}.kpis{{grid-template-columns:1fr 1fr}}.stock-facts{{grid-template-columns:1fr 1fr}}nav{{display:none}}}}
</style>
</head>
<body>
<div class="topbar"><div class="topbar-inner"><div class="brand">STOCK LOOP / {h(strategy_version)}</div>
<nav><a href="#pool">观察池</a><a href="#market">市场</a><a href="#candidates">全候选</a><a href="#review">复盘</a><a href="#risk">风险与策略</a><a href="#files">文件</a></nav></div></div>
<main class="shell">
<header class="hero">
  <div><div class="eyebrow">FILE-BASED RESEARCH WORKFLOW</div><h1>{latest_date.isoformat()}<br>每日研究看板</h1>
  <p>把当天市场快照、观察股票池、评分理由、风险、历史跟踪和策略建议集中在一个静态 HTML 中。页面不依赖服务器，重新运行后自动更新。</p></div>
  <div class="meta">
    <div><small>策略版本</small><b>{h(strategy_version)}</b></div>
    <div><small>数据源</small><b>{h(source_label)}</b></div>
    <div><small>行情日期</small><b>{h(market_data.get("market_as_of", latest_date.isoformat()))}</b></div>
    <div><small>观察池状态</small><b>{h(pool_status)}</b></div>
  </div>
</header>
{mock_notice}
<div class="kpis">
  <div class="kpi"><small>今日观察标的</small><strong>{len(selections)}</strong></div>
  <div class="kpi"><small>完整候选池</small><strong>{len(candidates)}</strong></div>
  <div class="kpi"><small>市场风险</small><strong>{h(market_data.get("market", {}).get("risk_level", "待确认"))}</strong></div>
  <div class="kpi"><small>历史运行日</small><strong>{run_count}</strong></div>
  <div class="kpi"><small>待到期 / 已完成</small><strong>{pending_count} / {completed_count}</strong></div>
</div>

<section id="pool"><div class="section-head"><div><div class="eyebrow">TODAY'S RESEARCH POOL</div><h2>今日观察股票池</h2></div>
<p>每只标的完整展示观察价、周期变化、均线、四类评分、信号、理由和数据质量。</p></div>
<div class="stock-grid">{stock_cards_html}</div></section>

<section id="market"><div class="section-head"><div><div class="eyebrow">MARKET SNAPSHOT</div><h2>市场与热点快照</h2></div>
<p>{h(index_text)} · {h(market_data.get("capital_flow", {}).get("summary", "暂无资金摘要"))}</p></div>
<div class="market-grid"><div class="panel"><div class="panel-head"><h3>板块热度与资金</h3><span>{len(sectors)} 个方向</span></div><div class="table-wrap"><table>
<thead><tr><th>方向</th><th>热点分</th><th>{h(flow_header)}</th><th>板块指数</th></tr></thead><tbody>{sector_rows}</tbody></table></div></div>
<div class="panel"><div class="panel-head"><h3>新闻与事件</h3><span>{len(news)} 条 · 滚动查看</span></div><div class="news-list">{news_html}</div></div></div></section>

<section id="candidates"><div class="section-head"><div><div class="eyebrow">FULL UNIVERSE</div><h2>完整候选池数据</h2></div>
<p>这里展示市场快照中的全部候选，不再只保留最终 5 只。</p></div>
<div class="table-wrap"><table><thead><tr><th>代码</th><th>名称</th><th>方向</th><th>收盘</th><th>5日</th><th>20日</th><th>MA20</th><th>MA60</th><th>量比</th><th>风险分</th></tr></thead>
<tbody>{candidate_rows}</tbody></table></div></section>

<section id="review"><div class="section-head"><div><div class="eyebrow">HISTORICAL REVIEW</div><h2>累计复盘与信号效果</h2></div>
<p>按策略版本和观察周期持续计算；首日数据尚未到期是正常状态。</p></div>
<div class="panel"><h3>准确率与胜率</h3><div class="table-wrap"><table><thead><tr><th>策略</th><th>周期</th><th>样本</th><th>方向准确率</th><th>胜率</th></tr></thead>
<tbody>{metric_rows}</tbody></table></div></div>
<div class="panel" style="margin-top:16px"><h3>信号有效性</h3><div class="table-wrap"><table><thead><tr><th>信号</th><th>周期</th><th>样本</th><th>正收益率</th><th>胜率</th><th>平均收益</th><th>平均回撤</th></tr></thead>
<tbody>{signal_rows}</tbody></table></div></div></section>

<section id="risk"><div class="section-head"><div><div class="eyebrow">RISK & ITERATION</div><h2>风险与策略迭代</h2></div>
<p>风险分析和 Agent 建议被完整带入页面；正式策略仍需人工确认后才能升级。</p></div>
<div class="text-grid">{section_cards(run_dir / "risk_analysis.md", "risk")}{section_cards(run_dir / "strategy_suggestion.md", "idea")}</div></section>

<section id="files"><div class="section-head"><div><div class="eyebrow">SOURCE FILES</div><h2>本次运行的全部文件</h2></div>
<p>点击可直接打开每日目录中的原始快照、CSV、复盘和日志。</p></div>
<div class="file-grid">{file_links}</div></section>

<footer><b>Stock Selection Loop</b><p>研究辅助输出，不构成投资建议。生成日期 {latest_date.isoformat()}，策略版本 {h(strategy_version)}。</p></footer>
</main>
</body></html>"""

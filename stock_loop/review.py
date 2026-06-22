from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .utils import markdown_table, pct, safe_float, write_text


def generate_review_markdown(
    run_date: date,
    metrics: dict[str, Any],
    observation_periods: list[int],
) -> str:
    completed = metrics.get("completed_rows", [])
    lines = [
        "# 历史观察池复盘",
        "",
        f"- 复盘日期：{run_date.isoformat()}",
        f"- 已完成观察记录：{len(completed)}",
        f"- 待到期观察记录：{metrics.get('pending_count', 0)}",
        "- 说明：收益按各日期快照的收盘价计算；缺失行情不会被视为成功或失败。",
        "",
        "## 分周期表现",
        "",
    ]
    summary_rows = []
    for horizon in observation_periods:
        items = [row for row in completed if int(row["horizon_days"]) == int(horizon)]
        if not items:
            summary_rows.append([horizon, 0, "暂无", "暂无", "暂无", "暂无"])
            continue
        returns = [safe_float(row.get("return_pct"), 0.0) or 0.0 for row in items]
        drawdowns = [safe_float(row.get("max_drawdown_pct"), 0.0) or 0.0 for row in items]
        positives = sum(value > 0 for value in returns)
        beat_index_items = [row for row in items if row.get("outperformed_index") not in ("", None)]
        beat_index = sum(bool(row.get("outperformed_index")) for row in beat_index_items)
        summary_rows.append(
            [
                horizon,
                len(items),
                pct(sum(returns) / len(returns)),
                pct(positives / len(items) * 100),
                pct(min(drawdowns)),
                (
                    pct(beat_index / len(beat_index_items) * 100)
                    if beat_index_items
                    else "暂无"
                ),
            ]
        )
    lines.append(
        markdown_table(
            ["观察期(交易日)", "样本数", "平均收益", "方向命中率", "最差最大回撤", "跑赢指数比例"],
            summary_rows,
        )
    )
    lines.extend(["", "## 重点成功与失败案例", ""])
    if not completed:
        lines.append("历史样本尚未到期。随着每日运行积累，系统会自动补齐 1/3/5/10 日复盘。")
    else:
        ranked = sorted(completed, key=lambda row: safe_float(row.get("return_pct"), 0.0) or 0.0)
        cases = ranked[:3] + list(reversed(ranked[-3:]))
        lines.append(
            markdown_table(
                ["选股日", "代码", "名称", "周期", "收益", "最大回撤", "理由是否成立"],
                [
                    [
                        item["selection_date"],
                        item["stock_code"],
                        item["stock_name"],
                        item["horizon_days"],
                        pct(safe_float(item.get("return_pct"))),
                        pct(safe_float(item.get("max_drawdown_pct"))),
                        "是" if item.get("reason_valid") else "否",
                    ]
                    for item in cases
                ],
            )
        )
    lines.extend(["", "## 信号有效性", ""])
    signals = metrics.get("signals", [])
    if signals:
        ranked_signals = sorted(
            signals,
            key=lambda row: (
                int(row.get("horizon_days", 0)),
                -(safe_float(row.get("win_rate_pct"), 0.0) or 0.0),
            ),
        )
        lines.append(
            markdown_table(
                ["信号", "周期", "样本", "正收益率", "胜率", "平均收益", "平均最大回撤"],
                [
                    [
                        item["signal"],
                        item["horizon_days"],
                        item["sample_count"],
                        pct(safe_float(item.get("positive_rate_pct"))),
                        pct(safe_float(item.get("win_rate_pct"))),
                        pct(safe_float(item.get("average_return_pct"))),
                        pct(safe_float(item.get("average_max_drawdown_pct"))),
                    ]
                    for item in ranked_signals[:15]
                ],
            )
        )
    else:
        lines.append("暂无足够已到期样本评估单一信号。")
    lines.extend(
        [
            "",
            "## 复盘边界",
            "",
            "- 复盘只评价历史观察结果，不追溯修改当时的原始文件。",
            "- mock 数据只用于验证计算链路，不能用于评价真实策略。",
            "- 未获得指数、板块或风险条件数据时，对应字段保留为空，不做猜测。",
        ]
    )
    return "\n".join(lines)


def build_strategy_suggestions(
    run_date: date,
    metrics: dict[str, Any],
    strategy: dict[str, Any],
) -> tuple[str, list[str]]:
    completed = metrics.get("completed_rows", [])
    review = strategy.get("review", {})
    minimum = int(review.get("minimum_samples_for_suggestion", 5))
    keys: list[str] = []
    suggestions: list[str] = []
    if len(completed) < minimum:
        suggestions.append(
            f"当前只有 {len(completed)} 条已到期观察记录，少于 {minimum} 条门槛；暂不建议调整正式策略。"
        )
        keys.append("insufficient_samples")
    else:
        five_day = [row for row in completed if int(row["horizon_days"]) == 5]
        sample = five_day or completed
        returns = [safe_float(row.get("return_pct"), 0.0) or 0.0 for row in sample]
        win_rate = sum(value >= float(review.get("win_return_threshold_pct", 1.0)) for value in returns)
        win_rate = win_rate / len(sample) * 100
        if win_rate < float(review.get("target_win_rate_pct", 55.0)):
            keys.append("tighten_technical_gate")
            suggestions.append(
                "观察期胜率低于目标：候选草案可提高最低技术结构分，并降低均线结构不完整标的的排序权重。"
            )
        drawdowns = [safe_float(row.get("max_drawdown_pct"), 0.0) or 0.0 for row in sample]
        if min(drawdowns) <= float(strategy.get("risk", {}).get("risk_stop_drawdown_pct", -8.0)):
            keys.append("tighten_risk_filter")
            suggestions.append(
                "出现超过策略风险阈值的回撤：候选草案可降低最高允许风险分，并增加短期涨幅过快过滤。"
            )
        benchmark_rows = [row for row in sample if row.get("outperformed_index") not in ("", None)]
        if benchmark_rows:
            beat_rate = sum(bool(row.get("outperformed_index")) for row in benchmark_rows)
            beat_rate = beat_rate / len(benchmark_rows) * 100
            if beat_rate < float(review.get("target_index_outperformance_pct", 50.0)):
                keys.append("add_relative_strength")
                suggestions.append(
                    "跑赢基准比例不足：候选草案可加入个股相对沪深300与所属板块的强弱因子。"
                )
        weak_signals = [
            row
            for row in metrics.get("signals", [])
            if int(row.get("sample_count", 0)) >= minimum
            and safe_float(row.get("win_rate_pct"), 100.0) < 40
        ]
        if weak_signals:
            names = "、".join(sorted({str(row["signal"]) for row in weak_signals}))
            keys.append("reduce_weak_signal_weight")
            suggestions.append(f"以下信号样本胜率偏低：{names}。建议仅在草案中降权，不直接删除。")
        if not suggestions:
            keys.append("keep_strategy")
            suggestions.append("当前已到期样本未触发明确调整条件，建议保持正式策略并继续积累样本。")
    lines = [
        "# 策略优化建议",
        "",
        f"- 生成日期：{run_date.isoformat()}",
        f"- 当前正式策略：{strategy.get('strategy_version', 'unknown')}",
        "- 状态：仅建议，不自动生效",
        "",
        "## 建议",
        "",
    ]
    lines.extend(f"{index}. {text}" for index, text in enumerate(suggestions, 1))
    lines.extend(
        [
            "",
            "## 变更纪律",
            "",
            "- 单日异常不触发正式策略修改。",
            "- 同类问题连续出现达到配置门槛后，只生成 draft。",
            "- draft 必须人工审阅、回测和确认后，才可手工更新 `config/strategy.yaml`。",
            "",
            f"<!-- suggestion_keys: {json.dumps(keys, ensure_ascii=False)} -->",
        ]
    )
    return "\n".join(lines), keys


def maybe_create_strategy_draft(
    root: Path,
    run_date: date,
    strategy: dict[str, Any],
    current_keys: list[str],
) -> Path | None:
    review = strategy.get("review", {})
    trigger = int(review.get("draft_trigger_days", 3))
    lookback = int(review.get("draft_lookback_days", 7))
    files = sorted((root / "runs").glob("????-??-??/strategy_suggestion.md"))[-lookback:]
    history: list[list[str]] = []
    pattern = re.compile(r"<!-- suggestion_keys: (.+?) -->")
    for path in files:
        match = pattern.search(path.read_text(encoding="utf-8"))
        if match:
            try:
                history.append(json.loads(match.group(1)))
            except json.JSONDecodeError:
                continue
    if not history or history[-1] != current_keys:
        history.append(current_keys)
    repeated = []
    for key in sorted(set(current_keys)):
        streak = 0
        for keys in reversed(history):
            if key not in keys:
                break
            streak += 1
        if streak >= trigger and key not in {"insufficient_samples", "keep_strategy"}:
            repeated.append(key)
    if not repeated:
        return None
    version = str(strategy.get("strategy_version", "v1.0"))
    match = re.match(r"v(\d+)\.(\d+)", version)
    major, minor = (int(match.group(1)), int(match.group(2))) if match else (1, 0)
    path = root / "strategy_versions" / f"v{major}.{minor + 1}-draft-{run_date.isoformat()}.md"
    if path.exists():
        return path
    text = "\n".join(
        [
            f"# v{major}.{minor + 1} 候选策略草案",
            "",
            f"- 基于正式版本：{version}",
            f"- 生成日期：{run_date.isoformat()}",
            "- 状态：Draft / 未生效 / 需人工确认",
            "",
            "## 连续触发的问题",
            "",
            *[f"- `{key}`" for key in repeated],
            "",
            "## 建议变更方向",
            "",
            "- 仅调整与上述问题直接相关的阈值或权重。",
            "- 在独立样本上进行回测，记录新旧版本差异。",
            "- 未完成人工确认前，不修改 `config/strategy.yaml`。",
        ]
    )
    write_text(path, text)
    return path

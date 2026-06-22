# Strategy Iteration Skill

## 1. 定位

本 Skill 根据历史复盘生成“候选策略优化建议”，目标是形成可审计的策略迭代链路，而不是让 Agent 自动控制正式策略。

## 2. 输入

- 当前正式策略：`config/strategy.yaml`
- 历史表现：`metrics/*.csv`
- 每日复盘：`runs/YYYY-MM-DD/review_previous.md`
- 历史建议：`runs/YYYY-MM-DD/strategy_suggestion.md`
- 历史正式或候选版本：`strategy_versions/`

## 3. 可提出的建议

- 提高或降低技术结构最低门槛；
- 调整热点、资金、技术和风险权重；
- 加入相对指数、相对板块强度；
- 对持续低效信号降权；
- 对短期过热、接近前高或大回撤加强过滤；
- 改进数据完整性要求与缺失值处理。

建议必须指出触发指标、样本数量、涉及周期和预期影响，不得只写笼统结论。

## 4. Draft 生成规则

1. 单日问题只写入 `strategy_suggestion.md`。
2. 同一个问题连续出现达到 `draft_trigger_days` 后，才允许生成 draft。
3. draft 文件写入 `strategy_versions/vX.Y-draft-YYYY-MM-DD.md`。
4. draft 只描述候选变更方向，不自动改写 `config/strategy.yaml`。
5. 已存在的同名 draft 不重复创建。

## 5. 正式升级流程

正式策略升级必须由人工完成：

1. 阅读 draft 与对应失败案例；
2. 在独立历史区间回测新旧版本；
3. 检查收益、准确率、胜率、最大回撤和样本量；
4. 明确接受或拒绝每项变更；
5. 手工更新 `config/strategy.yaml` 的参数与 `strategy_version`；
6. 在 `strategy_versions/` 保存正式版本说明；
7. 后续每日结果自动记录新版本。

## 6. 禁止事项

- 不得自动提升 draft 为正式版本。
- 不得因为少量样本大幅调参。
- 不得只优化收益而忽视回撤和数据质量。
- 不得删除失败历史或用新规则改写旧结果。
- 不得使用绝对化投资措辞。

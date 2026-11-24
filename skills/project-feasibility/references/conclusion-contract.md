# 可行性输出契约

结构化结果至少包含：

- `project_context`：项目、地区、年度、批次、申请类型和政策状态；
- `overall_conclusion`：`eligible`、`conditional`、`ineligible` 或 `undetermined`；
- `hard_gates`：逐项列规则、企业现状、判断状态、证据状态和出处；
- `items`：每个缺陷登记 `item`、`requirement`、`actual`、`gap`、`evidence`、`action`、`priority`；
- `scoring`：可选政策资料字段，记录当期评价项目、分值、权重、合格线及政策出处；
- `calculations`：公式、输入、单位、结果和复核状态；
- `uncertainties`：不确定事项、影响和解除条件；
- `evidence_gaps`：缺失材料、验证标准和内部完成节点；
- `actions`：按时间优先级排序的动作。

总体结论与硬门槛状态一致。差距用实际数量、金额、百分点或明确缺失的事实和材料表示。按阻断资格、申报时点和其余补强依赖排序。

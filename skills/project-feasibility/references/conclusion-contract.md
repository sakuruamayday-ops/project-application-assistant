# 可行性输出契约

结构化结果至少包含：

- `project_context`：项目、地区、年度、批次、申请类型和政策状态；
- `overall_conclusion`：`eligible`、`conditional`、`ineligible` 或 `undetermined`；
- `hard_gates`：规则、状态、证据状态和理由；
- `scoring`：确定分、可能分、评分依据和未公布标识；
- `calculations`：公式、输入、单位、结果和复核状态；
- `uncertainties`：不确定事项、影响和解除条件；
- `evidence_gaps`：缺失材料、验证标准和截止时间；
- `actions`：按时间优先级排序的动作。

总体结论必须能由硬门槛状态机械推导，文字摘要不得与结构化状态冲突。

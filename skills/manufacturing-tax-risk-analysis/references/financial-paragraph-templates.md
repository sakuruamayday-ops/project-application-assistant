# 财务数值回填段落模板

从本轮确定性指标 `display_values` 选择实际年度、类别和字段；下文示例仅演示语法，正文引用本轮数据。

## 先由程序准备输入

取得指标文件后，先用技能目录的 `scripts/generate_report_html.py report-data.json --metrics-json metrics.json --prepare-input` 创建本轮新输入。该命令生成带真实年度、科目标签和字段引用的总览与各专题表格，不需要模型从空对象编写全部报告。

在已生成输入中补综合结论、专题解释、替代解释、真实来源、整改和政策，保留具名财务引用；局部修订直接更新分析段落。缺资料专题标缺口，其余继续形成可用稿。

## 单位由程序输出

`{{financial.2025.facts.other_receivables}}` 已带万元，比例已带百分号，天数已带天。缺金额显示“待补充”，缺计算条件的比例显示“无法计算”。

## 可直接仿写的段落

- 编制基础：据企业财务资料分析盈利、现金流、偿债及涉税事项；附注、交易和政策缺项按实际范围说明，内部技术字段留在过程记录。
- 规模变化：收入由 `{{financial.2023.facts.revenue}}` 至 `{{financial.2025.facts.revenue}}`，原因结合产品、销售和交付资料说明。
- 盈利能力：2025年营业成本为 `{{financial.2025.facts.cost}}`，毛利率为 `{{financial.2025.metrics.gross_margin}}`，净利率为 `{{financial.2025.metrics.net_margin}}`。
- 往来款项：其他应收款由 `{{financial.2023.facts.other_receivables}}` 变为 `{{financial.2025.facts.other_receivables}}`，2025年占总资产 `{{financial.2025.metrics.other_ar_to_assets}}`。对象、性质与归还安排按已提供资料描述。
- 现金流：2025年经营活动现金流量净额为 `{{financial.2025.facts.operating_cash_flow}}`，购建长期资产现金支出为 `{{financial.2025.facts.capex_cash}}`，自由现金流为 `{{financial.2025.metrics.free_cash_flow}}`。
- 周转：2025年应收账款周转天数为 `{{financial.2025.metrics.ar_days}}`，存货周转天数为 `{{financial.2025.metrics.inventory_days}}`。
- 税费：现金税费支付率 `{{financial.2025.metrics.cash_tax_payment_rate}}` 按现金流口径解释，增值税负担及合规据对应税种资料核对。

同一字段在总览、专题、风险图和总结复用具名引用；新增指标补齐真实输入、公式和计算依据，政策数值与建议期限分别引用相应来源。

实际 `report-data.json` 保留 `{{financial...}}` 引用，由生成器填本轮数值。正文名称匹配字段定义，例如 `ocf_to_profit` 对应净利润。资料范围集中说明缺少的财务、交易和政策依据，工具执行过程留在内部记录。

专业预校验复用 `manufacturing-tax-risk-analysis.calculate-metrics` 的 `calculated` 证据，`values` 留空；已有计算结果直接引用，新增计算另列真实公式、输入、单位和来源。

历史自由文本和用户手改数字另按原始底稿复核，说明自动回填与人工复核的实际覆盖范围。

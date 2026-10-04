# 财务数值回填段落模板

从本轮确定性指标文件的 `display_values` 选择实际年度、类别和字段。下文年度仅演示语法，必须换成输入中存在的年度；不得把示例当成企业数据。

## 先由程序准备输入

取得指标文件后，先用技能目录的 `scripts/generate_report_html.py report-data.json --metrics-json metrics.json --prepare-input` 创建本轮新输入。该命令生成带真实年度、科目标签和字段引用的总览与各专题表格，不需要模型从空对象编写全部报告。

读取生成的输入后，只补综合结论、各专题解释、替代解释、实际资料来源、整改动作与已核验政策。保留财务事实和表格中的具名引用，不把引用改成手抄数字。没有资料支持的专题保留缺口，不能复制示例企业的高负债、关联方集中或担保结论。已存在的输入不重新初始化，局部修改直接改对应分析段落。

## 单位由程序输出

`{{financial.2025.facts.other_receivables}}` 已包含万元单位，正文不要再追加单位。`metrics` 中的比例已包含百分号，周转天数已包含天。缺失金额回填“待补充”，不可计算比例回填“无法计算”，不替代为零。

## 可直接仿写的段落

- 编制基础：本报告依据企业提供的财务汇总资料，对盈利、现金流、偿债及相关涉税事项进行分析。尚未取得的报表附注、交易明细与政策原文按实际缺项说明。此处写业务资料名称，不写 `enterprise-financial-facts/v1`、共享事实契约、技能、校验回执等内部技术名称。
- 规模变化：营业收入由 `{{financial.2023.facts.revenue}}` 变为 `{{financial.2025.facts.revenue}}`。变化原因结合已取得的产品、销售及交付资料判断，不从金额变化推断原因。
- 盈利能力：2025年营业成本为 `{{financial.2025.facts.cost}}`，毛利率为 `{{financial.2025.metrics.gross_margin}}`，净利率为 `{{financial.2025.metrics.net_margin}}`。
- 往来款项：其他应收款由 `{{financial.2023.facts.other_receivables}}` 变为 `{{financial.2025.facts.other_receivables}}`，2025年占总资产 `{{financial.2025.metrics.other_ar_to_assets}}`。对象、性质与归还安排按已提供资料描述。
- 现金流：2025年经营活动现金流量净额为 `{{financial.2025.facts.operating_cash_flow}}`，购建长期资产现金支出为 `{{financial.2025.facts.capex_cash}}`，自由现金流为 `{{financial.2025.metrics.free_cash_flow}}`。
- 周转：2025年应收账款周转天数为 `{{financial.2025.metrics.ar_days}}`，存货周转天数为 `{{financial.2025.metrics.inventory_days}}`。
- 税费：2025年现金税费支付率为 `{{financial.2025.metrics.cash_tax_payment_rate}}`。该现金流口径不等同于增值税税负率，不据此判定纳税违法。

财务总览、专题事实、风险地图及总结重复引用同一字段，不能复制成另一份手写数值。指标不在计算器输出中时，先列缺项，不创造引用。政策数值与建议实施期限不是企业财务事实，仍按各自来源处理。

数值示例只出现在本页说明中；实际 `report-data.json` 的财务数值保留 `{{financial...}}` 原样，生成器负责替换。正文的指标名称必须与所选字段定义一致，例如 `ocf_to_profit` 的分母是净利润，不能写为利润总额。资料范围与分析限制说明缺少哪些财务、交易或政策资料，不写水印、生成器、检查次数、输出文件数量或工具执行过程。

专业预校验直接引用 `manufacturing-tax-risk-analysis.calculate-metrics` 的一条 `calculated` 证据，其 `values` 留空；该回执已包含上述确定性结果，不再为同一数值创建人工 `calculations`。只有确实增加且不在计算器中的计算才另行准确列公式；不要用无意义的乘一、改分母或改操作符凑数。

当前回填机制不校正历史自由文本中的手写数字；旧报告及用户手工修订仍需按原始底稿复核，不能宣称已自动覆盖全部数字错误。

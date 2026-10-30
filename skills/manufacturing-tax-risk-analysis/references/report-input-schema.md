# 自动报告数据结构

## 使用方法

先用本轮财务数据运行确定性计算器，再以 `--prepare-input` 创建新的 `report-data.json`，沿真实年度预置表格和引用，补分析、来源和动作后生成。已有输入直接局部修订；字段问题定向查本文及相应示例。

```bash
python3 scripts/calculate_metrics.py metrics-input.json enterprise-financial-facts.v1.json \
  --metrics-output manufacturing-tax-risk-metrics.v1.json
python3 scripts/generate_report_html.py report-data.json --prepare-input \
  --metrics-json manufacturing-tax-risk-metrics.v1.json
# 补充本轮分析文字与实际来源，保留财务字段引用后，再执行下方生成命令。
python3 scripts/generate_report_html.py report-data.json --validate-only \
  --metrics-json manufacturing-tax-risk-metrics.v1.json
python3 scripts/generate_report_html.py report-data.json report.html \
  --metrics-json manufacturing-tax-risk-metrics.v1.json
```

生成器将 `gold-advisor.css` 内嵌到 HTML，输出文件可独立移动。所有文本均自动 HTML 转义。

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| company | string | 企业全称 |
| period | object | start、end |
| report_date | string | 报告日期 |
| preparer | string | 默认共创知识产权 |
| source_status | string | 正式、初稿、未签章等 |
| internal_only | boolean | 初稿或缺签章时设为 true |
| use_restriction | string | 对外使用限制 |
| risk_level | string | 高关注、中关注、一般关注 |
| one_line_conclusion | string | 执行摘要总判断 |
| sources | array | name、period、status、pages、limitation |
| executive_findings | array | title、conclusion、level、source，集中呈现本企业主要发现 |
| financial_overview | object | years、kpis、rows、conclusion；KPI 含 label、value、可选 note，表行含 name、values、source_pages、formula |
| sections | object | 固定9个专题 |
| risks | array | 风险地图 |
| roadmap | array | 按实际行动阶段组织；period、actions、owner、completion，其中 completion 写可观察验收结果 |
| p0_documents | array | 高优先补充资料 |
| calculations | array | 可为空；仅填写确定性指标文件尚未覆盖的补充计算，每项含 indicator、formula、result、source |
| policies | array | 本轮已核验的现行官方政策；每项含非空 name、issuer、date、官方直达 url。官方原文未取得时可留空数组，状态沿用当前模型判断并列出来源缺口 |
| final_judgment | object/string | 最终判断 |
| monthly_indicators | array | name、rule、owner、frequency |
| limitations | array | 资料缺口、政策范围及鉴证责任；执行过程留内部记录 |

正文列表使用字符串数组：`missing_documents`、专题及路线 `actions`、`p0_documents`、`limitations`。责任岗位另填 `owner`，其他对象按字段表归位。

## 九个固定专题

`sections` 可按当前资料填写以下专题：

1. `profitability`
2. `cash_flow`
3. `solvency`
4. `asset_quality`
5. `bills_deposits`
6. `related_parties`
7. `guarantees`
8. `income_tax_rd`
9. `accrual_revenue`

每个专题可填写 `conclusion`、`facts` 和 `actions`。可选 `title` 与 `table`。`facts` 每项使用 `title`、`text`、`source`；表格使用 `headers` 和 `rows`。

`actions` 填字符串数组，例如 `["补齐期后回款凭证", "逐笔复核关联往来"]`；责任岗位填 `roadmap[*].owner`。

`roadmap[*].completion` 写可观察的验收结果，例如“差异逐项闭合并经负责人复核”；建议动作、执行状态及已完成证据分别记录。

按原布局集中表达判断、KPI、事实、动作与风险，来源和必要明细自然续页。可参考 `risk-gates.md` 核对相关风险，正文按本企业实际问题展开。

内容长度按实际版式调整：优先压缩重复背景，保持关键事实、来源、风险含义和动作；字体和表格沿母版。

## 财务总览

`financial_overview.years` 填实际年度，`rows.values` 与之对应，提供 `source_pages`、`formula`；数值格式注明金额单位和百分比。

KPI、结论和专题优先引用原始年度数据或确定性指标展示值；确有新增派生指标时，使用同源输入、清楚公式、单位和可复算结果，按生成器支持的字段或独立计算说明呈现。

## 确定性指标文件

年度键用四位年份；同比与上一自然年比较，缺期显示缺失年度及计算状态，其余年度继续输出。

可选 `--metrics-json` 指向 `calculate_metrics.py --metrics-output` 生成的 `manufacturing-tax-risk-metrics/v1` 文件。生成器会核对企业名称并把 `report_rows` 写入“计算过程与来源”表。跨年增速、研发费用率、资产负债表恒等式差额及无法计算原因因此不依赖模型自行抄写。

共创客户端复用 `manufacturing-tax-risk-analysis.calculate-metrics` 已验签回执绑定展示值，元与万元按计算器对应值填写。政策表据本轮已核验官方原文填名称、机关、日期和直达链接；暂缺政策依据时 `policies` 填空数组并继续生成，封面与来源页保留草稿状态。

`calculations` 默认写 `[]`。确定性指标文件的 `report_rows` 会自动进入“计算过程与来源”页；只有确有新增、已绑定的计算且未被确定性文件覆盖时才添加补充行。所有指标与补充计算完整保留，来源表每10行增加续页，不截断内容。报告保留17个基础页面，实际页数以生成器返回的 `pages` 为准，PDF验收使用该页数。

比例、增长率和阈值优先引用确定性指标；新增复合指标按同源输入与公式复算。月度阈值绑定本轮证据或计算参数，参数待核时先给趋势监测和核验动作。

## 已提供政策文件的保留

`policies` 存本轮已核验官方现行文件；用户已提供文件登记 `sources` 的名称、适用期、状态、位置与采用范围。官方现行性待核时保留草稿及缺口，继续使用已取得内容并交付。

## 风险表达

风险项填 `chain`、`fact`、`alternative`、`missing_evidence`、`action`、`level`；交易证据待取得时用“需核验”，法律结论据完整证据判断。

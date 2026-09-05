# 自动报告数据结构

## 使用方法

复制同目录的 `metrics-input.example.json` 和 `report-data.example.json`，用当前企业事实替换示例内容。先用确定性计算器生成共享事实与报告指标，再校验并生成报告：

```bash
python3 scripts/calculate_metrics.py metrics-input.json enterprise-financial-facts.v1.json \
  --metrics-output manufacturing-tax-risk-metrics.v1.json
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
| executive_findings | array | title、conclusion、level、source，最多取5项 |
| financial_overview | object | years、kpis、rows、conclusion；KPI 必填 label、value，可选 note；每行含 name、values、source_pages、formula |
| sections | object | 固定9个专题 |
| risks | array | 风险地图 |
| roadmap | array | 30、60、90天阶段；每项含 period、actions、owner、completion |
| p0_documents | array | 高优先补充资料 |
| calculations | array | 可为空；仅填写确定性指标文件尚未覆盖的补充计算，每项含 indicator、formula、result、source |
| policies | array | 至少一项本轮核验的现行官方政策，每项含非空 name、issuer、date、url |
| final_judgment | object/string | 最终判断 |
| monthly_indicators | array | name、rule、owner、frequency |
| limitations | array | 资料限制和免责声明 |

所有面向正文的列表项都必须使用纯字符串。`missing_documents`、各专题的 `actions`、`roadmap[*].actions`、`p0_documents` 和 `limitations` 不接受 `{ "text": "..." }`、`{ "owner": "..." }` 等对象形式。生成器会在渲染前拒绝类型不符的数据，避免把 Python/JSON 对象字面量写进正式报告。

## 九个固定专题

`sections` 必须包含：

1. `profitability`
2. `cash_flow`
3. `solvency`
4. `asset_quality`
5. `bills_deposits`
6. `related_parties`
7. `guarantees`
8. `income_tax_rd`
9. `accrual_revenue`

每个专题必须包含 `conclusion`、`facts` 和 `actions`。可选 `title` 与 `table`。`facts` 每项使用 `title`、`text`、`source`；表格使用 `headers` 和 `rows`。

`actions` 是字符串数组，例如 `["补齐期后回款凭证", "逐笔复核关联往来"]`。整改责任岗位写入 `roadmap[*].owner`，不要把动作改成对象数组。

为保证固定17页不溢出：执行判断不超过5项；总览指标行不超过8行；每个专题事实不超过4项、动作不超过6项、专题表格不超过8行；风险地图不超过8项；计算不超过10项；政策不超过5项；月度指标不超过5项。十四项风险闸门都要检查，但报告只汇总最重要的8项风险链。

生成器同时执行文字长度门禁：公司名称不超过40字；总判断和专题结论分别不超过180字；单项事实不超过140字；单项动作不超过80字；风险矩阵单元不超过120字；最终判断正文不超过260字。超过限制时先压缩表达，不要缩小字号。

## 财务总览

`financial_overview.years` 至少两个年度。每个 `rows` 项的 `values` 数量必须与年度数量一致，并提供 `source_pages` 与 `formula`。展示值应提前格式化为“13,515.26万元”“99.21%”等，生成器不猜测金额单位。

## 确定性指标文件

`--metrics-json` 必须指向 `calculate_metrics.py --metrics-output` 生成的 `manufacturing-tax-risk-metrics/v1` 文件。生成器会核对企业名称并把 `report_rows` 写入“计算过程与来源”表。跨年增速、研发费用率、资产负债表恒等式差额及无法计算原因因此不依赖模型自行抄写。

共创客户端通过 `manufacturing-tax-risk-analysis.calculate-metrics` 的已验签回执覆盖报告里的确定性展示形式。同一差额同时显示为万元和元时，由计算器生成两种可绑定数值；不得让模型重新读取成品、枚举全部数字或手工复制复算数组。政策表只有在本轮官方原文已核验并进入证据时才填写，且至少包含一项现行政策的名称、发布机关、日期和官方直达链接。不从示例或记忆补齐；无法核验时停止正式报告链，交付明确标注缺少政策来源的草稿，不要用空链接或“现行状态待核验”占位冒充正式政策证据。

`calculations` 默认写 `[]`。确定性指标文件的 `report_rows` 会自动进入“计算过程与来源”页；只有确有新增、已绑定的计算且未被确定性文件覆盖时才添加补充行，避免重复展示造成固定页面溢出。

报告中的比例、增长率和阈值优先使用确定性指标文件已经输出的结果。不要自行增加当前计算器或专业校验器无法复算的复合指标，例如未提供连续年度复合增长率计算链时直接写 CAGR；确需增加时，应先扩展确定性计算器及其测试。月度规则中的硬阈值只有在本轮证据或复算参数能够绑定时才填写具体数字，否则改写为不含虚构阈值的趋势监测或核验动作。

## 风险表达

每项风险固定填写 `chain`、`fact`、`alternative`、`missing_evidence`、`action`、`level`。缺交易级证据时用“需核验”，不得直接写违法结论。

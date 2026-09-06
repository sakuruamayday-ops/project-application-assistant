# 自动报告数据结构

## 使用方法

直接按本文字段表构建指标输入与 `report-data.json`，不要在首次运行前读取或复制同目录的示例文件。先用确定性计算器生成共享事实与报告指标，再校验并生成报告；只有生成器真实返回字段结构错误且错误信息不足时，才定向查看相关示例片段：

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
| financial_overview | object | years、kpis、rows、conclusion；kpis 最多4项，KPI 必填 label、value，可选 note；每行含 name、values、source_pages、formula |
| sections | object | 固定9个专题 |
| risks | array | 风险地图 |
| roadmap | array | 30、60、90天阶段；每项含 period、actions、owner、completion；completion 必须写可核验的完成条件，不是当前执行状态 |
| p0_documents | array | 高优先补充资料 |
| calculations | array | 可为空；仅填写确定性指标文件尚未覆盖的补充计算，每项含 indicator、formula、result、source |
| policies | array | 本轮已核验的现行官方政策；每项含非空 name、issuer、date、官方直达 url。无法取得官方原文时必须为空数组，生成器自动输出明确标注的草稿 |
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

`roadmap[*].completion` 必须描述验收结果，例如“P0资料齐备并形成签收清单”或“差异清单逐项闭合并由负责人复核”。不得只写“完成”“已完成”“通过”“达标”“待完成”等状态词；报告生成时整改尚未执行，不能把建议动作误标成已完成。

为保证固定17页不溢出：执行判断不超过5项；KPI 卡片不超过4项；总览指标行不超过8行；每个专题事实不超过4项、动作不超过6项、专题表格不超过8行；风险地图不超过8项；计算不超过10项；政策不超过5项；月度指标不超过5项。十四项风险闸门都要检查，但报告只汇总最重要的8项风险链。

生成器同时执行文字长度门禁：公司名称不超过40字；总判断和专题结论分别不超过180字；单项事实不超过140字；单项动作不超过80字；风险矩阵单元不超过120字；最终判断正文不超过260字。超过限制时先压缩表达，不要缩小字号。

## 财务总览

`financial_overview.years` 至少两个年度。每个 `rows` 项的 `values` 数量必须与年度数量一致，并提供 `source_pages` 与 `formula`。展示值应提前格式化为“13,515.26万元”“99.21%”等，生成器不猜测金额单位。

KPI、结论和专题正文中的数字只允许直接取自原始年度数据，或取自确定性指标文件已经输出的展示值。不得自行计算三年复合增长率、累计净利润、均值、合计值或其他计算器尚未覆盖的派生数值；例如不得把三年收入改写为 CAGR，也不得把各年净利润相加后写成累计净利润。确有业务需要时，先扩展确定性计算器及测试，再用于报告。

## 确定性指标文件

`--metrics-json` 必须指向 `calculate_metrics.py --metrics-output` 生成的 `manufacturing-tax-risk-metrics/v1` 文件。生成器会核对企业名称并把 `report_rows` 写入“计算过程与来源”表。跨年增速、研发费用率、资产负债表恒等式差额及无法计算原因因此不依赖模型自行抄写。

共创客户端通过 `manufacturing-tax-risk-analysis.calculate-metrics` 的已验签回执覆盖报告里的确定性展示形式。同一差额同时显示为万元和元时，由计算器生成两种可绑定数值；不得让模型重新读取成品、枚举全部数字或手工复制复算数组。政策表只有在本轮官方原文已核验并进入证据时才填写，且至少包含一项现行政策的名称、发布机关、日期和官方直达链接。不从示例或记忆补齐；无法核验时把 `policies` 写为空数组并继续生成，生成器会在封面和来源页明确标注草稿。不要用空链接或“现行状态待核验”占位冒充正式政策证据，也不要为此重复联网或停止交付。

`calculations` 默认写 `[]`。确定性指标文件的 `report_rows` 会自动进入“计算过程与来源”页；只有确有新增、已绑定的计算且未被确定性文件覆盖时才添加补充行，避免重复展示造成固定页面溢出。

报告中的比例、增长率和阈值优先使用确定性指标文件已经输出的结果。不要自行增加当前计算器或专业校验器无法复算的复合指标，例如未提供连续年度复合增长率计算链时直接写 CAGR；确需增加时，应先扩展确定性计算器及其测试。月度规则中的硬阈值只有在本轮证据或复算参数能够绑定时才填写具体数字，否则改写为不含虚构阈值的趋势监测或核验动作。

## 风险表达

每项风险固定填写 `chain`、`fact`、`alternative`、`missing_evidence`、`action`、`level`。缺交易级证据时用“需核验”，不得直接写违法结论。

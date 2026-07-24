# 自动报告数据结构

## 使用方法

复制同目录的 `report-data.example.json`，用当前企业事实替换示例内容。先校验，再生成：

```bash
python3 scripts/generate_report_html.py report-data.json --validate-only
python3 scripts/generate_report_html.py report-data.json report.html
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
| financial_overview | object | years、kpis、rows、conclusion |
| sections | object | 固定9个专题 |
| risks | array | 风险地图 |
| roadmap | array | 30、60、90天阶段 |
| p0_documents | array | 高优先补充资料 |
| calculations | array | indicator、formula、result、source |
| policies | array | name、issuer、date、url |
| final_judgment | object/string | 最终判断 |
| monthly_indicators | array | name、rule、owner、frequency |
| limitations | array | 资料限制和免责声明 |

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

为保证固定17页不溢出：执行判断不超过5项；总览指标行不超过8行；每个专题事实不超过4项、动作不超过6项、专题表格不超过8行；风险地图不超过8项；计算不超过10项；政策不超过5项；月度指标不超过5项。十四项风险闸门都要检查，但报告只汇总最重要的8项风险链。

生成器同时执行文字长度门禁：公司名称不超过40字；总判断和专题结论分别不超过180字；单项事实不超过140字；单项动作不超过80字；风险矩阵单元不超过120字；最终判断正文不超过260字。超过限制时先压缩表达，不要缩小字号。

## 财务总览

`financial_overview.years` 至少两个年度。每个 `rows` 项的 `values` 数量必须与年度数量一致。展示值应提前格式化为“13,515.26万元”“99.21%”等，生成器不猜测金额单位。

## 风险表达

每项风险固定填写 `chain`、`fact`、`alternative`、`missing_evidence`、`action`、`level`。缺交易级证据时用“需核验”，不得直接写违法结论。

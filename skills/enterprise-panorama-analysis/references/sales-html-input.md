# 标准销售版结构化输入

客户端调用真实固定操作 `enterprise-panorama-analysis.build-sales-html`。参数 `input` 为企业工作区内 UTF-8 JSON，`output` 为尚不存在的 `.html` 路径。生成成功只表示中间源已创建，不能据此声称专业、来源或视觉检查通过；随后用返回的同一 HTML 做预校验并调用 `gongchuang_deliver_pdf`。

```json
{
  "company": {"name": "合成示例企业有限公司"},
  "report_date": "本次报告日期",
  "data_as_of": "本次资料截止日",
  "sections": {
    "01": {"notes": [{"text": "请企业提供登记资料后判断", "status": "medium"}]},
    "07": {"tables": []},
    "08": {"comparison": {"advantages": ["待本企业事实确认"], "limitations": ["待同业证据核对"]}},
    "12": {"assessment": {"level": "待核", "description": "请补充判断依据", "summary": "不根据资料缺失自动评级"}}
  },
  "sources": []
}
```

此例仅说明字段，不提供任何企业事实。未知内容留待补，不用零值或模板企业数据填满。

## 工商字段

`company.name` 必须是本企业名称。其他字段按原两列表顺序保留：`former_name` 曾用名、`credit_code` 统一社会信用代码、`founded_date` 成立日期、`registered_capital` 注册资本、`paid_in_capital` 实缴资本、`legal_representative` 法定代表人、`company_type` 企业类型、`registration_status` 登记状态、`address` 注册地址、`business_scope` 经营范围、`tax_qualification` 纳税人资质、`industry` 所属行业、`registration_authority` 登记机关、`website` 官网。登记字段可引用本次已核验的公开原文；不能从视觉样张抄取。

## 章节内容

`sections` 使用 `01` 至 `13` 的固定编号；顺序、章节标题、图标、DOM、列和 CSS 由程序决定。每章可填 `paragraphs` 文字数组、`points` 业务要点数组、`notes` 核验说明数组、`summary` 摘要对象、`callouts` 提示数组及 `tables` 数据数组。

`summary` 只填 `title` 与 `text`。`callouts` 每项只填 `kind`、`title`、`text`，固定 `kind` 为 `warning`、`success`、`info`、`danger`，分别沿用原黄色关注、绿色亮点、蓝色分析与红色重大风险布局及原图标。风险须有本企业依据；缺资料不能自动成为重大风险。

第八章 `comparison` 固定为 `advantages`、`limitations` 两个要点数组，形成原绿色与红色并排卡。第十二章 `assessment` 只填本企业 `level`、`description`、`summary`，形成原渐变评级卡；未提供级别显示“待核”，程序不评分。

## 固定表格

表格每项填 `type` 与二维 `rows`，行列数须与固定表头相同；可在该表后填 `summary`、`callouts`。不能传入 HTML、CSS、列名或重排其他章节的表型。

| 章节 | 表型及固定列 |
|---|---|
| 02 | shareholders 7列、management 4列、investments 6列 |
| 03 | business 2列、milestones 3列 |
| 04 | qualifications 4列、licenses 4列、certifications 3列、intellectual-property 3列 |
| 05 | assets 2列、related-risk 5列 |
| 06 | court-cases 5列、claims 4列、verification 3列、risk-dimensions 3列、risk-actions 5列 |
| 07 | operating-metrics 3列、tax-record 2列、paid-capital 5列 |
| 08 | policy-trends 2列、peer-comparison 5列 |
| 09 | historical-projects 4列、client-types 3列 |
| 10 | project-criteria 3列、project-options 3列、project-plan 3列 |
| 11 | development 3列、roadmap 4列 |
| 12 | summary-risks 4列、positive-factors 3列 |
| 13 | recommendations 3列 |

实际表头由生成器固定声明。既有风险整改表、同行项目对比表、可申报项目表、五年规划表始终保留；缺数据只填待补，不伪造风险、同行、项目或年度数字。

`operating-metrics` 仅填写用户提供的可靠经营财务资料，有行数据时需注明 `source_kind="customer-file"`。这不是数据已验真的声明；实际证据绑定与计算仍由客户端专业校验完成。没有资料留待补，不估算营收、利润、研发费、产能、未分配利润。工商实缴及股东出资可按本次真实公开来源填写，不与内部经营财务混同。

## 状态与来源

普通单元格为文字或用户提供数值。验证状态使用 `{"text":"已核验说明","status":"low"}`、`medium` 待核、`high` 风险说明，程序绘制真圆点；颜色不会替代说明或自动改变事实等级。风险严重程度使用 `{"text":"风险等级说明","severity":"high"}`，还支持 `medium`、`low` 与 `pending` 待核，沿用原彩色底状态片。不能用“（绿）”“（黄）”“（红）”及等价括号标注代替状态对象。

`sources` 每项只填本企业实际 `name`、`url`、`queried_at`，保留本次真实来源和查询日。图标、样张与样式只作视觉参考，不登记为本企业业务证据。模板内没有可借用的客户事实；生成操作不会替代来源台账、事实与数字校验。

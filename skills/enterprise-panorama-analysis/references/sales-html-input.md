# 标准销售版结构化输入

客户端调用固定操作 `enterprise-panorama-analysis.build-sales-html`，`input` 为工作区 UTF-8 JSON，`output` 为新 `.html` 路径。生成后沿用同一 HTML 完成来源、内容和版式复核，再调用 `gongchuang_deliver_pdf`；各项状态按实际结果记录。

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

示例说明字段。正文填本轮事实，未知内容集中列待补。

## 工商字段

`company.name` 填本企业名称。原两列表字段和顺序沿用：`former_name`、`credit_code`、`founded_date`、`registered_capital`、`paid_in_capital`、`legal_representative`、`company_type`、`registration_status`、`address`、`business_scope`、`tax_qualification`、`industry`、`registration_authority`、`website`。登记字段填本轮已核验公开原文；视觉样张仅供版式参考。

## 章节内容

`sections` 使用 `01` 至 `13` 的固定编号；顺序、章节标题、图标、DOM、列和 CSS 由程序决定。每章可填 `paragraphs` 文字数组、`points` 业务要点数组、`notes` 核验说明数组、`summary` 摘要对象、`callouts` 提示数组及 `tables` 数据数组。

`summary` 填 `title`、`text`；`callouts` 填 `kind`、`title`、`text`。`kind` 使用 `warning`、`success`、`info`、`danger`，沿用原图标和配色。风险回指本企业依据，资料缺口以待核说明呈现。

第八章 `comparison` 固定为 `advantages`、`limitations` 两个要点数组，形成原绿色与红色并排卡。第十二章 `assessment` 只填本企业 `level`、`description`、`summary`，形成原渐变评级卡；未提供级别显示“待核”，程序不评分。

## 固定表格

表格项填 `type` 和二维 `rows`，行列数匹配固定表头；表后可填 `summary`、`callouts`。沿用模板的 HTML、CSS、列名和章节表型。

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

表头沿生成器，风险、同行、项目及五年表按实际内容填写，缺项集中说明并保留原表结构。

`operating-metrics` 的营收、利润、研发费、产能和未分配利润采用用户提供的可靠资料，注明 `source_kind="customer-file"` 并核对实际依据；缺项标为待提供，继续生成其余正文。工商登记、实缴、人员/参保、行业和主营业务可据本轮公开来源填写，标记 `government-source`、`third-party-platform` 或 `public-source`，与内部经营财务分别呈现。

## 状态与来源

普通单元格填文字或用户提供数值。验证状态用 `{"text":"已核验说明","status":"low"}`，或 `medium` 待核、`high` 风险，由程序绘制圆点；风险严重程度用 `severity` 对象，支持 `high`、`medium`、`low`、`pending`，沿用原状态片。说明文字保留实际证据和状态。

`sources` 每项只填本企业实际 `name`、`url`、`queried_at`，保留本次真实来源和查询日。图标、样张与样式只作视觉参考，不登记为本企业业务证据。模板内没有可借用的客户事实；生成操作不会替代来源台账、事实与数字校验。

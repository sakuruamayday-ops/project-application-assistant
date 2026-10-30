---
name: project-feasibility
description: 分析单个政府项目的条件、企业证据和实施路径，支持企业名称加项目名启动前期评估、可行性或双报告；单条件咨询、既有报告解释和改写按请求范围完成。
---

# 可行性分析

企业名称与目标项目可启动分析，主体、地区、年度、批次和申报类型从现有材料及可用来源补齐，未知项标状态。单点问题直接回答，完整报告按用户目标组织。

## 判断方法

1. 政策核验使用 `policy-retrieval`，规则台账参考 `references/feasibility-decision-model.md`，记录规则类型、原文、来源、范围、时间与排除情形。征求意见、历史和异地规则作为对应参考。
2. 按 `references/evidence-state-model.md` 记录 `verified`、`computed`、`claimed`、`missing`、`conflicting`、`not-applicable`。业务现状与证明完整度分列，专精特新和小巨人沿用本轮已确认版本及材料事实。
3. 分别检查资格、排除情形、评分和实施动作，已核规则与事实支持确定判断，缺项用情景和待核说明。评分按正式细则逐项映射，确定分、条件分分列。
4. 财务采用当前企业 `enterprise-financial-facts/v1`，由 `financial-verification` 核对主体、期间、单位、币种、合并及证据，公式见 `references/calculation-review-rules.md`。
5. 结论参考 `references/conclusion-contract.md`：可申报、有条件申报、不可申报、暂无法判断；分别对应已具备条件、尚待补证或确认、明确条件差距、核心信息待核。风险按当期政策及实际影响解释，动作说明成立条件和时间。

## 报告结构

前期评估、培育规划参考 `references/policy-application-path-contract.md`，报告类型参考 `references/two-report-contract.md`、`references/report-template-registry.json`。前期突出核心条件、企业值、关键差距、建设路径和动作；可行性展开适用条件、正式评分、证据、复算、补强、完成标准与节点。“双报告”“前期报告和中期分析”等按 `preassessment`、`feasibility` 两份组织。

高企、专精、小巨人分析采用固定 HTML 模板；其他项目沿既有母版，申请书采用独立原生 Word 回填。模板保留章节、表格、对象、补强入口及品牌，条件数值取现行政策。

专精或小巨人的企业现状与培育报告采用 `sme-development-projects/references/material-checkup-report-template.md` 五章 19 内容块，`report_layout: "sme-action"` 和 `report_sections`，画像 `sme-action-report`。省级专精按当期申请条件，小巨人核对省级资格；产品按业务技术资料给具体建议。详细申请书体检按委托范围逐字段展开。研发设备筛选由 `research_equipment_screen` 输入和生成器计算，金额元、未知固定资产 `null`。

## 生成接口

共创客户端操作 `project-feasibility.generate-report` 参数为 `input` 工作区事实 JSON、`output` 新 HTML 路径、`reportType`。成功后取返回 `delivery_profile`，同一 HTML 调用 `gongchuang_deliver_pdf`。其他宿主参考 `references/report-cli-generation.md`。按当前可用资料生成草稿，后续复用已完成文件与有效检查结果。

```json
{"operation":"project-feasibility.generate-report","parameters":{"input":"工作区事实.json","output":"前期评估.html","reportType":"preassessment"}}
```

输入字段：

- `project_id` 为索引项目 ID，`enterprise` 为企业；`project_object`、`suggested_year`、`deadline`、`conclusion`、`conclusion_basis`、`primary_gap`、`next_action` 对应本轮已知事实与判断。
- `materials` 数组使用真实文件绝对 `path` 和逐字原文 `anchors`；知识库标 `source_type=knowledge-base`，客户原件标 `source_type=customer-file`、`source=用户提供`。
- `policies` 数组列实际 `title`、`locator`。资料待取时使用空数组，生成器返回 `report_stage=draft` 及 `warnings`；`status=pass` 记录文件生成成功，专业结论和定稿状态另列。
- `conditions` 可逐项填 `match`、`value`、`state`、`gap`、`action`。待确认事项如实填写，原件已说明的事实沿用输入状态。
- `table_content` 按母版原表头及实际行回填评分、口径、同行、补强、节点、资源和风险。格式 `{"columns":["表头"],"rows":[["内容"]]}`，支持单表或数组；表头映射待核的表保留为补充分析。
- 高企 `core_associations` 六列为 RD、核心技术、IP 及状态、转化、PS 及收入、依据缺口，覆盖输入 RD；同 PS 收入统一核算。

主任务、事实和来源复用，双报告分别保存输出及状态，已完成部分保留并继续其他报告或失败步骤。案例借鉴结构、指标组织和证据类型，企业事实与政策条件使用本案来源。

## 按需检查与交付

内容与文件生成后直接提供入口，深度检查按用户任务需要执行。`python3 scripts/validate_feasibility_assessment.py <结果.json>` 检查结构化分析，按实际结果修复问题。报告画像验证示例：

```bash
python3 scripts/validate_report_profile_delivery.py --plugin-root <实际技能包根目录> --state-root <本轮状态目录> --profile-id <project-presale-assessment-report|project-feasibility-analysis-report> --artifact <实际成品路径>
```

客户端采用统一交付结果；其他宿主核对实际最终文件。检查章节、表格、中文字体、品牌、可打开性和真实版式，缺检查条件时说明待完成范围。内置模板使用 OFL Noto Sans SC，字体及许可在 `assets/fonts/`。申请书 DOCX 与分析 PDF 分别验收。

对外来源附录采用“序号、文件名称、链接”；官方原文可点击，知识库链接列“来源共创知识库”。哈希、锚点、回执、内部路径等存入执行记录，正文呈现读者需要的事实、判断、来源和行动。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

企业数据取证参考[来源接续方法](../_runtime/enterprise-source-fallback.md)，复用成功结果，缺口随稿说明。

---
name: sme-development-projects
description: 处理优质中小企业培育、申请书审核和申报写作，按任务形成方向、条件判断、材料体检或正文；前期预评估可衔接 sme-score-preassessment。
---

# 中小企业培育项目

按本轮单点、局部、培育或申请书任务处理。材料体检参考 [material-checkup-report-template.md](references/material-checkup-report-template.md)：现状、可行性和培育使用五章 19 内容块的行动型报告，已有申请书核稿逐字段列发现。申请书采用对应表单 DOCX，分析与体检采用固定 HTML 生成 PDF；内容生成后按实际状态交付。

## 项目与事实

记录项目层级、地区、年度、批次、新申报或复核及表单版本，版本识别见 `references/application-version-gate.md`，不明部分以候选情景继续。按 `references/current-policy-baseline-2026.md` 核对管理办法。批次专用规则和表单由客户提供，先完成普通条件和材料体检。

从当前对话和已交材料识别首次填报者与已有填报经验者，仍会影响讲解方式时只补问一次；首次填报按当前系统栏位给填法和资料入口，有经验者直接给字段差异、勾稽关系、资格影响和补强动作，已有申请书审核直接进入逐字段核查。

现实资料与申请材料分别标来源：政策、目录、登记和对标使用可验证资料，申请书中的财务、经营、技术、客户、产能、指标和权利状态作为本轮企业输入。材料矛盾、计算及权威来源冲突保留原值并指出。自述可支持产品及方向判断，结合产品边界、技术因果、同类环节和跨章一致性评价；外部证明作为补充证据。

## 专业方法

- 按 `references/evaluation-workflow.md` 核对直通条件、排除情形、资格及评价项，标已核、计算、自述、缺失、冲突；当期标准与历史评分分别记录。财务复用 `enterprise-financial-facts/v1` 并由 `financial-verification` 核对，税务信号和政策资格分别判断。
- 方向卡参考 `references/direction-card-first-template.md`，比较企业现有、用户给定和建议新增方向的内容、收益、问题、培育、专利和申报角色；按已有信息形成推荐，客户、交付、收入及产业环节分别识别。
- 完整培育路径参考 `references/policy-application-path-contract.md`，覆盖相关主梯度、研发、绿色、数字化、IP、质量品牌和产业化，按条件成熟度、建设后、条件触发或长期梯度排序，列补证后复检节点。
- 产业链及六基使用 `industry-chain-foundation-matcher` 的原目录、精确近似和未命中结果；市场、排名、补短板、锻长板、填空白和替代使用 `industry-positioning`、`evidence-ledger` 的边界、对象、计算和来源方法，各项目采用自身政策条件。
- 产品与收入见 `references/main-product-naming-and-boundary-gate.md`、`core-formula-process-performance-matrix.md`，市场见 `market-share-workpaper-method.md`，技术见 `technology-advancement-feasibility-rubric.md`。技术载体及终端商业产品分别映射。
- 六问参考 `references/direction-card-to-six-questions.md`，每套对应一个产品；专利布局衔接 `patent-router`，正式写作衔接 `application-writing`。企业简介参考 `references/enterprise-introduction-method.md`，沿企业三段、产品技术五段，第四段为精细化管理；表单结构按当期要求。

## 当前栏位填写指引

首次填报者每到一个实际栏位，按以下顺序逐栏回答。

- 说明填什么，给出可直接填写的内容，数值按当前栏位注明单位、正负号和小数位。
- 说明从哪来，定位到对应报表、材料及统计口径。
- 说明填错会怎样，指出当前版本对应的必填校验、勾稽关系或资格条件。

已有值直接按这三项核对。缺少界面规则时写“缺该栏系统要求”，读取该栏说明后再给具体精度。

## 四项判断与输出

按 `references/four-judgment-decision-table.md` 对主导产品、补短板、填空白和国产替代分别给保留、替换或补证后保留，列对象、环节、依据和联动动作，锻长板单列优势证据。收入、客户和 I 类权利跨章节对应，申请、授权及有效状态分列。市场条件采用目标项目与年度；2026 小巨人新申请按当期申请书处理占有率或排名，证明材料使用其实际要求。

结构化结果保留 `application_context`、`overall_conclusion`、`four_judgments`、`hard_gates`、`evaluation`、`evidence_gaps`、`risks`、`actions`。缺陷与差距用 `items` 列要求、企业现状、差距、证据、补强动作、优先级。上下文含 `project_level`、`region`、`year`、`application_type`、`form_version`、`version_status`、`policy_status`。

- 总体状态：`eligible`、`conditional`、`ineligible`、`undetermined`。
- 四项键：`leading_product`、`bottleneck`、`gap_filling`、`import_substitution`；各项含 `decision`、`evidence_state`、`object`、`reason`、`actions`。
- 决策值：`retain`、`replace`、`retain-after-evidence`；证据状态：`verified`、`computed`、`claimed`、`missing`、`conflicting`。
- 发展质量评价条件按同年度主管平台回执对照当期政策，客户输出写已满足、不满足或缺正式回执。每个缺项给复核或补强动作。

客户端检查接口 `sme-development-projects.validate-assessment` 使用 `{"assessment":"工作区结果.json"}`；其他宿主可运行 `python3 scripts/validate_sme_assessment.py <结果.json>`。按真实结果定向修正，生成内容或文件直接交付，缺项集中列一次。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

内部校验需要 `evaluation.quality_score` 时，已核验回执的原值和出处随原始证据传给 `verified-platform-score` 分支，缺回执用 `pending-platform-evaluation` 且 `value` 为 `null`。客户正文使用条件状态与缺陷条目。

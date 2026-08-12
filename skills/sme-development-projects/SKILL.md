---
name: sme-development-projects
description: 分析创新型中小企业、专精特新中小企业、专精特新小巨人及相关培育项目。用户提及专精特新、小巨人、补短板、填空白、企业简介或主导产品产业链归属时使用。
---

# 中小企业培育项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "sme-development-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 项目与版本闸门

1. 先确认创新型中小企业、专精特新中小企业、专精特新“小巨人”或地方培育项目，再确认地区、申报年度、批次和新申报或复核。
2. 读取 `references/application-version-gate.md`。申请书版本识别失败、同时命中多个版本或用户确认版本与材料不一致时立即停止，不评分、不形成达标结论、不撰写正式正文。
3. 任何专精特新或小巨人任务必须读取 `references/current-policy-baseline-2026.md`，并重新核验当期通知。活动技能只保留 2026 政策分支，不运行历史四维评分或内部百分制。2026 年度小巨人复核按 2026 当期通知明确的过渡要求把握；该例外仅适用于通知指定的复核对象和期间，不能扩展到新申报或未来年度。

## 前期培育报告方向卡门禁

任务属于前期培育报告、产品方向选择或未来专利培育时，先完整读取 `references/direction-card-first-template.md`。先分别形成企业现有方向、用户给定方向和建议新增方向三类方向卡，每张卡直接写方向内容、好处、坏处、培育建议、专利布局和申报角色；完成横向比较与推荐后，才进入政策适配和申报成熟度。

方向卡阶段有资料就分析，没有就跳过，不因缺少第三方证据阻断方向判断。共享算法或底层能力不等于同一主导产品，不得用抽象“技术母体”把客户、交付物、收入边界或产业环节明显不同的方向硬合并。生成 Word 报告时复制 `assets/专精特新小巨人前期培育方向卡模板.docx` 到任务输出目录后填写，禁止直接改写技能内母版。

## 评价流程

4. 前期培育报告先完成方向卡和方向选择，再按 `references/evaluation-workflow.md` 依次核验直通条件、排除项、硬门槛和评价指标，区分已核验事实、计算结果、企业自述、缺失和冲突。命中历史评分表、旧培训材料或历史申请书时标记为历史档案并退出当前评价链，不提取旧条件、不计算旧分数。
5. 核验专业化、精细化、特色化、创新能力、财务、知识产权和产业链要求。某企业入选只证明其在对应年度、地区和批次通过评审，不能反推其满足全部评分项；不同年度、地区和政策口径的企业不得直接横向排名。

核验营收、利润、研发费用、资产负债率和增长率时，先读取同一企业的 `enterprise-financial-facts/v1` 共享事实，经 `financial-verification` 校验后复用。税务风险提示不自动转为专精特新或小巨人不达标结论。

涉及产业链或“工业六基”时，必须调用 `industry-chain-foundation-matcher`，严格使用其目录索引和精确、近似、未命中三级规则。没有精确命中时，输出一个相似目录项和一个推定产业链，均不得伪装成目录原文。

涉及市场占有率、细分领域排名、补短板、锻长板、填空白或国产替代时，必须调用 `industry-positioning`，读取其细分市场边界与产业链价值证据闸门，并将市场边界、测算口径、替代对象和证据状态写入 `evidence-ledger`。行业标准、海关编码和协会分类只按各自适用范围交叉验证，不得代替当期申请表指定的行业或产品分类。

主导产品命名、收入边界和自产自用核心技术载体分别读取 `references/main-product-naming-and-boundary-gate.md`、`references/core-formula-process-performance-matrix.md`。细分市场占有率读取 `references/market-share-workpaper-method.md`；技术先进性和工程落地性读取 `references/technology-advancement-feasibility-rubric.md`。这些方法只统一证据与计算顺序，不替代当期政策门槛。

前期培育报告进入补短板、填空白和六问展开前，读取 `references/direction-card-to-six-questions.md`。每套六问只服务一个已选产品方向；专利结构、未来布局和检索交给 `patent-router`，正式正文交给 `application-writing`，不得另建并行专利或写作入口。

诊断或改写企业总体情况简介时，先读取 `references/enterprise-introduction-method.md`。采用企业基本情况三段和主导产品技术四段加一可选段的结构，保持官方章节兼容，逐段建立行业问题、核心技术、量化指标、验证证据和产业链价值闭环。

## 四项独立判断

读取 `references/four-judgment-decision-table.md`，分别对主导产品、补短板、填空白和国产替代作出“保留、替换、补证后保留”结论，并单列锻长板证据。四项属于待审判断，不因申请书已经填写而自动成立；每项必须说明对象、同类环节、证据和联动修改。主导产品、四项判断、收入、客户和 I 类知识产权必须跨章节一致。

不得把审中专利视为有效授权成果。财务、市场份额、客户、领先地位和进口替代等信息没有可靠来源时，不推算、不补造，只列证据缺口。不得把“全球前三或国内第一”写成专精特新和小巨人的通用门槛；2026年小巨人新申请按当期申请书的占有率或排名条件执行，且不要求另行提交第三方市场占有率证明。

结构化诊断完成后运行 `python3 scripts/validate_sme_assessment.py <结果.json>`，检查版本确认、政策状态、四项判断和证据状态。验证失败时不得交付正式结论。

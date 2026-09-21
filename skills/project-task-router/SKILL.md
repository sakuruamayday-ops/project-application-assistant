---
name: project-task-router
description: 识别政府项目申报、企业分析、知识产权、财税法律和标准撰写任务阶段并路由专业技能。适用于用户不知道具体能力名称、同时咨询多个任务或需要从检索到交付的组合流程。
---

# 申报任务路由


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

先按本技能文档执行，工具调用以当前宿主实际暴露的接口为准。一般任务按需读取；用户要求源码审阅、接口核对或修复时，可直接定向读取相关源码、帮助和样例，不必先制造失败。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

本技能是 `project-application-assistant` 的内部路由器，不作为独立首页入口。仅在任务阶段不明、同时包含多个阶段或需要组合执行时触发；单一明确任务直接调用对应专业技能。

任务深度、确认复用、继续与完成条件统一执行 [共享任务边界](../_runtime/task-execution.md)，不在路由器重复维护。只选择一个主流程；单点查询、局部分析、正式交付不因领域词自动升级。

将任务归入政策检索、企业画像、项目匹配、可行性、材料写作、质量检查、版本对比、标准撰写或归档。

优先使用自然语言意图，不要求用户记住技能名。复杂任务明确列出调用顺序；缺少外部能力时说明降级路径。用户明确要求专业报告时，企业名称加现有资料即可作为入口，不要求用户先填写企业基本信息表；主体缺口由天眼查、企查查及官方来源补齐并标注证据状态。

外部企业数据统一执行 [企业数据源有限降级协议](../_runtime/enterprise-source-fallback.md)：完整企业数据能力可做全维核验；仅有部分公开数据时明确未覆盖字段；没有企业数据工具时只使用用户材料和官方来源，不输出“已完成全维核验”等伪完整结论。任何等级均不得用过期第三方财务数据补造客户事实。

单项目按 `references/domain-routing-matrix.md` 选择领域技能；多项目由共享任务边界确定主流程，该矩阵只用于分配领域子问题。不得因为调用多个领域技能而产生多个整份报告负责人。

执行阶段互斥：

- 找政策使用 `policy-retrieval`，判断能否申报使用 `project-feasibility`。
- 用户要求某个具体项目的“前期评估报告”或“可行性分析报告”时，以 `project-feasibility` 负责统一报告合同，再按 `references/domain-routing-matrix.md` 选择一个领域技能负责项目专属条件。前者输出谈单版核心条件、企业值、差距和补强，后者输出现行条件或完整评分表、证据、动作、验收标准和倒排计划；不得将两类报告合并成同一深度。
- 查询哪些企业已经获得某项认定、某产品或行业有哪些获评企业、公示或名单时，路由 `local-knowledge-retrieval` 并调用统一 `recognition_search`；不得进入企业可行性分析。查询计划必须保留全部项目、主题、地区和年度，确切、相关、待核验三档不得混写。
- 同行名单与主体核验使用 [名单与主体来源路由](../_runtime/recognition-source-routing.md)，不重复维护固定串行检索链。
- 只核验政策版本、效力、是否过期、是否被替代或完整文件链，且暂不判断企业条件时，`policy-retrieval`具有最高主路由优先级；具体项目领域技能只能辅助，不得占用`primary_skill`。旧年度、已截止或有效性不明时同时限制结论。
- 高企认定的申报年度选择、成长性测算和申报前评分使用 `high-tech-enterprise-preassessment`；按正式申请书母版扩缩RD、PS表并撰写、回填或核稿时使用 `high-tech-enterprise-application-drafting`；普通科技项目匹配仍使用 `technology-innovation-projects`。
- 专精特新或小巨人只有企业基础资料、财务底表并要求“评分、测分、差多少分”时使用 `sme-score-preassessment`；已形成申请书的体检和跨章节核验使用 `sme-development-projects`。
- 写正文使用 `application-writing`，检查单份终稿使用 `consistency-check`，比较多版本使用 `application-version-diff`。
- 查产业目录使用 `industry-chain-foundation-matcher`，判断企业定位证据使用 `industry-positioning`。
- 判断知识产权申报证据使用 `ip-assessment`；公司级专利查新、布局、FTO、挖掘交底和预审推荐统一使用 `patent-router`；单独核稿使用 `checking-patdocx-cn-single-agent`。

涉及登录网站、动态页面筛选、翻页、表单、上传或结构化网页提取时，调用 `web-task-operator`；政策和企业专业判断仍由对应业务Skill完成。

涉及浙江省首台套、首版次或首批次的历年目录变化、企业产品匹配和跨年状态时，统一路由 `local-knowledge-retrieval`。由该技能通过现有 `jiaotang-kb` MCP 的 `three_first_analysis` 统一入口自动组合名单、目录差异、产品匹配和原文读取；不得要求用户新增 MCP、重新申请凭据、记忆内部工具名或手工选择工具。

涉及财务门槛时先路由 `financial-verification`。若 `manufacturing-tax-risk-analysis` 已产出同一企业的 `enterprise-financial-facts/v1`，则校验后交给 `project-feasibility` 复用；只有企业身份、期间、口径或来源不符时才重新提取。

涉及写标准、编标准、企业标准、团体标准、产品标准、服务标准、管理标准、试验方法标准、标准修订、标准审查或编制说明时，路由 `standard-drafting`。先确定标准层级和文件功能，再核验现行起草规则、法规、强制性标准及同类标准。

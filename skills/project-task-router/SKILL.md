---
name: project-task-router
description: 识别政府项目申报、企业分析、知识产权、财税法律和标准撰写任务阶段并路由专业技能。适用于用户不知道具体能力名称、同时咨询多个任务或需要从检索到交付的组合流程。
---

# 申报任务路由


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-task-router" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

本技能是 `project-application-assistant` 的内部路由器，不作为独立首页入口。仅在任务阶段不明、同时包含多个阶段或需要组合执行时触发；单一明确任务直接调用对应专业技能。

将任务归入政策检索、企业画像、项目匹配、可行性、材料写作、质量检查、版本对比、标准撰写或归档。

优先使用自然语言意图，不要求用户记住技能名。复杂任务明确列出调用顺序；缺少外部能力时说明降级路径。

外部企业数据按三级降级：完整企业数据能力可做全维核验；仅有部分公开数据时明确未覆盖字段；没有企业数据工具时只使用用户材料和官方来源，不输出“已完成全维核验”等伪完整结论。任何等级均不得用过期第三方财务数据补造客户事实。

领域项目先按 `references/domain-routing-matrix.md` 选择一个主领域技能。单项任务不得同时散弹调用多个领域技能；确实跨领域时说明每个技能负责的子问题和调用顺序。

执行阶段互斥：

- 找政策使用 `policy-retrieval`，判断能否申报使用 `project-feasibility`。
- 高企认定的申报年度选择、成长性测算和申报前评分使用 `high-tech-enterprise-preassessment`；普通科技项目匹配仍使用 `technology-innovation-projects`。
- 专精特新或小巨人只有企业基础资料、财务底表并要求“评分、测分、差多少分”时使用 `sme-score-preassessment`；已形成申请书的体检和跨章节核验使用 `sme-development-projects`。
- 写正文使用 `application-writing`，检查单份终稿使用 `consistency-check`，比较多版本使用 `application-version-diff`。
- 查产业目录使用 `industry-chain-foundation-matcher`，判断企业定位证据使用 `industry-positioning`。
- 判断知识产权申报证据使用 `ip-assessment`，规划未来申请使用 `patent-layout-planning`。

涉及登录网站、动态页面筛选、翻页、表单、上传或结构化网页提取时，调用 `web-task-operator`；政策和企业专业判断仍由对应业务Skill完成。

涉及浙江省首台套、首版次或首批次的历年目录变化、企业产品匹配和跨年状态时，统一路由 `local-knowledge-retrieval`。由该技能通过现有 `jiaotang-kb` MCP 的 `three_first_analysis` 统一入口自动组合名单、目录差异、产品匹配和原文读取；不得要求用户新增 MCP、重新申请凭据、记忆内部工具名或手工选择工具。

涉及财务门槛时先路由 `financial-verification`。若 `manufacturing-tax-risk-analysis` 已产出同一企业的 `enterprise-financial-facts/v1`，则校验后交给 `project-feasibility` 复用；只有企业身份、期间、口径或来源不符时才重新提取。

涉及写标准、编标准、企业标准、团体标准、产品标准、服务标准、管理标准、试验方法标准、标准修订、标准审查或编制说明时，路由 `standard-drafting`。先确定标准层级和文件功能，再核验现行起草规则、法规、强制性标准及同类标准。

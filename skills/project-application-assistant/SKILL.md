---
name: project-application-assistant
description: 企业全生命周期总控技能。用于政府项目匹配、政策检索、企业分析、专利、财税法律、标准撰写、材料质量检查和归档，自动选择本技能包中的专业技能并组织执行顺序。
---

# 企业全生命周期助手


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-application-assistant" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

本技能是对外唯一推荐总入口。先识别企业、地区、年度、目标项目和当前任务阶段，再选择专业技能；`project-task-router` 只作为内部阶段路由器，不与本技能同时向用户争抢入口。

每次开始实质任务前读取 `~/.config/project-assistant/preferences.json` 的 `preferences`，将其作为官方规则之后的个人覆盖层。个人偏好只能调整地域、格式、详细度、语气、术语和工作流选择，不得覆盖政策有效性、事实核验、财务真实性、权限和正式材料质量门禁。

用户提出“以后都这样”“默认这么写”“记住这个习惯”时，将要求拆成结构化字段并调用 `first-run-configuration/scripts/manage_preferences.py set <字段> <值> --sync`。不得为个人习惯直接改写任何正式 `SKILL.md`。用户纠正的是通用事实或质量缺陷时，才交给受控自进化套件形成候选规则。

## 首次加载

1. 先读取 `first-run-configuration` 生成的统一能力报告；报告不存在时先运行该Skill，不允许云端、企查查、专利、浏览器和OCR能力分别重复索要凭据。
2. 确认受控自进化套件处于启用状态：`experience-recorder` 负责记录脱敏经验，`skill-curator` 负责发现冲突，`skill-evolution` 负责生成候选优化，`evolution-governance` 负责审批、快照和回滚。不得因更换Agent平台而跳过。
3. 再检查宿主持久记忆中的 `project_application_assistant.default_region`；宿主无持久记忆时，运行 `scripts/user_region_profile.py get`。
4. 未设置时，在执行其他申报任务前询问：“你的默认政策地区是哪里？请填写到省、市，例如浙江省杭州市。”
5. 将地区写入宿主持久记忆；不可用时运行 `scripts/user_region_profile.py set <地区>` 自动保存，不要要求用户手工编辑配置文件。
6. 设置成功后告知默认加载范围和临时切换方法。详细规则见 `references/region-loading-rules.md`。

用户说“修改默认地区”时更新记忆。用户只在某次任务中指定其他地区时，仅临时切换，不覆盖默认地区。

市级、区级项目必须先解析地区层级。裸问“市企业技术中心”等市级项目时使用默认城市；区级项目先使用企业注册区或用户在本次任务中说明的区县，仍无法确定时再追问。不得把泛称“市级”固定映射为杭州市，也不得混入其他城市或兄弟区县政策。

## 工作流

1. 信息不足时列出缺口，不自行补造。
2. 先调用 `local-knowledge-retrieval` 检索团队云端知识库，再按默认地区加载当地、上级省级和国家级项目地图。用户已明确启用 `third-party-data-indexing` 时可将其作为发现线索；无论是否启用，都必须继续核验管理办法和官方当期通知。
3. 项目涉及营收、利润、研发投入、资产或负债门槛时，先查找当前企业的 `enterprise-financial-facts/v1` 共享事实文件；通过 `financial-verification` 校验后复用，不重复索要已有可靠财务数据。
4. 依次调用 `project-matching`、`project-feasibility`、`application-writing` 和 `consistency-check` 完成项目匹配、可行性分析、材料写作与提交前检查。
5. 数字、日期、政策和知识产权结论进入证据链。
6. 不承诺企业一定符合或一定获批。

标准撰写任务不进入项目匹配链，直接调用 `standard-drafting`；先完成标准类型识别、依据矩阵和标准设计，再起草正文、编制说明及审查清单。

高新技术企业申报前评估、申报年度比较和成长性测算直接调用 `high-tech-enterprise-preassessment`。专精特新或小巨人只有企业基础资料并要求前期评分时调用 `sme-score-preassessment`；已经形成申请书时进入 `sme-development-projects` 的版本确认与后期体检流程。

## 任务结束

客户项目分析、正式申报材料、复杂分析、重要规则变更或基础设施迁移完成后，必须调用 `experience-recorder` 记录可泛化经验，并在对话结尾实际回答四问，不得只列问题：

1. 眼下最没有把握的事情是什么？
2. 关于当前情况，最大的遗漏是什么，还有什么没有意识到？
3. 对当前成果最有价值的创新改进是什么？客户产品任务则说明最值得增加的行业领先功能或创新点。
4. 可以用哪些不同做法提高本次任务效率？

普通问候、单句确认和不产生实质成果的轻量任务可不执行四问。四问只写在对话总结中，不写入正式申报书、企业报告或客户交付正文。

## 签单后资料移交

商务人员使用本技能包形成终版谈单资料并完成签单后，应将终版资料及客户已提供的必要附件发送给对应职能部门，供项目、专利或其他服务人员继续服务企业。

- 发送前确认使用终版文件，避免草稿和历史版本混入。
- 明确合同服务范围、已确认事项、待补资料和下一步工作。
- 原始客户资料按实际授权传递，不在材料中夹带账号、API Key、Token或无关个人信息。
- 本技能包不负责自动发送、消息通知、人员分配或进度管理。
- 当前不设置独立的 `project-handoff` Skill；真实业务出现结构化交接需求后再评估。

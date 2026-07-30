---
name: policy-retrieval
description: 检索并核验政府项目从管理办法、当期通知、指南附件、官方答疑、更正延期到公示结果的完整政策链；用户询问政策条件、申报时间、材料、最新通知或政策有效性时使用。
---

# 政策检索


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "policy-retrieval" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

检索并核验政府项目的完整政策链。只负责取得可靠政策依据，不代替企业资格判断和材料撰写。

## 强制流程

1. 明确地区层级、主管部门、项目名称或简称、目标年度和需要回答的问题。
2. 先查本地已归档原文，再查政府官方站点；第三方平台只作标题、文号和链接线索。用户提供发文机关正式直达链接时必须直接核验，不得因通用搜索引擎尚未收录而跳过。
3. 当年度通知采用固定降级链：先查发文机关直达页、栏目和站内检索；仍未命中时查省、市、区县政府官网对上级通知的明确引用；再次未命中时，从最近一次已核验申报通知提取其引用的当前有效管理办法。
4. 下级政府官网引用只能证明页面逐项写明的年度事实；当前有效管理办法只能生成稳定门槛和下一年度准备方向，不得补写当年度批次、企业截止时间、申报系统、年度材料或复核对象。相关字段保持未知。
5. 按“长期管理办法→当期申报通知→指南及附件→官方答疑→更正或延期→公示结果”补齐政策链。
6. 核验文件标题、文号、发布机关、发布日期、适用地区、适用年度、有效状态、原文链接和核验时间。
7. 将条件拆成申报主体、硬门槛、排除项、评分项、材料、流程、截止时间和奖补方式；不得把评分项写成硬门槛。
8. 发现新旧文件冲突时，保留两份原文并说明替代关系；无法确认时标记待核验。
9. 用户提供的文件年度早于目标申报年度、已经截止、已被替代或有效期不明时，先标记为历史或待核验文件，禁止直接作为当前批次依据。当前政策链未核实时，不进入企业资格判断；如需输出结构化路由状态，`policy_status`标为`stale`或`unknown`，`claims_limited`必须为`true`。

## 来源与失败边界

- 官方原文优先于转载、解读和商业平台摘要。
- 搜索结果页、新闻稿或项目汇总表不能替代正式通知和附件。
- 未找到完整政策链时，只能说明“当前检索层未命中”及已检索范围。
- 截止日期、金额、比例和政策状态在答复时重新核验，不沿用历史记忆。
- 历史文件只能用于口径沿革或预研参考。没有取得目标年度现行文件时，不得形成“可申报、不可申报、符合、不符合”的资格结论。

## 输出

先给政策链完整度，再给政策文件表、条件结构和缺失项。记录格式见
`references/policy-record-schema.md`，官方来源和冲突处理见
`references/official-source-routing.md`。

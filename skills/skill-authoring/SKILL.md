---
name: skill-authoring
description: 供管理员为本套件创建或修改专业技能候选，规划触发、互斥、工作流、资源、脚本、来源许可、测试和治理审批；不进入普通企业或政府项目任务，也不直接改写已签名核心。
---

# 技能创建


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "skill-authoring" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与权限

为本套件创建或修改技能候选。仅在用户明确要求维护技能时触发，不进入普通企业或政府项目路由，不直接改写已签名发布核心。

## 流程

1. 收集至少三个真实使用示例，包括正常任务、边界任务和应拒绝或转路由的任务。
2. 明确技能职责、触发描述、互斥技能、输入、输出、失败模式和依赖。
3. 只加入模型无法稳定自行完成的领域规则；详细内容放入一层 `references/`。
4. 重复、脆弱或需复算的操作才编写脚本，并实际运行测试。
5. 记录来源、作者或机构、许可证、可再分发性和脱敏结论；权属不明内容不得复制。
6. 运行结构验证、依赖检查和脱敏前向测试。
7. 将修改作为候选提交 `skill-curator`、`skill-evolution` 和 `evolution-governance`，批准后再由统一发布流程签名。

成熟度标准见 `references/skill-maturity-rubric.md`。结构初筛运行
`scripts/validate_skill_structure.py`；脚本通过不代表业务测试通过。

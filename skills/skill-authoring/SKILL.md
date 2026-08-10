---
name: skill-authoring
description: 供管理员为本套件创建或修改专业技能候选，规划触发、互斥、工作流、资源、脚本、来源许可、测试和治理审批；不进入普通企业或政府项目任务，也不直接改写已签名核心。
---

# 技能创建


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "skill-authoring" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
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

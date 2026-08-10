---
name: project-memory
description: 管理政府项目客户任务的企业与项目身份、事实锁、政策版本、待办、决定、交付物和跨会话连续性；用户提到继续、上次或既有客户项目时使用，与个人偏好分离。
---

# 项目记忆


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-memory" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

保存和召回客户项目连续性信息。项目事实与个人写作偏好分开管理；本技能不代替WorkBuddy偏好桥。

## 可保存内容

- 企业完整名称、项目名称、申报年度和已确认表单版本。
- 已确认事实及证据编号、政策版本、重要决定和待补材料。
- 当前阶段、交付物路径、负责人明确要求和下一步。

## 禁止内容

不得保存密码、密钥、验证码、证件原图、无关通信内容或未脱敏客户原文。涉及个人信息时只保存完成任务所需的最小字段。

## 流程

1. 以企业、项目、年度建立项目标识，不按简称混用客户。
2. 召回时只加载当前任务所需字段，并标注记录来源和更新时间。
3. 七天以上的可变状态标记为待复核；政策、截止日期、企业状态和专利状态必须重新核验。
4. 新事实与旧记录冲突时保留历史版本，记录冲突和确认结果。
5. 阶段结束时形成检查点，不自动归档正式材料。

项目记录结构和过期规则见 `references/project-memory-schema.md`。结构化项目状态可使用
`scripts/project_state.py` 校验、写入和读取。

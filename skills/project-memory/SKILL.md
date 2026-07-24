---
name: project-memory
description: 管理政府项目客户任务的企业与项目身份、事实锁、政策版本、待办、决定、交付物和跨会话连续性；用户提到继续、上次或既有客户项目时使用，与个人偏好分离。
---

# 项目记忆


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-memory" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
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

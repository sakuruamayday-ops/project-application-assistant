---
name: regional-special-projects
description: 将未纳入固定领域的市、区县、园区临时通知和新申报项目转换为带原文位置的候选规则，经核验后交project-feasibility；不为每个短期通知新建技能；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 区域特色项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "regional-special-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

把尚未形成固定领域模型的市、区县、园区临时通知转换为可审计候选规则，不为每个短期项目创建新技能。

## 流程

1. 调用 `policy-retrieval` 取得正式通知、附件、更正和延期文件。
2. 提取地区层级、主管部门、申报主体、适用行业、硬门槛、排除项、评分项、材料、流程、截止时间和奖补方式。
3. 每条规则保留原文位置和证据等级；无法确认的字段标记待核验。
4. 运行 `scripts/validate_candidate_rule.py` 检查规则结构。
5. 经人工核验后交给 `project-feasibility`，不得将候选规则直接写成正式政策事实。

## 数据不足处理

只有新闻稿、转载或摘要时，候选规则保持未核验，不输出明确截止日期和资格结论。附件缺失时列出缺失文件名和可能影响的判断字段。

## 输出

结构见 `references/regional-rule-schema.md`。同名项目跨地区不得复用规则，下一年度不得无核验沿用。

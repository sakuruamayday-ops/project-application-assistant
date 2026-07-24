---
name: talent-projects
description: 分析个人、创新团队、创业人才、海外人才、博士后和人才载体项目，核验身份、劳动或创业关系、到岗时间、团队任务及隐私边界。
---

# 人才项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "talent-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与分型

处理个人、创新团队、创业人才、海外人才和博士后等项目。先识别申报主体是人才本人、团队还是用人单位。

## 核验流程

1. 核验学历职称、工作经历、劳动关系、社保个税、到岗时间和地域要求。
2. 创业人才核验持股、实缴、任职、企业成立和项目产业化。
3. 团队项目核验负责人、核心成员、分工、稳定性和共同任务。
4. 将人才成果与申报项目、企业产品和实施目标建立关联。
5. 检查合同、社保、任职、入境或回国、项目期的时间线冲突。
6. 来源缺失或冲突时保留各来源原值、日期和出处，建立冲突项，不得静默择一或补造。会影响人才身份、劳动关系、到岗或地域门槛的，暂停资格结论，列明需补的合同、社保个税记录、任职文件、出入境或主管部门证明，并标注应由申报单位、人才本人或主管部门中的哪一方确认。

个人信息按最小化原则处理，证件原文不进入公共技能和日志。详细规则见
`references/talent-evidence-matrix.md`；结构化日期可运行
`scripts/validate_talent_timeline.py`。输出须区分已核验、待核验、来源冲突和因此受限的结论。

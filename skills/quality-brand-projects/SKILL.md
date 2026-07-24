---
name: quality-brand-projects
description: 分析产品认定、制造精品、政府质量奖、标准品牌、市场地位、单项冠军和隐形冠军项目，先识别项目类型再核验对应质量、标准、认证、管理和市场证据。
---

# 质量品牌项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "quality-brand-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与项目分型

处理产品认定、组织质量奖、标准品牌、市场地位和冠军类项目。开始分析前必须先确定项目类型，不得将浙江制造精品、质量奖和单项冠军混用一套条件。

## 核验维度

- 产品认定：产品、标准、检测、认证、质量稳定性和市场应用。
- 组织质量奖：质量管理模式、持续改进、经营绩效和组织治理。
- 标准品牌：标准先进性、认证、品牌建设和示范应用。
- 市场地位：细分市场定义、销售口径、市场容量、排名来源和期间。
- 冠军类项目：长期专注、单项产品、市场地位、创新和产业链作用。

市场占有率和排名必须说明分子、分母、细分市场、地域、期间和来源。项目分类和证据等级见
`references/quality-brand-taxonomy.md`。

输出项目分型、硬门槛待核验项、评分证据、不可证明项和下一步。

---
name: industry-positioning
description: 在industry-chain-foundation-matcher给出目录候选后，判断企业主导产品的产业链关键环节和重点领域定位是否有收入、技术、客户、产线及知识产权证据；用于补短板、填空白和国产替代三档决策，不负责自行检索或创造目录分类。
---

# 产业定位


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "industry-positioning" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与依赖

本技能是产业定位的判断层，不负责检索目录。凡询问产业链、工业六基、产业基础目录或开展专精特新和小巨人定位，必须先调用 `industry-chain-foundation-matcher` 取得可追溯匹配结果。

## 双维判断

1. **产品维度**：主导产品是否实际处于候选产业链关键环节，产品功能、材料、工艺、客户和上下游位置是否一致。
2. **企业维度**：企业研发、生产、收入、客户、知识产权和产业化证据是否足以支撑该重点领域定位。

目录命中不等于企业自动符合。重点识别：

- 牵强挂靠：目录名称相似，但产品对象、功能或环节不同。
- 支撑不足：目录匹配合理，但收入、技术、客户或知识产权证据不足。

## 四项决策

主导产品、补短板、填空白和国产替代逐项输出“保留、替换、补证后保留”。替换时给出首选方案和联动章节；补证后保留时列出证据、验证标准和未补证前限制。

判断矩阵见 `references/industry-positioning-assessment.md`。不得创造目录外路径或用企业经营范围代替产品实质。

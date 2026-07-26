---
name: patent-fto-analysis
description: 针对明确产品版本、拟实施行为、目标国家或地区和基准日期，独立检索并分析当前有效及可能授权的专利权利要求，形成自由实施FTO风险初筛、要素对照、权利状态、到期时间和规避验证建议。用户提到FTO、自由实施、上市侵权风险、出口专利风险或产品落入专利范围时使用，不与创造性或授权性检索混用。
---

# 专利FTO分析


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-fto-analysis" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

先使用 `patent-data-foundation`，再使用 `patent-search-core` 的FTO模式。读取 [fto-boundary.md](references/fto-boundary.md) 后执行。

## 工作流

1. 固定产品版本、部件、工艺、供应链行为、法域、上市时间和基准日。
2. 检索目标法域当前有效授权及可能在上市期授权的审中申请。
3. 强制获取授权公告B版权利要求；缺少B版停止现行范围结论。
4. 按全部必要技术特征逐项比对，分别分析独立和从属权利要求。
5. 核验权利人、剩余期限、无效复审、许可和法律状态。
6. 输出高、中、低和证据不足风险，以及规避方向和律师复核清单。

不以创造性相似度替代侵权要素对照，不出具“不侵权保证”。

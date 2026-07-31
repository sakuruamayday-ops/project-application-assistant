---
name: peer-benchmarking
description: 从政府公示名单和公开资料中建立同项目、同政策版本、同地区、同产品的可比企业事实对标，核验主体和年度口径；不由入选结果推定未公开评分或全部条件；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 同行对标


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "peer-benchmarking" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

从公开名单和公开材料中寻找可比企业，为申报定位提供事实参照，不推断未公开的申请书内容或专家评分。

## 流程

1. 明确目标项目、年度、地区、行业、产品和对标目的。
2. 优先获取政府正式公示或认定名单，第三方平台仅用于定位官方来源。
3. 锚定企业完整名称，避免集团、子公司和同名主体混淆。
4. 按同项目、同政策版本、同地区、同细分行业、同类产品和相近规模评估可比性。
5. 分开记录公开事实、可计算指标、合理推断和未知项。
6. 入选事实只证明企业在对应年度获得该结果，不自动证明每个评分项均满足或高分。
7. 跨年度比较前核验管理办法、申报范围和评价指标；口径不一致时只作历史背景或趋势参考。

## 输出

输出来源清单、可比性评分、事实对比表、政策口径差异和不可比较项。详细规则见
`references/peer-comparability-rules.md`。

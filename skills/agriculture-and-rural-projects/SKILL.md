---
name: agriculture-and-rural-projects
description: 分析农业农村、乡村振兴、农业科技、农产品加工、未来农场、农业品牌和联农带农项目；用于核验农业主体、基地、生产、加工、质量安全和利益联结，纯食品制造或销售项目应转工业化或质量品牌技能。
---

# 农业农村项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "agriculture-and-rural-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与边界

处理农业经营主体、基地、种养殖、农产品加工、联农带农、农业品牌和乡村振兴类项目。仅有食品制造或销售、没有农业生产和利益联结证据的，转入工业化或质量品牌项目。

## 核验流程

1. 识别企业、合作社、家庭农场、村集体等主体类型和注册地区。
2. 核验土地或基地权属、生产周期、产量、加工能力、质量追溯和许可认证。
3. 核验与农户、村集体或合作社的合同、收购、就业、分红和收益数据。
4. 区分企业自营、订单合作、委托加工和未来规划，不把计划规模写成已实现规模。
5. 将科技、品牌和产业链成效分别对应到检测、认证、订单、产销和利益联结证据。

## 数据不足处理

没有土地、产量、农户或收益证据时，不得用企业宣传材料补足。能够确认加工和销售、不能确认农业生产或联农带农时，分别标记已核验范围与缺失范围。

## 输出

按 `references/agriculture-evidence-matrix.md` 输出主体适配、事实、缺口和转路由建议。

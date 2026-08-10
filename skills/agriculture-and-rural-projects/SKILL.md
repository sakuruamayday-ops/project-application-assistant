---
name: agriculture-and-rural-projects
description: 分析农业农村、乡村振兴、农业科技、农产品加工、未来农场、农业品牌和联农带农项目；用于核验农业主体、基地、生产、加工、质量安全和利益联结，纯食品制造或销售项目应转工业化或质量品牌技能；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 农业农村项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "agriculture-and-rural-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
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

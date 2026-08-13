---
name: green-development-projects
description: 分析绿色工厂、绿色供应链、节能节水、降碳、资源综合利用、清洁生产和环保改造项目，核验统计边界、基准期、单位指标、合规与实际成效；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 绿色发展项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "green-development-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与边界

处理绿色工厂、绿色供应链、节能节水、清洁生产、资源综合利用和降碳改造。环保合规不等于绿色绩效，建设计划不等于已实现成效。

## 核验流程

1. 固定组织边界、生产边界、基准期、报告期和产品产量口径。
2. 核验能源、水、原材料、废弃物、排放、碳和绿色管理数据。
3. 对总量、单位产品指标、改造前后数据和计算公式进行勾稽。
4. 区分计量数据、审计或检测数据、企业测算和目标值。
5. 核验环评、排污许可、处罚、能源审计和绿色供应链证据。

详细口径见 `references/green-metrics-boundaries.md`。结构化指标可运行
`scripts/validate_green_metrics.py` 检查期间、单位和基准一致性。

用户要求绿色工厂前期评估报告或可行性分析报告时，同时读取 `project-feasibility/references/two-report-contract.md`，按基础设施、能源资源、产品、排放、碳、管理体系和绿色绩效切换核心评估对象。前期报告只列政策明确要求且已有企业数据、已确认差距或会改变结论的条件，不机械铺陈“无处罚”等空泛合规表述；可行性报告再按当期评价表完整拆解。

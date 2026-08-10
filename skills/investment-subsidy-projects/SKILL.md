---
name: investment-subsidy-projects
description: 分析技术改造、设备更新、固定资产投资、产业化建设和专项资金项目，核验备案、建设期及合同发票付款资产证据链，复算适格投资；不代替审计结论；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 投资补助项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "investment-subsidy-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与边界

处理技术改造、设备投资、制造业投资奖励和产业化建设补助。只负责投资项目事实和费用适格性，不代替财务审计结论。

## 强制流程

1. 核验备案主体、建设地点、建设期、投资起止期和申报截止期。
2. 建立合同、发票、付款、设备到货、验收和资产入账对应关系。
3. 区分设备、软件、安装、土建、研发、流动资金及其他费用。
4. 区分含税与不含税、已投资与计划投资、新设备与二手设备、关联交易与非关联交易。
5. 按当期政策标记适格、待核验和不适格金额，不自行扩大补助范围。
6. 将投资与产能、效率、质量、就业或节能绩效对应。

费用规则见 `references/investment-evidence-chain.md`。结构化台账运行
`scripts/reconcile_investment_ledger.py` 做金额和凭证链检查。

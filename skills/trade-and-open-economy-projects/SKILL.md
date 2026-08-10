---
name: trade-and-open-economy-projects
description: 分析货物贸易、服务贸易、跨境电商、境外展会、海外品牌和境外投资项目，核验订单、报关、物流、收汇、平台及币种期间；国内电商和国内展会不适用；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 开放经济项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "trade-and-open-economy-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与分型

处理货物贸易、服务贸易、跨境电商、境外展会、海外品牌和境外投资项目。国内电商和国内展会不自动归入本技能。

## 核验流程

1. 确认经营主体、海关或平台主体、项目类型、地域和统计期。
2. 货物贸易核验订单、报关、物流、收汇和退税；服务贸易核验合同、交付、收款和涉外凭证。
3. 跨境电商区分平台订单、独立站、海关监管方式和境内普通电商。
4. 境外展会和投资核验实际发生、支付、境外主体和合规手续。
5. 金额保留原币种、折算币种、汇率来源、汇率日期和统计期间，不自行猜测汇率。

分类及数据口径见 `references/trade-data-reconciliation.md`。结构化交易表可运行
`scripts/validate_trade_records.py` 检查订单、报关、收款和币种字段。

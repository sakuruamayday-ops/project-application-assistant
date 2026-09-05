---
name: trade-and-open-economy-projects
description: 分析货物贸易、服务贸易、跨境电商、境外展会、海外品牌和境外投资项目，核验订单、报关、物流、收汇、平台及币种期间；国内电商和国内展会不适用；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 开放经济项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

宿主若只暴露 `run_code`，`skill`、`read`、`web_search`、校验器等工具均须在其中以 `await tools.<name>(...)` 调用，不得根级调用隐藏工具。先按 `SKILL.md` 或参考文档执行命令。脚本名或命令表示执行入口，不是预读源码许可；首次执行前不得读取 `scripts/**`、`examples/**`、`tests/**`、`*.example.*`、`package.json`，也不得列出技能目录。只有文档命令已经真实失败，且错误仍不足以确定调用契约时，才可定向读取与该失败直接相关的一个源码文件。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
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

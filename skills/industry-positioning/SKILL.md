---
name: industry-positioning
description: 在industry-chain-foundation-matcher给出目录候选后，判断企业主导产品的产业链关键环节和重点领域定位是否有收入、技术、客户、产线及知识产权证据；用于补短板、填空白和国产替代三档决策，不负责自行检索或创造目录分类。
---

# 产业定位


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

宿主若只暴露 `run_code`，`skill`、`read`、`web_search`、校验器等工具均须在其中以 `await tools.<name>(...)` 调用，不得根级调用隐藏工具。先按 `SKILL.md` 或参考文档执行命令；不得为理解用法预读脚本、模板、示例或测试，只有真实命令报错且契约不明确时才读取直接相关源码。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与依赖

本技能是产业定位的判断层，不负责检索目录。凡询问产业链、工业六基、产业基础目录或开展专精特新和小巨人定位，必须先调用 `industry-chain-foundation-matcher` 取得可追溯匹配结果。

凡涉及市场占有率、细分市场排名、补短板、锻长板、填空白或国产替代，必须完整读取 `references/market-boundary-and-substitution-gate.md`。该闸门统一证据方法，不统一项目阈值；不得把一个项目的排名条件复制到其他项目。

当核心创新位于自产自用配方、基材、核心部件、嵌入式软件、算法或关键工艺层，而商业化收入由终端产品形成时，完整读取 `references/cross-project-technical-commercialization-gate.md` 和 `references/automatic-master-matrix-orchestration.md`。同一企业只维护一份技术—产品—收入母矩阵；由 `scripts/technical_product_revenue_matrix.py` 校验并生成项目视图，不要求客户填写 Excel，不把视图生成状态解释为项目达标。

## 双维判断

1. **产品维度**：主导产品是否实际处于候选产业链关键环节，产品功能、材料、工艺、客户和上下游位置是否一致。
2. **企业维度**：企业研发、生产、收入、客户、知识产权和产业化证据是否足以支撑该重点领域定位。

目录命中不等于企业自动符合。重点识别：

- 牵强挂靠：目录名称相似，但产品对象、功能或环节不同。
- 支撑不足：目录匹配合理，但收入、技术、客户或知识产权证据不足。

## 市场边界与四项决策

先对细分市场输出“可复核、边界偏窄但可解释、人为缩窄”结论，再对主导产品、补短板、填空白和国产替代逐项输出“保留、替换、补证后保留”。锻长板单列优势对象、同口径比较指标和产业化证据。替换时给出首选方案和联动章节；补证后保留时列出证据、验证标准和未补证前限制。

判断矩阵见 `references/industry-positioning-assessment.md`。不得创造目录外路径或用企业经营范围代替产品实质。

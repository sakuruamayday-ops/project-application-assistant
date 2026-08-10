---
name: industry-positioning
description: 在industry-chain-foundation-matcher给出目录候选后，判断企业主导产品的产业链关键环节和重点领域定位是否有收入、技术、客户、产线及知识产权证据；用于补短板、填空白和国产替代三档决策，不负责自行检索或创造目录分类。
---

# 产业定位


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "industry-positioning" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与依赖

本技能是产业定位的判断层，不负责检索目录。凡询问产业链、工业六基、产业基础目录或开展专精特新和小巨人定位，必须先调用 `industry-chain-foundation-matcher` 取得可追溯匹配结果。

凡涉及市场占有率、细分市场排名、补短板、锻长板、填空白或国产替代，必须完整读取 `references/market-boundary-and-substitution-gate.md`。该闸门统一证据方法，不统一项目阈值；不得把一个项目的排名条件复制到其他项目。

## 双维判断

1. **产品维度**：主导产品是否实际处于候选产业链关键环节，产品功能、材料、工艺、客户和上下游位置是否一致。
2. **企业维度**：企业研发、生产、收入、客户、知识产权和产业化证据是否足以支撑该重点领域定位。

目录命中不等于企业自动符合。重点识别：

- 牵强挂靠：目录名称相似，但产品对象、功能或环节不同。
- 支撑不足：目录匹配合理，但收入、技术、客户或知识产权证据不足。

## 市场边界与四项决策

先对细分市场输出“可复核、边界偏窄但可解释、人为缩窄”结论，再对主导产品、补短板、填空白和国产替代逐项输出“保留、替换、补证后保留”。锻长板单列优势对象、同口径比较指标和产业化证据。替换时给出首选方案和联动章节；补证后保留时列出证据、验证标准和未补证前限制。

判断矩阵见 `references/industry-positioning-assessment.md`。不得创造目录外路径或用企业经营范围代替产品实质。

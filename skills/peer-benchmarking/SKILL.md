---
name: peer-benchmarking
description: 从政府公示名单和公开资料中建立同项目、同政策版本、同地区、同产品的可比企业事实对标，核验主体和年度口径；不由入选结果推定未公开评分或全部条件；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 同行对标


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "peer-benchmarking" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

从公开名单和公开材料中寻找可比企业，为申报定位提供事实参照，不推断未公开的申请书内容或专家评分。

## 流程

1. 明确目标项目、年度、地区、行业、产品和对标目的。
2. **先检索本地知识库，再进行任何联网检索**：先调用 `local-knowledge-retrieval` 的 `knowledge_service_status`，连接正常后检索已核验的政府公示、认定和复核名单及其原文。
3. 本地知识库未命中、覆盖不足或服务不可用时，按固定降级顺序补充：先用天眼查核验主体、曾用名、登记地区和状态，再用企查查补齐缺失或高影响字段，最后才调用官方网页或联网搜索定位动态名单和原文。第三方资料只能作为主体线索或官方来源定位，不能替代官方认定事实。
4. 锚定企业完整名称，避免集团、子公司和同名主体混淆。
5. 按同项目、同政策版本、同地区、同细分行业、同类产品和相近规模评估可比性。
6. 分开记录公开事实、可计算指标、合理推断和未知项。
7. 入选事实只证明企业在对应年度获得该结果，不自动证明每个评分项均满足或高分。
8. 跨年度比较前核验管理办法、申报范围和评价指标；口径不一致时只作历史背景或趋势参考。

## 输出

输出来源清单、可比性评分、事实对比表、政策口径差异和不可比较项。详细规则见
`references/peer-comparability-rules.md`。

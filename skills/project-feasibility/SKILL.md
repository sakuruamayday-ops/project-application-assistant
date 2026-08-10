---
name: project-feasibility
description: 对单个政府项目执行完整可行性分析，覆盖项目与版本确认、硬门槛、评分映射、证据状态、财务计算复核、不确定性、材料差距和结论生成。用户询问某企业能否申报、申报成功条件、差距、预评分或需要补什么材料时使用。
---

# 可行性分析


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-feasibility" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 强制执行顺序

1. 确认企业主体、项目全称、地区、申报年度、批次以及新申报或复核类型。任一信息可能改变适用规则时，先调用 `policy-retrieval` 取得管理办法、工作指引和当期通知。
2. 读取 `references/feasibility-decision-model.md`，建立规则台账。每条规则标明规则类型、原文、来源、适用范围、时间状态和是否一票否决；不得把历史政策或同类项目规则拼入当期规则。
3. 读取 `references/evidence-state-model.md`，将企业事实逐项映射为“verified、computed、claimed、missing、conflicting、not-applicable”。只有 verified 和复算通过的 computed 可以直接支撑硬门槛。
4. 先判断排除项和硬门槛，再处理评分项。硬门槛出现 `failed` 时结论为不可申报；出现 `missing`、`conflicting` 或关键 `claimed` 时不得给出确定达标结论。
5. 财务门槛先查找 `artifacts/enterprise-financial-facts.v1.json` 或同契约文件，调用 `financial-verification` 核验企业、期间、单位、币种、合并范围和证据。按 `references/calculation-review-rules.md` 展示公式、原始值、单位、结果和复核状态。
6. 将评分细则逐项映射到事实，不以企业入选案例反推评分，不把同一证据重复计入互斥评分项，不将可能得分计入确定得分。政策未公布评分细则时只分析条件和竞争力，不虚构分值。
7. 按 `references/conclusion-contract.md` 生成结论、依据、风险和行动。先给三档结论，再给逐项依据；不承诺获批。

## 结论规则

- `可申报`：所有硬门槛均为 `passed`，不存在一票否决，关键证据已核验；评分项如有，只将确定分计入。
- `有条件申报`：未发现明确硬门槛失败，但存在可在申报前补齐的关键证据、口径冲突或待确认规则。
- `不可申报`：任一适用硬门槛明确失败，或命中当期政策的一票否决项。
- `暂无法判断`：项目版本、政策原文、企业主体或关键数据不足，无法安全落入前三档。此状态不是“有条件申报”。

## 停止与降级

- 同时命中多个政策版本、缺少当期官方通知或政策时效清单标为 `stale` 时，停止形成正式资格结论，先补政策。
- 财务事实属于其他主体、期间不足、口径不一致或质量为 `unverified` 时，停止复用并列出补证要求。
- 只获得企业自述、媒体报道或历史入选名单时，将其作为线索，不升级为硬门槛事实。
- 税务、司法或舆情风险只有在当期政策明确规定为排除项时才转化为资格判断。

## 交付与自检

输出固定包含：项目版本、总体结论、硬门槛矩阵、评分映射、计算复核、证据缺口、不确定性、风险和按截止时间倒排的行动清单。形成结构化结果时运行：

`python3 scripts/validate_feasibility_assessment.py <结果.json>`

校验失败时不得交付确定性结论。

案例包可用于比较材料结构、指标分布和证据类型，但不得把案例值当成政策阈值或当前企业事实。可行性结论仍以当期政策和当前企业证据为准。

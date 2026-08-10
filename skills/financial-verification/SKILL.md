---
name: financial-verification
description: 核验政府项目申报中的营收、利润、研发投入、资产、负债、增长率和专项财务指标。用户提供可靠财务资料后使用。
---

# 财务核验


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "financial-verification" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

只使用用户提供或明确授权的可靠数据。读取 `references/source-and-normalization-rules.md`，先确认主体、年度、币种、单位、合并范围和审计口径，再登记原始值。无可靠数据时不推算企业财务，不用第三方过期数据补造。

## 固定流程

1. 建立来源台账，区分审计报告、财务报表、纳税申报表、专项审计、企业台账和外部线索；外部线索不得覆盖企业原始资料。
2. 统一年度、币种、单位和合并范围。无法无损转换或来源口径冲突时保留并列版本，不静默选值。
3. 按 `references/reconciliation-and-formulas.md` 执行表内、表间和跨年度勾稽；研发费用必须区分财务核算、加计扣除和项目申报口径。
4. 每个计算展示公式、原始值、单位、结果和复核状态。缺少分母、期间不连续或口径不同，不计算比例或增长率。
5. 将结果标为“verified、computed、missing、conflicting、not-applicable”；只有前两类可以传递给资格判断。
6. 输出可复用事实、计算指标、证据、质量状态、冲突和缺口；不输出税务违法或申报资格结论。

## 共享财务事实

读取 `references/financial-facts-contract.md`。发现 `enterprise-financial-facts/v1` 文件时：

1. 运行 `python3 scripts/validate_financial_facts.py <文件> --company <企业名称>`。
2. 校验企业名称或统一社会信用代码、期间、币种、单位、合并范围和来源证据。
3. 只向其他 Skill 传递 `facts`、`metrics`、`evidence` 和 `quality`；不传递税务违法或申报资格结论。
4. 新财务文件与旧事实冲突时，保留两版来源并停止自动覆盖，直至用户确认正确口径。

形成结构化核验结果后运行：

`python3 scripts/validate_financial_assessment.py <结果.json>`

企业不一致、单位缺失、计算无公式、冲突被静默覆盖或指标缺乏来源时，验证必须失败。

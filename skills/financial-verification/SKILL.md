---
name: financial-verification
description: 核验政府项目申报的营收、利润、研发投入、资产、负债、增长率和专项财务指标，以用户提供或明确授权的可靠资料形成可复算结果。
---

# 财务核验

按 `references/source-and-normalization-rules.md` 识别主体、年度、币种、单位、合并范围和审计口径，登记原始值。缺资料时列待取项，继续核验已取得数据。

## 核验方法

1. 来源台账区分审计报告、财务报表、纳税申报、专项审计、企业台账和外部线索，保留各自证据层级。
2. 统一年度、币种、单位和合并范围；口径冲突或转换有损时保留并列版本及差异。
3. 按 `references/reconciliation-and-formulas.md` 做表内、表间和跨年度勾稽，研发费用分别采用核算、加计扣除和申报口径。
4. 展示公式、原始值、单位、结果及复核状态。分母缺失、期间或口径待明时列待算条件，其他指标照常计算。
5. 结果标记 `verified`、`computed`、`missing`、`conflicting`、`not-applicable`；事实与计算传递对应质量状态，资格和税务判断由专业任务结合政策作出。
6. 完整三表解读参考 `references/financial-statement-analysis.md`，阈值及行业基准附来源、年度、样本；基准待取时形成企业自身趋势与结构分析。
7. 资金安全、回款、库存、账期、资本开支和压力情景参考 `references/cash-flow-and-working-capital-review.md`；13 周现金流、现金跑道、现金转换周期采用用户数据或明确假设。

## 共享事实与输出

按 `references/financial-facts-contract.md` 处理 `enterprise-financial-facts/v1`，运行 `python3 scripts/validate_financial_facts.py <文件> --company <企业名称>`，核对主体、期间、币种、单位、合并范围和来源。共享 `facts`、`metrics`、`evidence`、`quality`；新旧冲突保留两版来源和待确认口径。

结构化结果用 `python3 scripts/validate_financial_assessment.py <结果.json>` 检查主体、单位、公式、冲突及来源，交付已核范围、计算和缺口，按真实检查结果修正对应内容。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

企业数据取证参考[来源接续方法](../_runtime/enterprise-source-fallback.md)，复用成功结果，缺口随稿说明。

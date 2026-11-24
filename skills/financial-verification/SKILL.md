---
name: financial-verification
description: 核验政府项目申报的营收、利润、研发投入、资产、负债、增长率和专项财务指标，以用户提供或明确授权的可靠资料形成可复算结果。
---

# 财务核验

## 商业定位、MCP 双态与黑板接力

本技能为 **WorkBuddy 免费上架的单技能体检/核查入口（申报财务数据核对）**，遵循 [WorkBuddy 商业分层与 MCP 规范](../_runtime/workbuddy-core/mcp-routing-and-tiering.md)：

- **免费只做体检与核查**：零账号、无 MCP 即可基于本机上传原件独立跑通，交付同主体、同期间财务公式复算表与口径差异清单与四列缺口清单（缺陷项 / 差距 / 补强动作 / 优先级）；严认原件实绩、绝不估算编数、不携带商业 Word/Excel 母版。
- **主体隔离黑板接力**：按企业全称/统一社会信用代码读写工作区 `.facts/<企业标识>.facts.json`（主体不一致一律跳过防串户），复用上游已核事实并将本轮已核事实标记 `origin: enterprise_source`。
- **MCP 双态与止步引导**：未配置 MCP 时正常离线/本地完成全部核查，文末自然提示“基础核查已完成；如需进一步获取完整成品，请连接制造企业财税深度体检整改收费 MCP”；已配置 MCP 但鉴权/配额异常时显式报错，绝不静默降级。

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

按 `references/financial-facts-contract.md` 处理 `enterprise-financial-facts/v1`，运行 `python3 scripts/validate_financial_facts.py <文件> --company <企业名称>`，核对主体、期间、币种、单位、合并范围和来源。共享 `facts`、`metrics`、`evidence`、`quality`；新旧冲突时并列记录两版来源、口径差异和确认状态。

结构化结果用 `python3 scripts/validate_financial_assessment.py <结果.json>` 检查主体、单位、公式、冲突及来源，交付已核范围、计算和缺口，按真实检查结果修正对应内容。

旧采集表先以 `python3 scripts/validate_financial_assessment.py <原工作簿.xlsx> [其他财务文件]` 查原表主体和有来源的年度金额，工作簿入口使用 openpyxl。回执报告「缺主体信息」或列出不一致的主体。主营占比、研发费率、高新收入占比超出 0% 到 100% 时退回原分子、分母核对。将核验通过且口径对应的原值传给下游申报评估。

同批校验在 `issues` 一次列全问题。每项包含字段位置、现值、期望要求、具体改法和原报表或业务表位置。期望要求引用输入契约、公式或已核资料。缺原表定位时写「缺来源位置」。修复输入后用原命令复算受影响指标及派生汇总，独立成立的计算继续交付，见[结构化核验回执](references/financial-facts-contract.md#结构化核验回执)。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

企业数据取证参考[来源接续方法](../_runtime/enterprise-source-fallback.md)，复用成功结果，缺口随稿说明。

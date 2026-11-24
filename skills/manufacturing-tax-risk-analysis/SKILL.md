---
name: manufacturing-tax-risk-analysis
description: 基于制造企业财务与税务资料，复算三表、分析现金流和财务健康、筛查智慧税务及账票税款货一致性，形成整改建议。完整报告默认深度分析版 PDF，按请求交付同正文 Word；单指标咨询按问题范围处理。
---

# 制造企业财税体检

## 商业定位、MCP 双态与黑板接力

本技能属于 **WorkBuddy 收费深度分析与成品交付能力（制造企业财税体检 · 收费 MCP 服务端 / 付费交付端）**，遵循 [WorkBuddy 商业分层与 MCP 规范](../_runtime/workbuddy-core/mcp-routing-and-tiering.md)：

- **业务范围**：承接制造企业财税深度体检与整改行动报告成品交付；商业报告母版与服务端生成资产留在收费侧，严认原件实绩与可验证数据、绝不虚构财务/司法/实测指标、绝不输出废弃的内部估分，提供四列缺口与可执行整改动作。
- **主体隔离黑板与 MCP 故障显式报错**：按当前企业主体读写 `.facts/<企业标识>.facts.json` 实现组合包无缝接力并杜绝跨企业串户；已配置付费 MCP 若遇鉴权过期、配额归零或超时，显式向用户报错排查，绝不静默降级。

以可复算、可追溯的财务事实支持风险判断，风险信号与违法认定分别表述。完整分析、整改方案和报告按下列方法组织，单点咨询直接核验对应问题。

## 资料与复算

1. 锚定企业、年度、单位及连续性，使用用户提供的合作客户财务资料。登记纳税申报、发票、流水、库存、合同、个税社保和研发辅助账的取得状态。
2. PDF、OCR、联网及排版使用当前宿主能力；扫描关键金额回看原页，保留提取结果和修正记录。三表分析按需采用 `financial-verification`。
3. 提取资产负债表的资金、应收预付其他应收、存货、资产、借款、应付预收、税费、负债与权益；利润表的收入成本、费用、利润、所得税及滞纳金；现金流的收现、采购、薪酬、税费、经营、资本和筹资；附注的税率优惠、账龄、库存、进项、关联、抵押担保和意见。
4. 复算主表合计、期初期末与现金净变动。数据结构见 [data-schema.md](references/data-schema.md)。

客户端可用 `manufacturing-tax-risk-analysis.calculate-metrics`，参数为工作区 `input`、`financialFactsOutput`、`metricsOutput`。专业核验可用一条 `calculated` 证据绑定实际计算回执及展示值。其他宿主运行：

```bash
python3 scripts/calculate_metrics.py input.json artifacts/enterprise-financial-facts.v1.json --metrics-output artifacts/manufacturing-tax-risk-metrics.v1.json
```

共享事实使用 `enterprise-financial-facts/v1`，保留主体、年度、单位、合并范围、原值、指标、证据和质量；指标文件包含收入与应收增速、研发费率、恒等式差额及待算原因。其他技能复用事实及质量状态，资格和税务判断另据专业分析形成。

“支付税费÷收入”称现金税费支付率；行业经验结合订单周期与可比样本使用。单位展示取计算器 `display_values`，便携宿主核对元、万元和百分比换算。

## 风险分析与政策

参考 [risk-gates.md](references/risk-gates.md)，核对预收、收现、开票及收入；库存、采购、领用及成本；往来账龄、对象与用途；关联交易和定价；会计利润、税申报、亏损与优惠；核算、高企、加计扣除三套研发口径；工资个税社保代发；发票红冲税率品名及票货款合同；出口报关收汇退税；滞纳金、逾期及更正。

每项用“事实—计算—风险及替代解释—待取证据—动作”表达，交易级事实待取时写需核验。政策采用税务总局、财政部、政府和属地税务官方原文，参考 [policy-baseline.md](references/policy-baseline.md)、[tax-calculation-and-freshness-protocol.md](references/tax-calculation-and-freshness-protocol.md) 动态核验。

精确文号、日期和链接对应实际取得的官方文本。原文待取时 `policies` 使用空数组，继续生成标注“政策原文未核验”的分析草稿，来源定位按实际年度、科目、文件或页码。网络状态按工具真实返回说明。标题、段落小修沿用原资料和政策状态，数字、画像及其他正文保持对应版本。

“金税四期”按智慧税务、以数治税的通俗称谓使用，经验预警阈值标明来源性质。

## 写作与生成

采用 [report-spec.md](references/report-spec.md)，按经营变化、资产现金流、税务一致性、重点核验和 30/60/90 天动作组织。正文面向读者。

按 [report-input-schema.md](references/report-input-schema.md) 准备分析字段，财务段落参考 [financial-paragraph-templates.md](references/financial-paragraph-templates.md)。金额、比例和周转天数保留具名引用，生成器从计算结果回填，已有输入可局部修订。

```bash
python3 scripts/generate_report_html.py report-data.json --metrics-json metrics.json --prepare-input
python3 scripts/generate_report_html.py report-data.json report.html --metrics-json artifacts/manufacturing-tax-risk-metrics.v1.json
```

运行时使用工作区及脚本实际绝对路径。`completion` 写可核验完成条件。生成器采用深度分析版的金色模板，输出 17 个基础页面区块，来源超过 10 行自动续页；财务总览、风险地图、90 天路线、计算来源四表与必填、长度、主体及占位检查由生成器处理。实际页数取返回 `pages`，错误定向修复，成功结果继续渲染交付。

## 文件与验收

默认 PDF，可按用户请求生成 Word 或两种格式；HTML、指标和共享事实作为任务源文件保留。Word 复用同一 HTML 和资料状态，使用 `evidence-ledger.create-docx-from-file` 的 `input`、新 `output`，再用 `evidence-ledger.apply-office-branding-gold`。其他宿主：

```bash
python3 ../evidence-ledger/scripts/create_docx_from_text.py --input-file /abs/report.html /abs/report.docx

python3 scripts/validate_report.py /abs/report.docx
```

PDF 沿用 `assets/gold-analysis.css` 的深棕黑、香槟金、米金体系。使用当前 Node、Playwright 和 Chromium 渲染：

```bash
node scripts/render_pdf_stdout.js /abs/report.html > /abs/report.pdf
python3 scripts/validate_report.py /abs/report.pdf --expected-pages "$REPORT_PAGES"
```

按生成器返回值核对成品页数、封面、正文、风险矩阵、长表和来源。

生成器的输出位置用 `-` 时从标准输出传入 `node scripts/render_pdf_stdout.js -`，生成回执在标准错误。受限宿主仅允许本地 Chromium 单进程时，可设置 `REPORT_CHROMIUM_SINGLE_PROCESS=1`。

交付说明实际稿件状态、资料缺口与 OCR 不确定性，鉴证及法律结论衔接相应专业审查；归档和模板沉淀按用户要求办理。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

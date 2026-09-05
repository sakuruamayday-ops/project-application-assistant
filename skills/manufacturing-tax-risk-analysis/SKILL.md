---
name: manufacturing-tax-risk-analysis
description: 基于制造企业近三年审计报告、财务报表及税务资料，完成三表复算、财务健康分析、金税四期与智慧税务风险筛查、订单和往来穿透、研发及所得税核验，并生成带金色居中水印的专业顾问版 PDF。用于用户提出制造企业金税四期分析、税务风险体检、审计报告财务分析、账票税款货一致性检查、税务整改方案或同类金色顾问报告时。
---

# 制造企业金税财务体检


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

宿主若只暴露 `run_code`，`skill`、`read`、`web_search`、校验器等工具均须在其中以 `await tools.<name>(...)` 调用，不得根级调用隐藏工具。先按 `SKILL.md` 或参考文档执行命令；不得为理解用法预读脚本、模板、示例或测试，只有真实命令报错且契约不明确时才读取直接相关源码。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

用户只问一个财务指标、税务风险信号或账务现象时，只核验并解释该问题，不自动要求近三年全套资料，也不生成九专题、风险地图、整改路线或顾问报告。以下完整体检流程只在用户明确要求财税体检、完整分析、整改方案或正式报告时执行。

## 目标

把审计报告中的三年财务事实转换为可复算、可追溯的财务与税务风险报告。先判断数据一致性，再讨论税务风险；风险提示不等于违法认定。

## 必须联用的能力

- 读取既有 PDF：使用宿主 PDF 能力。
- 扫描审计报告：使用宿主 OCR 能力，保留 Markdown、结构化结果和原始输出。
- 三表分析：调用 `financial-verification`，按其三表联读、指标复算和现金流规则形成共享财务事实。
- 正式交付：使用宿主 PDF 排版能力与包内金色顾问模板。
- 事实性和政策性断言：执行防幻觉自检。
- 查询现行政策：使用联网检索；后端不可用时改用官方域名限定搜索。

## 工作流

### 1. 锁定资料与期间

1. 确认企业名称、分析年度和审计报告是否连续。
2. 只使用用户提供的合作客户财务数据，不用第三方过期财务数据补造。
3. 记录缺失资料。通常包括纳税申报表、发票明细、银行流水、存货台账、合同履约、个税社保和研发辅助账。
4. 审计报告为扫描件时必须 OCR；关键金额回看原页。

### 2. 提取并复核财务数据

至少提取：

- 资产负债表：货币资金、应收账款、预付款项、其他应收款、存货、流动资产、总资产、短期借款、应付账款、预收账款、应交税费、流动负债、总负债、权益。
- 利润表：收入、成本、税金附加、销售费用、管理费用、研发或研究费用、财务费用、利息、营业利润、利润总额、所得税费用、净利润、滞纳金。
- 现金流量表：销售收现、采购付现、职工薪酬、支付税费、经营现金流、资本开支、筹资现金流。
- 附注：税率及优惠、往来账龄、存货构成、进项税、关联方余额、抵押担保、审计意见。

主表合计、期初期末衔接和现金净变动必须复算。OCR 金额与原页不一致时以原页为准并记录修正。

### 3. 计算指标

按 [数据结构与公式](references/data-schema.md) 准备 JSON，运行：

```bash
python3 scripts/calculate_metrics.py input.json artifacts/enterprise-financial-facts.v1.json \
  --metrics-output artifacts/manufacturing-tax-risk-metrics.v1.json
```

`enterprise-financial-facts.v1.json` 必须使用 `enterprise-financial-facts/v1` 共享事实契约，保留企业身份、年度、单位、合并口径、原始数值、计算指标、证据页和质量状态。`manufacturing-tax-risk-metrics.v1.json` 由同一确定性计算器生成，固定包含跨年收入与应收增速、研发费用率、资产负债表恒等式差额，以及缺少输入时无法计算的指标和原因。不得手工重写这两份计算结果。共享事实文件可供 `financial-verification`、`project-feasibility`、专精特新体检和其他申报技能复用，但不把税务风险判断自动传递为项目资格结论。

禁止把现金流量表“支付的税费 ÷ 收入”称为增值税税负率；统一称“现金税费支付率”。制造业经验基准只作提示，不能代替企业订单周期和行业对标。

### 4. 执行风险闸门

读取 [风险判断与证据闸门](references/risk-gates.md)。至少检查：

1. 预收款、销售收现、开票和收入确认。
2. 存货、采购进项、生产领用和成本结转。
3. 应收账款与其他应收款账龄、对象和资金用途。
4. 关联交易真实性、定价和资金闭环。
5. 会计利润、所得税申报、亏损弥补和优惠扣除。
6. 会计研发、高企研发、加计扣除研发三套口径。
7. 工资、个税、社保和银行代发一致性。
8. 发票作废红冲、税率、品名、票货款合同一致性。
9. 出口收入、报关、收汇、退税和进项分配。
10. 滞纳金、逾期申报和历史更正。

对每项输出“事实—计算—风险解释—替代解释—缺失证据—动作”。没有交易级证据时写“需核验”，不得写“存在偷税、虚开或股东借款”。

### 5. 核验政策

每次任务重新核验现行官方来源。优先国家税务总局政策法规库、财政部、政府门户和企业所在地税务局。参考 [政策基线](references/policy-baseline.md)，但不得假定其中状态永久有效。

涉及具体税种、税率、优惠、计税依据或申报期限时，同时读取 [税种计算与政策时效协议](references/tax-calculation-and-freshness-protocol.md)。不得把外部通用税务技能中的历史税率、优惠期限、截止日或处罚金额复制为正式常量。

“金税四期”作为智慧税务和以数治税的通俗称谓。课件中的百分比阈值、预警描述和案例仅作内部筛查，不写成全国统一法定标准。

### 6. 撰写报告

采用 [报告结构与视觉规范](references/report-spec.md)。默认结论顺序：

1. 经营改善或恶化。
2. 资产质量和现金流。
3. 税务数据一致性。
4. 高优先核验事项。
5. 30天、60天、90天整改路线。

关键数字必须给来源页码和计算公式。报告封面固定列示“完成人：共创知识产权”。

按 [自动报告输入规范](references/report-input-schema.md) 准备 `report-data.json`，可参考
[完整示例](references/report-data.example.json)，然后运行：

```bash
python3 scripts/generate_report_html.py report-data.json report.html \
  --metrics-json artifacts/manufacturing-tax-risk-metrics.v1.json
```

生成器必须读取确定性指标文件，输出17个固定页面区块，并完成必填字段、字段长度、报告主体一致性和未解析占位符检查。财务总览、风险地图、90天整改路线、计算过程与来源四张表由生成器固定输出；跨年增速、研发费用率、资产负债表恒等式差额和无法计算原因直接来自指标文件，不能由模型省略或改写。
不得用模型临时拼接的普通HTML替代该生成器。

### 7. 生成金色顾问版 PDF

1. 固定使用 `assets/gold-advisor.css` 与包内17页生成器。正文必须贯彻深棕黑、香槟金、米金三层体系，不得只制作金色封面后沿用蓝绿正文。
2. 确认宿主环境已提供 Node.js、Playwright、Chromium和PyMuPDF；依赖版本见 `package.json` 与共享品牌运行时的 `requirements.txt`。
3. 以内存管道生成无水印 PDF，再调用同一技能包内 `skills/_runtime/gongchuang-branding` 共享运行时进行金色品牌双遍处理：

```bash
node scripts/render_pdf_stdout.js /abs/report.html \
  | python3 scripts/brand_gold_pdf.py /abs/report.pdf --audit-json /abs/brand-audit.json
```

4. 禁止把无水印底稿写入交付目录。

### 8. 交付闸门

从当前 Skill 目录执行共享交付闸门：

```bash
python3 ../_runtime/gongchuang-branding/scripts/delivery_gate.py \
  /abs/report.pdf \
  --expected-pages 17 \
  --expected-author 共创知识产权 \
  --expected-title-contains 金税四期
```

闸门必须确认恰有17页、作者元数据正确、每页恰有一个居中金色水印且全文尺寸一致。
随后渲染全部页面为图片，抽查封面、普通正文、风险矩阵、最长表格和来源页，确认无裁切、重叠、空白页、乱码和表格断裂。

## 交付要求

- 交付 PDF、可编辑 HTML、指标 JSON 和 `enterprise-financial-facts/v1` 共享事实文件。
- 说明数据缺口和 OCR 不确定性。
- 不承诺不存在其他税务风险，不替代税务鉴证或法律意见。
- 任务结束询问是否归档报告，并询问是否把本次结构继续沉淀为行业模板。

---
name: manufacturing-tax-risk-analysis
description: 基于制造企业近三年审计报告、财务报表及税务资料，完成三表复算、财务健康分析、金税四期与智慧税务风险筛查、订单和往来穿透、研发及所得税核验，并生成带金色居中水印的专业顾问版 PDF。用于用户提出制造企业金税四期分析、税务风险体检、审计报告财务分析、账票税款货一致性检查、税务整改方案或同类金色顾问报告时。
---

# 制造企业金税财务体检


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "manufacturing-tax-risk-analysis" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 目标

把审计报告中的三年财务事实转换为可复算、可追溯的财务与税务风险报告。先判断数据一致性，再讨论税务风险；风险提示不等于违法认定。

## 必须联用的能力

- 读取既有 PDF：使用宿主 PDF 能力。
- 扫描审计报告：使用宿主 OCR 能力，保留 Markdown、结构化结果和原始输出。
- 三表分析：使用财务报表分析技能。
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
python3 scripts/calculate_metrics.py input.json output.json
```

`output.json` 必须使用 `enterprise-financial-facts/v1` 共享事实契约，保留企业身份、年度、单位、合并口径、原始数值、计算指标、证据页和质量状态。默认同时保存为任务工作区的 `artifacts/enterprise-financial-facts.v1.json`，供 `financial-verification`、`project-feasibility`、专精特新体检和其他申报技能复用。共享文件只传递数据与可复算指标，不把税务风险判断自动传递为项目资格结论。

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
python3 scripts/generate_report_html.py report-data.json report.html
```

生成器必须输出17个固定页面区块并完成必填字段、字段长度和未解析占位符检查。
不得用模型临时拼接的普通HTML替代该生成器。

### 7. 生成金色顾问版 PDF

1. 固定使用 `assets/gold-advisor.css` 与包内17页生成器。正文必须贯彻深棕黑、香槟金、米金三层体系，不得只制作金色封面后沿用蓝绿正文。
2. 确认宿主环境已提供 Node.js、Playwright、Chromium和PyMuPDF；依赖版本见 `package.json` 与共享品牌运行时的 `requirements.txt`。
3. 以内存管道生成无水印 PDF，再调用同一技能包内 `skills/_runtime/jiaotang-branding` 共享运行时进行金色品牌双遍处理：

```bash
node scripts/render_pdf_stdout.js /abs/report.html \
  | python3 scripts/brand_gold_pdf.py /abs/report.pdf --audit-json /abs/brand-audit.json
```

4. 禁止把无水印底稿写入交付目录。

### 8. 交付闸门

从当前 Skill 目录执行共享交付闸门：

```bash
python3 ../_runtime/jiaotang-branding/scripts/delivery_gate.py \
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

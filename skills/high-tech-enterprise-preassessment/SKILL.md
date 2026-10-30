---
name: high-tech-enterprise-preassessment
description: 评估高企资格、评分与申报年度，分析目标分、保守分、压力分，核验知识产权、转化滚动窗口、组织管理和成长性，形成双年度比较、补强计划或预评估采集表。
---

# 高新技术企业预评估

资格条件、评分及年度建议分别判断，企业输入作为本轮事实并核对矛盾、计算及时间线。政策、截止、属地材料和权利使用规则对应当期国家、地方及系统要求。官方合格线为综合得分超过 70 分；75 分为内部缓冲线。把握按证据、分数余量和同地区结果样本判断，缺校准样本时用高、中、低及敏感变量表达。

## 口径与输入

记录地区、拟报年度、截止、首次或重新认定、曾未通过、三个会计年度、审定或预测状态、IP 取得方式、有效性、共有及使用情况。缺项可分情景，说明假设后继续比较。

需要采集表时复制 [高企预评估双年度采集表.xlsx](assets/高企预评估双年度采集表.xlsx) 到新路径，保留九张表及公式，逐年度填写人员、财务和质量状态。客户端画像 `high-tech-preassessment-workbook`，报告与工作簿分别验收。

营业收入、销售收入、总收入、净利润、利润总额分别取对应资料；缺总收入时保留输入空值及高品占比条件待核，可另算占营业收入比作经营参考。报告结论、已通过数量与工作簿使用同一状态。

## 资格条件

参考 [policy-baseline.md](references/policy-baseline.md) 核验现行依据。逐项检查注册年限、领域、核心 IP 所有权、科技人员、研发占比、境内研发、高品收入、创新评价和重大事故违法事项。成长性零分与资格条件分别判断；条件存在差距时给整改或培育路径，待核项保留未知。

## 成长性与评分计算

本年与次年采用 `scripts/compare_scenarios.py`，客户端可用 `high-tech-enterprise-preassessment.calculate-scenarios`，参数 `input` 为工作区 JSON。两个年度各一个 `scenarios` 元素，财务数组由早至晚；示例用于字段结构，具体值取企业资料及评分依据：

```json
{"scenarios":[{"name":"本年度","revenue":[100,110,121],"net_assets":[100,105,110.25],"scores":{"ip":{"target":25,"conservative":22,"stress":19},"conversion":{"target":20,"conservative":18,"stress":15},"organization":{"target":15,"conservative":12,"stress":10}}}]}
```

一次输入两个年度，按返回诊断修正。计算证据可记 `kind: calculated`、`status: calculated`、`source: high-tech-enterprise-preassessment.calculate-scenarios`、`values: []` 并由宿主绑定真实操作回执。正文成长性、`nonfinancial_scores`、`totals` 和内部建议区间统一取操作结果；非财务评分另附专业依据。

十进制精确计算后分档，最后舍入显示值。负分母、合并或报表口径变化、数据冲突列财务专项复核。资格有效期按证书三年口径，2026 认定的正常到期重新认定为 2029，监督检查另记事件。

按 [scoring-evidence-rubric.md](references/scoring-evidence-rubric.md) 形成目标、保守、压力三档，每项附“评分档—事实—证据—缺口”。专利数量、先进性、核心支持和转化质量分别评估。子项相加为维度，维度相加为总分，同一项目标 ≥ 保守 ≥ 压力。

子项可用 `scores.ip.components`、`scores.organization.components`，各项填 `target`、`conservative`、`stress`，程序汇总。例如 `[{"target":8,"conservative":5,"stress":4},{"target":8,"conservative":8,"stress":7},{"target":8,"conservative":7,"stress":6},{"target":6,"conservative":4,"stress":3}]` 合计 30、24、20，实际评分按企业依据确定。

研发部门、设备与合作按真实记录评价；政府研发机构称号与企业组织能力分别列示。未来制度、奖励和人员等预测标记情景；领域待核及其他未知项保持对应状态。

## 双年度与补强

按 [timing-and-remediation.md](references/timing-and-remediation.md) 同时计算新增财务、转化、已授权 IP，以及退出窗口的旧年度贡献；比较 II 类使用、截止前授权、提前认定机会及关键假设。

补强分为已发生事实的证据补齐和未来实际执行的新事实。制度、合同、转化、IP 及执行记录对应真实日期与状态，同一成果按实质计数。滚动窗口将已完成与预测分列：2024、2025 各完成 3 项、2026 预测 3 项时，确认 6 项、预测情景 9 项；年度数量按年度汇总，RD、PS、IP 分配待明确时另列缺口。

现有保守分不足时说明“按现有材料暂不建议申报”，分别测算补证和新事实的提升空间。依据 [rd-super-deduction-strengthening.md](references/rd-super-deduction-strengthening.md) 核对立项、人员设备、工时领料、小中试、变更结题、专利、月分配、辅助账和明细账，与高企 RD、专项审计及纳税口径衔接；缺资料标“待企业确认，建议补强”。

## 结论与报告

呈现资格状态、本年三档分数、次年预测及假设、滚动窗口净变化、年度建议、按收益和时限排序的动作，以及敏感变量。

内部建议：保守分 ≥75 且条件通过可建议本年；71—74 结合截止前真实补证余量；≤70 比较次年净改善；压力分明显低于 71 提示争议。每项建议同时展示现有依据和成立条件。

前期评估与可行性参考 `project-feasibility/references/two-report-contract.md`，前者保留关键年度决策条件，后者展开资格、四维评分、双年度窗口、加计扣除与动作。使用 Word 母版时按 `table_content`、`core_associations` 填已有事实及全部 RD、技术、专利、成果、收入关系。已提供制度和有效权利沿用输入状态，证明缺口另列。

## 权利和事实口径

申请、授权及有效权利分别记载。II 类在未通过申请中的使用记录与通过认定中的使用次数分别核验；I、II 类、共有及其他规则对应当期指引与属地口径。制度文本与执行记录分列，财务采用用户资料、审计、纳税申报和标明的预测，地方实践和内部缓冲线标明来源性质。

```bash
python3 scripts/compare_scenarios.py input.json
```

脚本负责确定性计算，资格、证据与政策有效性由对应分析给出。报告表达采用[报告写作规则](../_runtime/report-writing.md)。

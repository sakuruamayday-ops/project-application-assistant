---
name: industrialization-projects
description: 评估首台套、首批次、首版次和工业新产品的申报方向、条件与成熟度，结合产品、政策和现有证据提出首选及备选路径。
---

# 产业化项目

## 分类与核验

1. 识别产品、地区、年度及批次，按申报对象和政策定义分类。项目名称待明时可衔接 `project-matching`。
2. 按 `references/project-type-decision-tree.md`，装备及关键部件核验首台套，新材料核验首批次，独立工业软件核验首版次，鉴定、验收或备案成果核验工业新产品；扩产、复购和纯研发分别对应投资或研发路径。
3. 装备、材料、软件组合按合同、收入、核心创新载体及政策定义选主项目，其他方向列备选；同一合同的应用事实统一记录。
4. 按 `references/maturity-evidence-matrix.md` 核验技术成熟、创新、IP、检测鉴定、用户应用、合同发票和产业化能力，分别标记样机、送检、试用、首单、销售及批量应用。
5. 浙江首批次新材料使用对应年度申报通知和《浙江省重点新材料首批次应用示范指导目录》核验范围、性能及应用；企业公示、认定和奖励另取记录。
6. 政策、分类或成熟度缺项时继续形成候选、技术建议和补证清单，政策条件保持待核。权利人、状态、RD 和产品关联逐字段沿用输入，明确已知与待核部分。

输出主备项目、依据、阶段、七类证据状态、风险与下一步。结构化结果可用 `python3 scripts/validate_industrialization_assessment.py <结果.json>`。

## 报告

前期评估及可行性参考 `project-feasibility/references/two-report-contract.md`，按对象、目录、创新、成熟、检测查新、首次应用、IP 和产业化给出建议层级。研发机构、检测及认定等资料待取时标明范围，建设周期按企业实际任务估算。

研发机构培育衔接 `technology-innovation-projects`；杭州平台参考其 `references/current-rd-platform-baseline-2026.md`，区分准备依据、征求意见稿与历史正式文件。已销售产品及拟开展 RD 分别按真实状态组织。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

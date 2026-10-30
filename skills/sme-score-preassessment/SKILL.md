---
name: sme-score-preassessment
description: 按 2026 适用规则评估专精特新中小企业与小巨人申报条件、平台质量分和企业差距，形成产品、专利、财务及培育路径建议。
---

# 专精特新申报前预评估

按现有资料直接判断并形成行动报告，规则采用 2026 办法及适用通知，质量分使用真实平台记录。客户报告围绕条件、企业值、产品、专利和行动；质量分原文、技术元数据及内部核验保留在工作底稿。省级报告按目标条件组织，小巨人对应项目核对省级专精特新身份。

## 政策与接口

参考 [current-policy-baseline-2026.md](references/current-policy-baseline-2026.md)，记录层级、新报或复核、地区、年度与版本。2026 新报的政策质量分要求为省级 50、小巨人 60；2026 小巨人复核过渡分支对应当期指定对象和期间。历史评分模型作为历史资料，当前结论按适用政策和企业事实形成。

客户端可用 `sme-score-preassessment.run-preflight`，参数 `{"taskType":"quality-preassessment","projectLevel":"省级专精特新中小企业","applicationType":"新申报"}`，其他项目类型按工具清单值填写；其他宿主：

```bash
python3 <本技能目录>/scripts/preflight.py --task-type quality-preassessment --project-level "省级专精特新中小企业" --application-type "新申报"
```

`schema_version`、`policy_version`、`rule_branch`、`rule_id` 留在机器记录，实际政策名称、文号、年度及申请类型用于业务说明。计算回执按真实操作 ID 绑定。

## 事实与判断

1. 企业身份、资质、IP 和荣誉使用当前工具与材料核验，未命中说明本轮范围。财务、经营、研发、人员、产品、客户、产能和份额取用户资料及明确陈述，按原口径计算。
2. 每个条件记规则、企业值、证据状态和结论，分已核、自述、计算、冲突及待补；主导产品、补短板、填空白和替代可依据自述判断，结合边界、因果、环节及跨章一致性评价。
3. 平台分采用 `{"status":"verified-platform-score","value":58,"source":"平台记录"}`，待取时 `{"status":"pending-platform-evaluation","value":null}`。当前判断说明关键未知与成立条件。
4. 单元状态用“已具备、存在差距、待补强、待定、冲突待核、不适用”：未提供且未核的字段待定，已检索核对但未取得的资料待补强，保留业务现状与证据状态差别。

## 报告方法

采用 [pre-sale-assessment-report-contract.md](references/pre-sale-assessment-report-contract.md)、[policy-application-path-contract.md](references/policy-application-path-contract.md)，客户报告沿 `sme-development-projects/references/material-checkup-report-template.md` 五章 19 内容块，主导产品和专利分别成章，按内容自然分页。

- 开头给总体成熟度、主导产品首选及备选、近年申报路线和关键提升。
- 相关项目在后台形成完整池，前台用一张表列项目、建议年度、已核核心条件、企业值、差距和下一步，覆盖有业务关联的研发、绿色、数字化、IP 及质量品牌。
- 产品根据合同交付物、收入、技术、专利和可比同行确定最小充分单元，提出具体名称及调整建议。同产品已认定同行待取时说明范围。
- 专利写现有支撑、缺口、布局技术簇、节奏与项目作用，合作发明状态按输入填写；拟布局主题与已形成权利分列。
- 财务写已知趋势与可复算营收、增长、研发强度、主营占比、负债、利润及人员口径，公式与来源对应，缺项集中成短清单。
- 数字化诊断参考 `references/digital-transformation-diagnostic-strengthening.md`，写五维、对标、优势短板和两年提升任务；原报告待取时列“待企业确认，建议补强”。

客户正文呈现事实、判断和行动，详细方向利弊、十二字段路径底稿、内部责任表及评分记录存工作底稿，按用户深度要求展开。已有申请书核稿衔接 `sme-development-projects`；合作后可行性展开实际条件、证据、动作、完成标准和年度节点。

内容或文件生成后交付，缺项集中列一次。报告表达采用[报告写作规则](../_runtime/report-writing.md)。

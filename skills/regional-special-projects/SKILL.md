---
name: regional-special-projects
description: 将市、区县、园区临时通知和新项目转换为带原文位置的候选规则，形成可行性输入；政策版本、效力和文件链核验优先使用 policy-retrieval。
---

# 区域特色项目

## 方法

1. 使用 `policy-retrieval` 及当前资料取得通知、附件、更正和延期。
2. 提取地域、机关、主体、行业、条件、排除情形、评分、材料、流程、截止及奖补。
3. 各规则附原文位置、来源等级和核验状态，新闻转载摘要作为线索，未知字段标待核。
4. `scripts/validate_candidate_rule.py` 检查结构；与原文核对后按实际状态提供给 `project-feasibility`。
5. 附件缺项列文件名和影响字段，同名跨地区及跨年度分别核验。

结构见 `references/regional-rule-schema.md`。沿用通用规则模型，按当前可得资料形成候选、分析稿与待取清单。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

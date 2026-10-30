---
name: industry-positioning
description: 结合目录候选和企业产品、收入、技术、客户、产线、知识产权证据，判断产业链关键环节与重点领域定位，形成主导产品、补短板、填空白和国产替代建议。
---

# 产业定位

目录候选由 `industry-chain-foundation-matcher` 提供，定位按产品实质及证据判断。市场份额、排名、补短板、锻长板、填空白和替代参考 `references/market-boundary-and-substitution-gate.md`，各项目使用自身政策阈值。

## 判断方法

1. 产品维度核对对象、功能、材料、工艺、客户和上下游环节。
2. 企业维度核对研发、生产、收入、客户、IP 与产业化。
3. 分别识别名称相似而功能环节不同的牵强挂靠，以及分类合理而支撑待补的情况。
4. 市场边界给出“可复核、边界偏窄但可解释、人为缩窄”，主导产品、补短板、填空白和国产替代分别给“保留、替换、补证后保留”。替换列首选和联动章节，补证列证据、标准及成立条件；锻长板列优势对象、同口径指标和产业化依据。

创新位于自产自用配方、基材、部件、嵌入式软件、算法或工艺层时，参考 `references/cross-project-technical-commercialization-gate.md`、`references/automatic-master-matrix-orchestration.md`，由现有资料整理一份技术—产品—收入母矩阵，使用 `scripts/technical_product_revenue_matrix.py` 生成项目视图；矩阵状态与资格判断分别说明。

输出见 `references/industry-positioning-assessment.md`，按已有可追溯路径、已知事实和资料缺口形成当前判断。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

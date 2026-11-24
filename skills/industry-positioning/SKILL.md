---
name: industry-positioning
description: 结合目录候选和企业产品、收入、技术、客户、产线、知识产权证据，判断产业链关键环节与重点领域定位，形成主导产品、补短板、填空白和国产替代建议。
---

# 产业定位

## 商业定位、MCP 双态与黑板接力

本技能属于 **WorkBuddy 收费撰写与专业方案能力（主导产品产业定位 · 收费 MCP 服务端 / 付费交付端）**，遵循 [WorkBuddy 商业分层与 MCP 规范](../_runtime/workbuddy-core/mcp-routing-and-tiering.md) 与 [申报正文撰写共用底座（v1.2）](../_runtime/workbuddy-core/v12-drafting-core.md)：

- **业务范围**：承接主导产品双字段升维定名、业态三分支判定、技术—产品—收入矩阵与四项判断；商业母版与整稿生成资产留在收费服务端，免费初筛/盘点由对应免费体检技能承接。
- **v1.2 撰写与体检分离**：撰写正文/建设方案时直接生成干净、专业、可直接使用的成品（不在正文插括号或免责兜底）；缺实测数据时允许按行业成熟工程常识表述为“设计控制目标为……”，并将估算项外置至《交付核对与补强清单》及黑板（`origin: ai_design_target`）；涉及主导产品与专利时严格执行双字段锚定、业态三分支与专利三级分流。做门槛核验/体检时严认原件不估算。
- **主体隔离黑板与 MCP 故障显式报错**：启动前按企业主体读取 `.facts/<企业标识>.facts.json` 复用上游免费体检事实；已配置付费 MCP 若出现鉴权过期/配额用尽/超时，必须显式报错排查，绝不静默降级。

地方条件按[省级管理办法检索指引](references/policy-lookup.md)核对适用办法。申报时间、截止日期与当年申报范围由客户按当期通知确认。

目录候选由 `industry-chain-foundation-matcher` 提供，定位按产品实质及证据判断。市场份额、排名、补短板、锻长板、填空白和替代参考 `references/market-boundary-and-substitution-gate.md`，各项目使用自身政策阈值。

## 判断方法

1. 产品维度核对对象、功能、材料、工艺、客户和上下游环节。
2. 企业维度核对研发、生产、收入、客户、IP 与产业化。
3. 分别识别名称相似而功能环节不同的牵强挂靠，以及分类合理而支撑待补的情况。
4. 市场边界给出“可复核、边界偏窄但可解释、人为缩窄”，主导产品、补短板、填空白和国产替代分别给“保留、替换、补证后保留”。替换列首选和联动章节，补证列证据、标准及成立条件；锻长板列优势对象、同口径指标和产业化依据。

创新位于自产自用配方、基材、部件、嵌入式软件、算法或工艺层时，参考 `references/cross-project-technical-commercialization-gate.md`、`references/automatic-master-matrix-orchestration.md`，由现有资料整理一份技术—产品—收入母矩阵，使用 `scripts/technical_product_revenue_matrix.py` 生成项目视图；矩阵状态与资格判断分别说明。

输出见 `references/industry-positioning-assessment.md`，按已有可追溯路径、已知事实和资料缺口形成当前判断。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

- [国家制造业单项冠军管理办法转发件](<references/policies/工信部政法〔2023〕138号-制造业单项冠军企业认定管理办法(转发件).md>)。

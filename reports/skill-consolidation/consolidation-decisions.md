# 正式技能整合决策

基线：V1.6.3.1，49 项正式技能。目标候选：V1.6.4，50 项正式技能。

| 本地或外部技能 | 处理结论 | 正式归属 | 说明 |
|---|---|---|---|
| jiaotang-humanizer-zh | 改用公共正式名后新增 | gongchuang-humanizer-zh | 具备独立触发、事实锁、差异审计和受控进化边界；旧名受公共命名门禁阻断，本地保留兼容映射 |
| artifact-template-gb-t-1-1 | 合并后退役 | standard-drafting | 正式技能已有脱敏通用模板与审计流程，不引入旧客户模板 |
| artifact-template-sme | 合并后退役 | sme-development-projects | 使用包内方向卡模板，移除个人模板依赖 |
| artifact-template-v1-3-1 | 合并后退役 | high-tech-enterprise-application-drafting | 使用包内高企空白母版，移除个人模板依赖 |
| enterprise-checkup | 合并后退役 | enterprise-profile + project-matching + project-feasibility | 保留主体画像、项目匹配和差距分析的分阶段交接，不保留商业平台固定调用清单 |
| expert-dual-assessment | 合并后退役 | industry-positioning | 吸收技术载体、终端产品、商业化母矩阵和多项目视图生成器 |
| financial-statement-analysis-zh | 合并后退役 | financial-verification | 吸收三表联读、指标体系、趋势和风险信号；删除无来源固定健康阈值 |
| jiaotang-branding | 合并后退役 | _runtime/gongchuang-branding | 作为共享运行时，不新增业务技能入口 |
| patent-layout-planner | 合并后退役 | patent-router | 吸收项目导向专利组合、节奏和一页式交底卡 |
| project-quick-reference | 不保留独立技能 | project-task-router + 各领域项目技能 | 静态条件容易过期，只保留项目分类和现行政策核验规则 |
| sme-checkup | 合并后退役 | sme-development-projects | 仅吸收通用门禁和方法；客户报告、缓存和旧评分规则不入包 |
| srxgj-qa | 合并后退役 | sme-development-projects + patent-router + application-writing | 吸收方向卡到六问的单方向一致性规则 |
| china-tax-compliance | 合并后退役 | manufacturing-tax-risk-analysis | 只吸收税种识别、计算输入和政策时效协议，不固化税率、优惠和截止日 |
| charlie | 合并后退役 | financial-verification | 只吸收现金跑道、13周现金流、现金转换周期和情景压力测试；不吸收SaaS或美元基准 |
| arxiv | 明确排除 | 无 | 不进入正式包 |
| bigquery-patent-search | 明确排除 | 无 | 不进入正式包 |
| dogfood | 明确排除 | 无 | 不进入正式包 |

本候选不删除本机旧技能，不推送、不发布、不部署；待正式包通过门禁并获批发布后，再做可恢复退役。

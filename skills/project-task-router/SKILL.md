---
name: project-task-router
description: 识别政府项目、企业、知识产权、财税法律及标准任务阶段，按自然语言目标选择专业技能和必要协作。
---

# 任务路由

作为 `project-application-assistant` 的阶段选择能力，明确任务直接使用专业技能，复杂任务按真实依赖组合。范围与完成条件参考[共享任务说明](../_runtime/task-execution.md)，主体资料由当前材料、企业接口和官方来源补齐并标状态。

## 路由表

| 目标 | 主能力 |
|---|---|
| 政策版本、效力、文件链 | `policy-retrieval` |
| 企业画像 | `enterprise-profile` |
| 多项目方向、年度路线 | `project-matching` |
| 项目可行性、前期或双报告 | `project-feasibility` 结合领域技能 |
| 获评名单、产品行业反查 | `local-knowledge-retrieval` 的 `recognition_search` |
| 浙江三首目录变化、企业产品匹配 | 同一知识连接的 `three_first_analysis` |
| 高企年度、成长性及预评分 | `high-tech-enterprise-preassessment` |
| 高企申请书、RD/PS 回填核稿 | `high-tech-enterprise-application-drafting` |
| 专精或小巨人前期评估 | `sme-score-preassessment` |
| 已成申请书体检 | `sme-development-projects` |
| 正文、单份检查、多版比较 | `application-writing`、`consistency-check`、`application-version-diff` |
| 产业目录、企业定位 | `industry-chain-foundation-matcher`、`industry-positioning` |
| 权利事实、专利专项、Word 核稿 | `ip-assessment`、`patent-router`、`checking-patdocx-cn-single-agent` |
| 财务核验、制造财税体检 | `financial-verification`、`manufacturing-tax-risk-analysis` |
| 标准草案、编制说明及审查 | `standard-drafting` |
| 动态网页、后台、表单及采集 | `web-task-operator` |

领域对应见 `references/domain-routing-matrix.md`。企业来源使用[企业数据源说明](../_runtime/enterprise-source-fallback.md)，名单参考[名单来源说明](../_runtime/recognition-source-routing.md)。共享财务事实核验主体、期间及口径后复用。

报告前期突出核心判断与补强，可行性展开条件、评分、证据、动作和验收；各任务保留对应完成状态，按当前可用资料持续交付。政策待核、部分来源、名单覆盖及企业字段缺项在对应结果中如实说明。

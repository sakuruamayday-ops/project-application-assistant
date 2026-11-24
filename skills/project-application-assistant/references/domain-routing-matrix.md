# 领域路由矩阵

这张表是「意图 → 技能」的唯一权威映射。总入口 `project-application-assistant` 负责阶段划分和交接，`project-task-router` 负责识别任务阶段及依赖。

| 用户意图 | 首选入口 | 区分条件 |
|---|---|---|
| 政策版本、效力、文件链 | `policy-retrieval` | |
| 企业画像 | `enterprise-profile` | |
| 多项目方向、年度路线 | `project-matching` | |
| 项目可行性、前期或双报告 | `project-feasibility` 结合领域技能 | |
| 获评名单、产品行业反查 | `local-knowledge-retrieval` 的 `recognition_search` | |
| 浙江三首目录变化、企业产品匹配 | 同一知识连接的 `three_first_analysis` | |
| 高企整本书 / 整份申请书 | `high-tech-enterprise-application-drafting` | 整本撰写、按 Word 母版回填、整本核稿或体检走此入口。高企 RD/PS 表回填、扩缩及核稿也走此入口。仅撰写单个正文栏目且交付正文片段走 `application-writing`。申报前的资格、年度和缺陷诊断走 `high-tech-enterprise-preassessment`。 |
| 高新技术企业申报前评估、双年度数据、成长性和创新能力 | `high-tech-enterprise-preassessment` | 逐项核对要求、企业现状、差距及补强顺序。普通科技项目匹配走 `technology-innovation-projects`。进入整本申请书撰写、回填或核稿时，按上行交接。 |
| 专精特新或小巨人申报前评估、资格和补强 | sme-score-preassessment | 核对政策硬门槛及平台正式评价状态，列实际差距。已形成申请书的后期体检转 sme-development-projects。 |
| 已形成的专精特新或小巨人申请书体检 | `sme-development-projects` | |
| 申报正文、单栏目撰写 | `application-writing` | 高企仅交付指定栏目的正文片段时走此入口。涉及高企申请书模板、表格回填或整本核稿时，按整本申请书行分派。 |
| 单份申报材料一致性检查 | `consistency-check` | 专用申请书体检按对应入口分派。 |
| 多版申报材料比较 | `application-version-diff` | |
| 产业目录、企业定位 | `industry-chain-foundation-matcher`、`industry-positioning` | |
| 权利事实、专利专项、Word 核稿 | `ip-assessment`、`patent-router`、`checking-patdocx-cn-single-agent` | |
| 财务核验、制造财税体检 | `financial-verification`、`manufacturing-tax-risk-analysis` | |
| 标准草案、编制说明及审查 | `standard-drafting` | |
| 动态网页、后台、表单及采集 | `web-task-operator` | |
| 农业基地、农产品、联农带农 | [agriculture-and-rural-projects](../../agriculture-and-rural-projects/SKILL.md) | 纯食品制造转industrialization-projects |
| 制造设备联网、系统集成、智能工厂 | digitalization-projects | 纯软件研发转technology-innovation-projects |
| 节能、绿色工厂、清洁生产 | green-development-projects | 单纯环保处罚查询转企业风险能力 |
| 知识产权类政府项目 | [intellectual-property-projects](../../intellectual-property-projects/SKILL.md) | 权利事实核验转ip-assessment |
| 设备投资、技改补助 | investment-subsidy-projects | 研发任务转technology-innovation-projects |
| 制造精品、质量奖、冠军、品牌 | [quality-brand-projects](../../quality-brand-projects/SKILL.md) | 知识产权品牌专项转intellectual-property-projects |
| 区县或园区管理办法、客户专项材料 | [regional-special-projects](../../regional-special-projects/SKILL.md) | 已有固定领域模型时使用对应领域技能 |
| 人才、团队、博士后 | [talent-projects](../../talent-projects/SKILL.md) | 普通企业研发团队转technology-innovation-projects |
| 研发机构、科技计划、奖励 | technology-innovation-projects | 产品认定或示范应用转industrialization-projects；设备、产线和固定资产投资转investment-subsidy-projects |
| 外贸、跨境、服务贸易、境外业务 | [trade-and-open-economy-projects](../../trade-and-open-economy-projects/SKILL.md) | 国内电商不适用 |
| 去AI味、降低机器腔、中文自然化润色 | gongchuang-humanizer-zh | 资格判断转project-feasibility；正式正文尚未成稿时先转application-writing |

多项目和续问先沿[共享任务说明](../../_runtime/task-execution.md)确定主流程，再分配子项，复用已完成步骤。

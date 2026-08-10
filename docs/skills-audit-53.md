# 53个Skills重叠、触发、知识依赖与发布边界审计

审计日期：2026-07-18  
审计对象：`skills/` 下全部53个标准Skill  
结论：数量准确；不存在完全重复Skill；统一首次配置向导负责检测云端知识库、企查查、BigQuery或其他专利数据、MCP、OCR和文档能力，其他Skill读取同一能力报告。

## 一、统一触发层级

1. `project-application-assistant` 是对外唯一推荐总入口。
2. `project-task-router` 仅作内部阶段路由，不独立争抢入口。
3. 项目类别Skill按明确项目类型触发；`regional-special-projects` 只承接现有类别无法覆盖的官方项目。
4. `industry-positioning` 负责论证，严格目录分类委托 `industry-chain-foundation-matcher`。
5. 专利业务先经过 `patent-data-foundation` 和 `patent-search-core`，再进入权利要求、相似、FTO、撰写、质检、方向或对标。
6. 团队知识只通过 `local-knowledge-retrieval` 调用云端固定API；服务不可用时只使用当前会话文件、本地个人政策规则和政府官方来源降级核验。

## 二、核心申报链 18项

| Skill | 主触发 | 强依赖 | 重叠与发布边界 |
|---|---|---|---|
| project-application-assistant | 企业能报什么、完整申报任务 | 路由、知识、匹配、可行性、写作、检查 | 唯一总入口；不替代专业Skill |
| project-task-router | 阶段不明、多阶段组合 | web-task-operator | 仅内部路由，不独立展示为快捷入口 |
| enterprise-profile | 企业画像、申报前事实底座 | 企业合法数据源 | 不做项目结论，不推算无来源财务 |
| project-matching | 多项目清单、年度路线图 | 项目地图、团队知识、第三方可选 | 只做候选匹配，不代替单项目可行性 |
| project-feasibility | 单项目门槛、差距、风险 | 政策、画像、证据 | 不承诺必然符合或获批 |
| policy-retrieval | 条件、时间、材料、最新通知 | 团队知识、政府官方源 | 负责检索；动态结论必须回官方原文 |
| local-knowledge-retrieval | 历史政策、名单、案例、模板 | `/v1/me`、`/v1/search`、`/v1/documents/{id}` | 名称为兼容保留；团队资料只走云端，不读取本地镜像 |
| evidence-ledger | 数字、政策、知识产权证据链 | 所有事实型Skill | 只记证据与不确定性，不作业务路由 |
| financial-verification | 财务指标复算 | 用户可靠财务资料 | 无可靠数据不推算；不替代审计 |
| application-writing | 正式申报正文 | 已核验政策、画像、证据 | 只在事实核验后写作 |
| consistency-check | 提交前一致性 | 写作成果、证据台账 | 质检不改写事实 |
| application-version-diff | 两版材料变化 | 两个明确版本 | 只做差异与风险，不代替一致性检查 |
| peer-benchmarking | 同行、名单、案例对标 | 公示名单、官方来源 | 不把未命中写成不存在 |
| industry-positioning | 产业链、重点领域论证 | 严格目录匹配 | 负责解释与证据链，不自造目录分类 |
| industry-chain-foundation-matcher | 产业链、工业六基严格分类 | 两份内置目录PDF | 目录无精确项时输出相似项与判断项，标注来源 |
| enterprise-panorama-analysis | 企业尽调、标准销售版或深度顾问版报告 | 团队知识、企业画像、项目与专利链 | 正式团队Skill；PDF由宿主提供，包内脚本仅作后备 |
| legal-regulations | 适用法律、现行效力、合规红线、行业监管 | 官方法规、当期通知、团队知识 | 法规适用性检索；不替代项目条件检索，不输出律师结论 |
| manufacturing-tax-risk-analysis | 制造企业三表复算、金税四期和税务风险 | 用户提供的审计、财务及税务资料 | 深度财税体检；与申报财务门槛核验分离，无可靠数据不推算 |

## 三、项目类别 12项

| Skill | 独占触发范围 | 与其他类别边界 |
|---|---|---|
| agriculture-and-rural-projects | 农业科技、龙头、乡村振兴、农产品 | 农业生产与加工为主 |
| digitalization-projects | 未来工厂、数字车间、工业互联网、软件 | 纯首版次转 industrialization |
| green-development-projects | 绿色工厂、节能降碳、清洁生产 | 设备投资补助转 investment-subsidy |
| industrialization-projects | 首台套、首批次、首版次、工业新产品 | 新产品产业化认定为主 |
| intellectual-property-projects | 知识产权示范、导航、高价值组合 | 专利文本业务转专利技能组 |
| investment-subsidy-projects | 技改、设备更新、固定资产、贴息 | 资金与投资门槛为主 |
| quality-brand-projects | 制造精品、质量奖、冠军、品牌 | 市场地位和质量荣誉为主 |
| regional-special-projects | 临时、园区、特色项目 | 仅在其余11类均不适配时兜底 |
| sme-development-projects | 创新型、专精特新、小巨人 | 强制产业链目录匹配与专项体检门禁 |
| talent-projects | 人才计划、博士后、专家、团队 | 人才或载体资格为主 |
| technology-innovation-projects | 研究院、研发中心、重点研发、奖励 | 研发平台与科技计划为主 |
| trade-and-open-economy-projects | 外贸、跨境、出口品牌、境外投资 | 开放型经济主管条线为主 |

## 四、知识产权链 11项

| Skill | 主触发 | 前置依赖 | 发布边界 |
|---|---|---|---|
| ip-assessment | 项目中的专利、软著、商标口径 | 可核验权利状态 | 区分授权、审中、转让；不做FTO |
| patent-data-foundation | 任何批量专利分析 | 合法数据源 | 必装底座，不单独给结论 |
| patent-search-core | 在先技术、IPC/CPC、检索计划 | data-foundation | 必装检索层，不把检索命中当侵权结论 |
| patent-claim-analysis | 权利要求、保护范围、稳定性 | data-foundation、search-core | 非律师意见；FTO另走专用Skill |
| patent-similarity-search | 相似专利、方案查重 | data-foundation、search-core | 相似度不等于侵权或不授权 |
| patent-fto-analysis | 上市、出口、自由实施 | data-foundation、search-core | 必须限定产品、地域、日期 |
| patent-drafting-coach | 交底书、权利要求、说明书 | 真实技术资料 | 不虚构实施例，不处理诉讼代理 |
| patent-draft-auditor | 申请文件提交前质检 | data-foundation、search-core | 只审稿，不代替撰写 |
| patent-direction-planner | 主营业务、预审、专利挖掘 | data-foundation、search-core | 企业业务导向；项目导向转 layout |
| patent-layout-planning | 目标项目反推专利缺口 | data-foundation | 项目导向；具体撰写转 drafting |
| patent-benchmark-landscape | 龙头专利地图、竞品路线、PPT | data-foundation、search-core | 对标分析，不直接形成FTO结论 |

## 五、数据与运行 5项

| Skill | 主触发 | 依赖 | 发布边界 |
|---|---|---|---|
| project-rule-manager | 地区规则录入、版本、替代、核验状态 | 官方原文、用户本地工作区 | 全体成员可维护本地规则；不得写团队云端知识库 |
| third-party-data-indexing | 企策顾问等授权增量采集 | web-task-operator、服务端采集器 | 实验性可选；不得绕过访问控制 |
| web-task-operator | 登录后网页任务、翻页、上传 | Agent浏览器能力 | 不内置浏览器品牌与账号 |
| project-memory | 继续、上次、既有决定 | 宿主持久记忆 | 不保存密钥与无关客户原文 |
| project-deliverable-archive | 正式成果或复杂任务自动归档 | 宿主可写工作区 | 不依赖笔记软件；不覆盖原文件、不自动上传云端 |

## 六、首次配置 1项

| Skill | 主触发 | 依赖 | 发布边界 |
|---|---|---|---|
| first-run-configuration | 首次安装、供应商配置、能力缺失 | 用户安全环境、可选联网验证 | 正式团队Skill；统一检测云端、企查查、专利、浏览器、OCR和文档能力，报告不含密钥 |

## 七、技能治理与知识图谱 6项

| Skill | 主触发 | 依赖 | 发布边界 |
|---|---|---|---|
| skill-authoring | 创建或更新Skill | 标准Skill规范 | 维护者工具，不在普通业务中自动触发 |
| skill-curator | 重复、冲突、过期审计 | 全包清单与使用记录 | 维护者工具 |
| skill-evolution | 用户明确要求优化 | 脱敏案例、评分 | 实验性；不得自动发布 |
| evolution-governance | 自动修改、合并、回滚 | 快照、测试、审批 | 强制治理门禁，维护者专用 |
| experience-recorder | 任务复盘、用户纠正 | 脱敏执行记录 | 只生成候选经验，不直接修改Skill |
| graphify | 知识图谱、关系追踪、GraphRAG | graphify第三方工具 | 仅明确触发；不替代云端全文检索与MCP |

## 八、知识库依赖等级

- **K0 无知识库依赖**：版本对比、写作、检查、路由、网页操作、技能治理等可在用户提供材料后工作。
- **K1 建议知识库**：企业画像、财务核验、专利撰写与质检可由用户材料完成，但知识库能补历史证据。
- **K2 强知识库依赖**：政策检索、项目匹配、可行性、项目类别、同行对标、产业定位必须检索团队库并核验官方原文。
- **K3 专用数据依赖**：专利数据底座、检索、FTO、相似和对标需要合法专利数据源；第三方索引需要用户合法账号与服务端采集器。

## 九、发布分层

1. **标准业务包**：核心申报链18项、项目类别12项、知识产权链11项，共41项，默认分发。
2. **首次配置**：`first-run-configuration`，随团队包默认分发并优先执行。
3. **可选运行包**：`project-rule-manager`、`web-task-operator`、`project-memory`、`project-deliverable-archive`，随团队包分发并按宿主能力启用。
4. **实验性包**：`third-party-data-indexing`，默认关闭，配置合法数据源后启用。
5. **维护者包**：5项技能治理能力，不应向普通申报工程师自动触发。
6. **资料边界**：目录PDF、公开政策和用户自有资料可随包或云库分发；第三方数据库原文、账号、Cookie、Token及不明授权模板不得进入发布包。

## 十、本轮已修正

- 明确总入口与内部路由器的触发顺序，消除 `project-application-assistant` 与 `project-task-router` 抢占。
- 将 `local-knowledge-retrieval` 改为团队云端API优先、本地RAG降级，消除最终架构仍依赖本地磁盘的问题。
- 在总入口中显式加入团队知识检索前置步骤。
- 将成员政策写入限定在本地 `project-rules/`，普通成员不能修改团队云端知识。
- 用自动归档替换Obsidian，并加入企业全景报告Skill。
- 增加 `first-run-configuration`，统一生成当前用户凭据文件、脱敏能力报告和首次配置说明。
- 增加 `legal-regulations` 与 `manufacturing-tax-risk-analysis`，并与政策检索、申报财务核验划清触发边界。
- 发布门禁扫描本机绝对路径、旧依赖名、`agents` 元数据、macOS `._` 文件和Python缓存。

## 十一、仍需人工验收

- 第三方动态采集必须用真实企策顾问账号做小样稳定性测试。
- 专利外部数据源的许可范围需按实际供应商合同确认。
- Skills ZIP正式发布前应按本报告分为标准、首次配置、可选、实验性和维护者五个清单，并运行全部安装测试。

## 十二、配置依赖结果

- **团队云端知识库**：所有团队成员统一配置 `JIAOTANG_KB_ENDPOINT`、`JIAOTANG_KB_MCP_URL` 和个人凭据；普通成员只读。
- **企查查**：`enterprise-profile`、`enterprise-panorama-analysis`、`peer-benchmarking` 可选增强；未配置时回到公开工商、企业材料和政府来源。
- **BigQuery或其他专利源**：`patent-data-foundation`、`patent-search-core`、相似、FTO、权利要求和专利对标任务需要；单件核验仍回官方专利来源。
- **MCP**：云端知识库支持网站生成的MCP地址与个人凭据；企查查和专利MCP由用户在首次配置向导中选择，不在各Skill重复配置。
- **OCR与PDF、Word、Excel、PPT**：由Agent提供，发布包只做能力检测和调用提示，不重复打包通用文档Skill。

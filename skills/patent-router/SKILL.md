---
name: patent-router
description: 共创研究院公司级专利工作的唯一综合入口。用户提出“这家公司的专利审查意见、全面建议”、专利查新、现有技术检索、专利挖掘、技术交底、AI或软件发明专利、权利要求策略、FTO、专利布局、地方保护中心预审推荐或政府项目知识产权关联时使用。单次运行内整合技术特征证据图、分层检索、专利挖掘交底和预审推荐，并强制记录法域、基准日、检索范围与证据来源。用户仅要求检查、核稿、批注或修订一份中国专利申请 Word 时改用 checking-patdocx-cn-single-agent；软件著作权登记材料不属于本技能。
---

# 共创研究院专利总路由


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-router" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

把每次公司级专利工作先变成可审计任务记录，再在一个技能内完成综合分析。原主技能、G1、G2 已作为本技能的内部组件，不再作为三个顶层技能分别触发。

## 强制任务头

执行前记录：

- `jurisdiction`：法域，默认中国；涉及地方预审时写到具体保护中心。
- `cutoff_date`：法律、状态和检索证据的基准日。
- `evidence_sources`：原始文件、数据库、官方网页、检索式及访问日。
- `primary_intent`：本轮唯一主意图。
- `confidentiality`：公开、内部、脱敏后可共享或商业秘密。

缺少法域、基准日或证据来源时，不得给出“现行、有效、最新、无现有技术、可授权、可预审”类确定结论。用 `scripts/patent_route.py` 生成并校验任务头。

## 完整申请案卷的唯一清单

用户要求撰写、形成或交付完整专利申请时，案件模式锁定为 `filing-ready`，并在第一个阶段文件形成前执行：

```bash
python3 scripts/patent_case_manifest.py init \
  --case-dir <案卷目录> \
  --case-id <不含技术秘密的案件标识>
```

本案只维护一份 `patent-case-manifest.json`。任务头、技术特征证据图、交底、检索计划、现有技术证据、申请文件输入、申请文件、附图规范、权利要求现有技术矩阵、核稿、核稿验证、预审建议和提交清单，必须以唯一角色登记文件路径、SHA-256、案件版本和上游依赖哈希。底稿或检索证据更新后，所有仍引用旧哈希的下游文件均为错版，不能靠文件名或“已完成”说明放行。

正式撰写前，先用 `scripts/build_technical_feature_map.py` 把技术问题、核心特征、效果、出处和检索单元形成 `technical-feature-map/v1`。完整申请案卷中，该证据图是交底、检索和申请文件的强制上游。规则见 `references/technical-feature-evidence-map.md`。

正式成文前先锁定事实，再使用唯一生成器：

```bash
python3 scripts/build_patent_application.py \
  --input <案卷目录>/application-input.json \
  --output <案卷目录>/application.docx \
  --drawing-spec <案卷目录>/drawing-spec.json \
  --audit-json <案卷目录>/application-audit.json \
  --case-dir <案卷目录>
```

生成器只消费 `patent-application-input/v1`，`fact_lock.status` 必须为 `confirmed`。正式案卷发现待补、占位或模板变量时停止；不补造实施例、参数、效果、申请人或发明人。申请 Word 仍须交给独立核稿技能检查。提交前生成清单并执行：

```bash
python3 scripts/patent_case_manifest.py checklist --case-dir <案卷目录>
python3 scripts/patent_case_manifest.py validate \
  --case-dir <案卷目录> \
  --milestone filing-ready
```

只有 `completion_allowed=true` 才能标记为可提交。门禁逐项返回缺失角色、错版依赖、哈希变化及精确重建任务。契约原文见 [专利申请交付契约](references/patent-application-delivery-contract.json)。

## 两条互斥路径

### A. 公司级综合审查：本技能

默认依次执行三个内部阶段，并在一份结论中合并：

1. `P1 检索与法律分析`
   - 查新、专利性初评、权利要求策略、FTO、布局。
   - 记录检索库、检索式、日期、覆盖范围和未检索范围。完整案卷中以技术特征证据图生成分层检索计划，依次覆盖单项特征、核心组合、分类号交叉、引证和同族扩展。
   - 申请文件先由 `scripts/build_ipc_evidence_chain.py` 生成权利要求引用关系图、独立权利要求必要技术特征树、IPC 候选和分层检索蓝图。
   - 检索结果必须带公开日、来源链接、命中原文、段落号、权利要求号、附图标记和证据等级，再用 `scripts/build_claim_prior_art_matrix.py` 生成可直接用于审查意见分析的 claim chart。
   - 使用 `scripts/claim_structure.py` 解析超长权利要求中的嵌套限定、并列与择一关系、数值范围和马库什变量。三层以上嵌套、多组择一或马库什结构强制标记特征边界复核。
   - 语义等同采用“机器发现候选＋原文、上下文权利要求、附图和本领域含义裁决”。词项、同义词、字符相似或模型判断只能标记 `LEXICAL_REVIEW_REQUIRED` 或 `SEMANTIC_REVIEW_REQUIRED`，不能自动认定已公开。
   - 新颖性按单一在先文件逐项判断；创造性依次记录最接近现有技术、区别特征、技术效果、实际技术问题和技术启示。详细数据契约见 `references/claim-prior-art-matrix.md`。
   - 方法见 `references/p1-search-analysis.md`。
2. `P2 专利挖掘与交底策略`
   - 扫描技术材料，形成专利点资产清单、保护主题、组合关系和交底缺口。
   - 未完成专利点清单与取舍，不直接成文交底书。证据图中标为预期、待确认或缺少定位的内容不得自动升级为申请文件事实。
   - 方法见 `references/p2-mining-disclosure.md`。
3. `P3 预审通道推荐`
   - 先比较浙江省、杭州市两个候选中心，再推荐一个主目标中心。
   - 不把两个中心的规则合并审查同一案件。
   - 两个中心的备案状态默认按“已备案”运行；这是主人确认的常设工作假设，不冒充逐案官方核验。用户提供相反信息、中心暂停服务或进入正式提交前复核时，以最新事实覆盖默认值。
   - 申请人注册地不作为默认反问项：根据用户给出的完整企业名称或统一社会信用代码，优先通过企查查取得登记住所并记录查询日期；主体简称先做实体识别。
   - 技术主题与拟申请 IPC 不作为默认反问项：优先从用户提供的技术材料、交底书或申请文件提取技术主题，由 P1/P2 分析形成拟申请 IPC、备选 IPC 和判断依据。
   - 对 `.docx` 申请文件先运行 `scripts/build_ipc_evidence_chain.py`，生成“原件哈希 → 权利要求引用图 → 独立权利要求技术特征树 → IPC候选 → 查新蓝图 → 双中心命中 → 唯一推荐”的JSON证据链。关键词结果只是候选，最终IPC仍按独立权利要求和正式分类复核。
   - 使用 `scripts/recommend_preexam_center.py`；进入正式预审检查前再运行 `scripts/audit_preexam_rules.py`。
   - 方法见 `references/p3-preexam.md`。

用户只问查新、交底或预审时，可以缩小输出，但仍由本技能统一记录；用户说“给出这家公司的审查意见、全面建议”时，P1、P2、P3 全部执行。

### AI 发明专利专项

技术材料涉及机器学习、生成式 AI、检索增强、Agent、具身智能、模型训练、推理优化或 AI 安全时，在 P1、P2 中同时执行 `references/ai-patent-practice.md`：

- 模型构建或训练类方案检查必要模块、层级或连接关系、训练步骤和必需参数。
- 具体场景应用类方案检查模型与场景的结合方式、输入输出的技术含义与内在关系。
- 数据采集、标签管理、规则设置或推荐决策涉及个人信息、法律、社会公德或公共利益时，单独记录合规事实和来源。
- AI 不得列为发明人。只记录自然人的创造性贡献线索，不在技术底稿中收集身份证号和私人联系方式。
- 方法、系统、设备、介质或计算机程序产品等主题按技术事实和保护价值选择，不机械追求固定“多件套餐”。

### B. 申请文件核稿：独立技能

`checking-patdocx-cn-single-agent` 只负责中国专利申请 Word 的逐条核稿、真实批注、修订与完整性验证。路由不依赖主人补充固定口令：

- 文件同时包含权利要求书、说明书和可识别独立权利要求时，自动识别为专利申请文件。
- 仅提供申请文件且没有企业级审查目标时，只执行独立核稿技能。
- 同时提供企业名称并要求全面审查时，自动建立双轨任务：总路由执行 P1、P2、P3，核稿技能独立执行文件检查；两轨分别输出，禁止把核稿问题混进预审准入结论。
- 有技术说明但没有权利要求书时，按技术材料或交底材料进入 P1、P2、P3，不启动核稿。

自动识别结果由 `scripts/build_ipc_evidence_chain.py` 的 `automatic_route` 字段记录；结构不足时才请求主人确认。

## 浙江默认预审中心池

共创研究院当前只维护以下两个 G2 候选中心：

1. `浙江省知识产权保护中心`
   - 案件级适用范围：申请主体在浙江省行政区域内，并满足该中心备案与产业领域要求。
   - 当前官方管理基线：《浙江省知识产权保护中心备案主体、代理机构预审服务管理办法（2025修订）》，自 2025-10-01 起施行。
2. `杭州市知识产权保护中心`
   - 结构化规则库兼容键：`中国（杭州）知识产权保护中心`。
   - 案件级适用范围：申请主体在杭州市行政区域内，并满足该中心备案与动态产业领域要求。

两个中心是“候选池”，不是要求同一申请同时通过两个中心。P3 必须先比较后推荐一个 `primary_target_center`；只有用户明确要求比较通道时，才对两个中心分别形成准入结果，禁止把两套规则合并成一套更严规则。

推荐顺序固定为：

1. 从企业登记数据取得申请主体注册地；两个中心备案状态默认“已备案”，存在相反证据时覆盖。
2. 拟申请 IPC 是否命中该中心现行官方清单。
3. 从用户材料分析所得技术主题与中心产业领域的直接匹配度。
4. 主体在该中心的现有备案、暂停或异常状态。
5. 证据同等时，保留两个候选并说明还缺哪项事实，不凭经验编造授权速度或通过率。

中心规则、产业领域和 IPC 分类号均按基准日动态核验，结构化内置记录只用于候选提示。官方入口及核验策略见 [references/preexam-default-centers.md](references/preexam-default-centers.md)。

完整决策表见 [references/routing-matrix.md](references/routing-matrix.md)。

## 流程规则

- 公司级任务在本技能内部按 `P1 检索分析 → P2 挖掘交底 → P3 预审推荐 → 项目关联` 串行执行。检测到申请文件时，核稿仍作为技能外的独立轨道自动执行，不再要求主人重复输入“检查申请文件”。
- 项目申报关联不是独立专利审查关卡。它只消费已核验的专利结论，并明确区分有效授权、审中、失效或终止、转让取得。
- 预审中心的“部分清单、派生数据、第三方镜像、不可访问附件”一律不得作为一票否决依据。
- 现行国家层面基线固定为：《专利审查指南（2023）》正文与国家知识产权局第 84 号令修改内容合并适用；第 84 号令修改内容自 2026-01-01 起施行。涉及电子申请文件时，同时执行自 2026-01-01 起实施的 XML 格式要求。后续有新规时按任务基准日继续更新。
- IPC 名称与分类有效性以案件基准日适用的国家知识产权局 IPC 版本为准；自 2026-01-01 起使用 IPC 2026.01 版。地方中心受理范围仍以各中心经核定的清单为准，二者不得互相替代。
- 查无结果只能写“当前检索范围未命中”。
- 不补造实施例参数、实验效果、专利号、法律状态、IPC、申请人或发明人。

## 回归门禁

使用真实申请文件前先保留 SHA-256，所有操作在副本上进行。回归至少覆盖：

- 批注起止锚点、跨 run 定位、重复文本 occurrence。
- 表格、文本框、脚注/尾注、公式、附图及附图标记。
- 修订接受后的内容差异。
- DOCX ZIP 部件、关系、内容类型和媒体完整性。
- 全页渲染检查；批注另做 OOXML 结构检查。

用 `scripts/build_anonymized_fixture.py` 生成不含原技术内容的结构保持样例，用 `scripts/docx_structure_audit.py` 对比结构。详细验收项见 [references/regression-gates.md](references/regression-gates.md)。

完整申请案卷另使用仓库内 `tests/fixtures/patent-case-delivery` 匿名夹具。该夹具只保留角色、依赖和章节结构，不含真实企业、发明人、技术方案、参数、效果或专利编号；`fixture` 可通过回归里程碑，但永远不能通过 `filing-ready`。

## 证据分级

- A：国家知识产权局、国家法律法规数据库、保护中心或政府主管部门原文。
- B：WIPO、EPO、USPTO 等对应法域官方数据库。
- C：商业数据库或学术数据库，用作检索线索并回到原文。
- D：第三方汇总、转载或模型推断，不单独支撑法律状态或地方准入结论。

输出先列事实和来源，再列判断、风险、缺口和下一步。高风险结论提示由执业专利代理师或律师复核。

双中心 IPC 库及快照状态见 [references/ipc-snapshots/manifest.json](references/ipc-snapshots/manifest.json)；推荐算法说明见 [references/preexam-center-recommendation.md](references/preexam-center-recommendation.md)。

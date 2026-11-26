---
name: patent-strategy-assistant
description: 公司级专利综合战略助手，处理专利查新检索、现有技术对比、专利挖掘交底、AI/软件算法发明、权利要求特征树与 FTO 自由实施尽调、专利布局、浙江/杭州双保护中心专利预审通道推荐及政府项目专利关联。
---

# 专利综合分析（patent-strategy-assistant）

本技能承接专利查新检索、权利要求特征对照（支持跨类独权继承解析与 Unicode 连字符范围展开）、双中心预审建议（含完整 `H04L` 通信安全与扩展产业词表）与布局规划，遵循本地 `references/v3-delivery-constitution.md`。

地方条件按[省级管理办法检索指引](references/policy-lookup.md)核对适用办法。申报时间、截止日期与当年申报范围由客户按当期通知确认。

单点适配咨询围绕企业及产品技术关系、近似检索、现有技术差异与改进建议展开；项目名称作为适配背景。完整申请、布局、FTO、预审或综合建议按对应方法组织。

## 任务与案卷

记录 `jurisdiction`、`cutoff_date`、`evidence_sources`、`primary_intent`、`confidentiality`，默认中国法域，地方预审记录具体中心。`scripts/patent_route.py` 可生成任务头；缺项说明假设和待核范围，按当前资料继续。

完整案卷以一份 `patent-case-manifest.json` 记录角色、路径、SHA-256、版本及上游依赖，资料变化后更新关联文件。技术问题、特征、效果、出处和检索单元由 `scripts/build_technical_feature_map.py` 形成 `technical-feature-map/v1`，供交底、检索和申请写作复用，规则见 `references/technical-feature-evidence-map.md`。

```bash
python3 scripts/patent_case_manifest.py init --case-dir <案卷目录> --case-id <脱敏案件标识>
python3 scripts/build_patent_application.py --input <案卷目录>/application-input.json --output <案卷目录>/application.docx --drawing-spec <案卷目录>/drawing-spec.json --audit-json <案卷目录>/application-audit.json --case-dir <案卷目录>
python3 scripts/patent_case_manifest.py checklist --case-dir <案卷目录>
python3 scripts/patent_case_manifest.py validate --case-dir <案卷目录> --milestone filing-ready
```

现有生成器输入契约为 `patent-application-input/v1`，`fact_lock.status: confirmed` 对应已确认材料。实施例、参数、效果、申请人与发明人按真实资料填写，草稿和资料清单记录需要确认的内容及当前状态。核验返回缺失角色、依赖版本、哈希和重建任务，`completion_allowed` 按真实结果记录；申请 Word 交独立核稿。契约见 [patent-application-delivery-contract.json](references/patent-application-delivery-contract.json)。

## P1 检索与法律分析

“快速摸底”只用于技术方向和候选文献线索，输出检索范围、候选清单及下一步检索动作；用户要求 FTO、侵权判断、无效证据或正式申请决策时，直接进入对应完整证据流程，快速摸底结果不作为这些任务的最终结论。

- 记录数据库、检索式、日期、覆盖与未覆盖范围；按单特征、核心组合、分类号交叉、引证和同族扩展形成分层计划。
- 每个候选集合记录来源方法、实际取得条数、服务端总数及截断状态；语义相似检索、条数封顶或仅取得部分分页的集合按截断样本处理，总数未知时保留空值，仅描述样本内已核文献与定性技术路线，不据此推算总体数量、技术路线占比或技术空白。
- 中国首轮发现优先 `scripts/cnipa_epub_search.py`，发送脱敏短技术词。题名、公开号和摘要标 `discovery`；公开日、官方全文、权利要求、图和状态核验后更新 `prior_art_eligible`。Google Patents 可补外国文献、同族、引证及全文，候选回对应法域官方文本。说明见 `references/cnipa-epub-provider.md`。
- `scripts/build_ipc_evidence_chain.py` 形成引用图、独立权利要求特征树、IPC 候选和检索蓝图。证据保留公开日、链接、命中原文、段落、权利要求、图标记和等级，以 `scripts/build_claim_prior_art_matrix.py` 形成 claim chart。
- `scripts/claim_structure.py` 解析嵌套、并列、择一、数值及马库什变量，复杂结构列特征范围复核。词项与语义候选分别标 `LEXICAL_REVIEW_REQUIRED`、`SEMANTIC_REVIEW_REQUIRED`，结合原文、上下文、附图和通常含义裁决。
- 新颖性逐单一在先文件判断；创造性写最接近现有技术、区别、效果、实际问题及技术启示。数据契约见 `references/claim-prior-art-matrix.md`，方法见 `references/p1-search-analysis.md`。

## 异步任务恢复

异步提供器从 `scripts/build_search_plan.py` 的 `run_async_search_unit` 提交与恢复。同一检索超时后按原远端任务标识查状态，从原检查点接续已存进度。状态未知时保留结果和检查点。提供器明确返回原任务失败或不存在，且本轮有重试授权时，才关联原任务记录重提。调用和登记字段见 [异步检索任务登记与恢复](references/async-search-state.md)。

## 检索条件生效核验

每轮新增 AND 条件或申请人、日期、分类号过滤后，抽查前10篇，不足10篇时全查，逐篇列出条件、原词或已确认等价表达、原文位置或字段值及符合结果，并计算全部新增条件均有证据的篇数占抽查篇数的比例；字段过滤出现反例时纠正检索式，技术条件无原文证据的文献退出对应限定候选集，新增条件使条数减少但抽查符合比例未提高时改用已验证字段、分类号或另一特征组合重新检索。

## P2 挖掘、交底与布局

形成专利点资产、保护主题、组合关系、取舍和交底缺口，再按目标展开文本。证据图分别记录预期内容和需要确认的内容，并保留各自状态。布局在 P2 形成申请前决策，按需复用 P1 的检索和法律分析。按[布局规划](references/patent-layout-planning.md)确定核心、外围、工艺控制、应用和防御公开的组合、优先级及申请与公开节奏。授权前景以现有技术、差异和不确定性表达。方法见 `references/p2-mining-disclosure.md`。

## P3 预审推荐

对浙江省、杭州市两候选中心分别核验并推荐 `primary_target_center`，规则按中心独立呈现。按申请主体和中心核验本案备案证据，缺证据记“未核实”。住所区分企业提供、接口返回和公开来源。

主体住所从企业全称或信用代码及[企业数据源说明](../_runtime/enterprise-source-fallback.md)取得；主题从技术材料、交底或申请提取，IPC 由独立权利要求与正式分类复核。`.docx` 可通过 `build_ipc_evidence_chain.py` 形成“原件哈希—引用图—特征树—IPC—查新—双中心匹配—推荐”证据链，使用 `scripts/recommend_preexam_center.py` 和 `scripts/audit_preexam_rules.py`。

- 浙江省知识产权保护中心：核对浙江省注册地、备案和领域；当前记录基线为《浙江省知识产权保护中心备案主体、代理机构预审服务管理办法（2025修订）》，2025-10-01 起施行，按案件基准日复核。
- 杭州市知识产权保护中心：兼容键 `中国（杭州）知识产权保护中心`，核对杭州市注册地、备案及动态领域。

比较注册地、现行 IPC 清单、技术主题、备案暂停和异常状态；证据相当时保留候选及缺项。部分清单、派生记录、镜像和待访问附件作为线索，准入结论依据当前官方资料。说明见 `references/p3-preexam.md`、[preexam-default-centers.md](references/preexam-default-centers.md)、[routing-matrix.md](references/routing-matrix.md)。

## AI 发明与文件核稿

AI、RAG、Agent、模型训练推理等参考 `references/ai-patent-practice.md`：模型构建写模块、层级连接、训练步骤和必要参数；应用方案写场景结合、输入输出的技术含义与关系；数据、标签、规则及决策涉及个人信息或公共利益时记录合规事实。发明人记录自然人的创造性贡献，敏感身份信息通过专用申请接口处理。主题按保护价值选择方法、系统、设备、介质或程序产品。

包含权利要求、说明书及独立权利要求的文件可自动识别核稿，`automatic_route` 记录结果。单文件检查衔接 `patent-docx-reviewer`；综合企业任务可同时保留 P1/P2/P3 和核稿结果，各自注明范围。有技术说明时按资料程度开展检索挖掘及通道分析。

## 基线与验证

案件日期核验《专利审查指南（2023）》及第 84 号令合并文本，当前记录的修改生效日为 2026-01-01，电子申请 XML 要求及 IPC 2026.01 同期更新；后续按新规更新。国家分类和各中心受理清单分列。项目关联（`PROJECT_LINK`）仅使用已核验专利结果，分别标注授权、审中、终止及转让。缺项按对应专利任务单独核验。

查询采用脱敏词，验证码与人工交互交网站正常流程；凭据、未公开方案和个人数据通过宿主权限与安全接口处理。未命中写当前检索范围，具体技术、号码与状态取可验证来源。

原件保留 SHA-256，在副本核对批注锚点、跨 run、重复 occurrence、表格文本框、脚尾注、公式附图、修订差异、ZIP 部件关系及媒体，并检查全页渲染。适配器回归覆盖离线解析、类型选择、去重、证据降级、敏感查询处理、重试和零结果。

`scripts/build_anonymized_fixture.py` 生成结构样例，`scripts/docx_structure_audit.py` 比较结构。详见 `references/regression-gates.md`。

来源分级：A 为国家知识产权局、法规库及中心主管原文；B 为 WIPO/EPO/USPTO 对应官方库；C 为商业学术检索线索；D 为转载汇总或推断。事实及来源、判断、风险、缺口、动作依次呈现，高风险意见结合执业代理师或律师复核。

IPC 快照见 [ipc-snapshots/manifest.json](references/ipc-snapshots/manifest.json)，推荐算法见 [preexam-center-recommendation.md](references/preexam-center-recommendation.md)。

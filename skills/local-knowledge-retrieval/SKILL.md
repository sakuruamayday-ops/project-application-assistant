---
name: local-knowledge-retrieval
description: 按本地索引 rag-query.sh → 云端 → 官方来源的顺序查询政策、案例、模板、名单及项目经验，核对主体、地区、年度批次与来源。
---

# 套件知识检索

## 商业定位、MCP 双态与黑板接力

本技能为 **WorkBuddy 免费公开数据 MCP 入口（申报案例与名单查询）**，遵循 [WorkBuddy 商业分层与 MCP 规范](../_runtime/workbuddy-core/mcp-routing-and-tiering.md)：

- **免费只读公开事实**：围绕专精特新、小巨人、首台套、首批次、首版次公开认定事实与原文定位返回带原文定位的结构化事实，不携带商业模板或私有案例正文。
- **MCP 双态处理**：已配置免费数据 MCP 时优先查权威只读库（`origin: mcp_verified`）；未配置时基于本机导入清单或公开来源说明覆盖范围并提示开通免费数据 Key；已配置但鉴权失效/限流/超时时显式报错不静默蒙混。
- **主体隔离黑板接力**：将核验命中的主体认定记录写入工作区 `.facts/<企业标识>.facts.json` 供下游评估与收费撰写无缝复用。

从问题提取企业、项目、地区、年份、批次和文件类型。检索词与职责分工见[检索编排协议](references/search-orchestration.md)，三首名单见[三首项目名单数据协议](references/three-first-project-list-schema.md)。

## 查询顺序

检索顺序：本地索引 rag-query.sh → 云端 → 官方来源

每项所需证据从第一级开始。取得与查询范围相符、足以支撑该项结论的证据即结束该项检索。某级未命中或不可用时，只把该级仍缺的证据交给下一级。

### 第一级 · 本地索引

查询前检查 `~/JiaotangData/索引/current` 和 `~/JiaotangData/知识库`。两处都须是可读、可进入的目录。`current` 为软链接时检查其实际指向，并确认两个索引库可读。

```bash
index_dir="$HOME/JiaotangData/索引/current"
knowledge_dir="$HOME/JiaotangData/知识库"
test -d "$index_dir" && test -r "$index_dir" && test -x "$index_dir" &&
  test -d "$knowledge_dir" && test -r "$knowledge_dir" && test -x "$knowledge_dir" &&
  test -r "$index_dir/knowledge_content.sqlite3" &&
  test -r "$index_dir/knowledge_inventory.sqlite3"
```

通过自检后运行 `~/rag/rag-query.sh "查询词" [top_k] [分类]`。入口转调 `search_local_index.py`。默认取 8 条。整数 `top_k` 超出 1 至 30 时取相应边界值。分类按索引中的顶层分类名称传入，指定分类时先传 `top_k`。

- **命中**。读取 `results` 中的标题、摘要和源路径，打开所需原文，核对主体、项目、年份批次或地区等查询条件。涉及现行条件、申报期限和认定状态，须取得能支持该项结论的原文或附件。
- **未命中**。`results` 为空，或调整简称、全称、年份批次等查询词后仍只有不相关条目、无法回读的线索或缺少所需证据，记录“当前本地索引未命中”及已查范围，进入下一级。结合标题、原文和查询条件判断相关度，`score` 用于检索排序。
- **不可用**。目录或索引库不可读、命令退出失败或无有效 JSON 时，记录本地故障，进入下一级。

#### 本地 JSON 与来源

- `query` 是输入，`effective_query` 是脚本改写后的主查询，`category` 是分类或 `null`，`expanded_queries` 是额外查询词数组。用 `len(results)` 计本次实际返回条目，受 `top_k` 限制。需要统计有效命中时，按核对过的相关条目另计。
- `results` 每条都有 `title`、`source`、`document_role`、`sensitivity`、`excerpt`、`score`、`index_layer`、`search_method`、`适用地区`、`duplicate_count`、`duplicate_titles`、`duplicate_sources`。`search_method` 为 `segmented_fts`、`fts` 或 `contains`。`duplicate_count` 为同组折叠的其他条目数。
- `index_layer=content` 的结果还带 `validity_status`、`replacement_title`、`replacement_url`、`canonical_project_name`、`region`、`document_stage`，`excerpt` 为正文片段。`index_layer=metadata` 的结果带 `index_mode`、`upload_action`，`excerpt` 为空字符串，引用正文须打开原文件。
- 关联政策版本记录时会增加 `version_group_id`、`version_status`、`policy_status`、`detected_date`、`detected_year`、`latest_source`、`confidence`、`lifecycle_evidence_type`、`lifecycle_evidence_quote`、`lifecycle_evidence_source`、`superseded_by_source`、`supersession_basis`、`policy_status_source`，部分已替代或到期条目还带 `validity_label`。以原文确认效力和替代关系。
- `source` 是索引记录的来源路径。先在 `~/JiaotangData/知识库` 下按该相对路径定位。遇旧归档路径，结合 `duplicate_sources`、题名、项目、地区和附件名回找重排后的对应文件，核对一致后引用实际读到的路径和页码、条款或附件位置。原件缺失时保留 `source` 作为线索，报告缺少的证据。
- `index_status` 提供 `release_id`、`inventory_files`、`content_indexed`、`content_characters`、`policy_candidates`、`multi_version_groups` 和 `live_metrics`。`ocr_or_conversion_pending` 来自提取摘要快照，依据 `pending_metric_source` 和 `pending_metric_generated_at` 说明其口径。

实跑 `~/rag/rag-query.sh "研发费用比例" 5` 返回 5 条。下例保留六个顶层字段，节选第一条公开来源的字段与索引版本。

```json
{
  "query": "研发费用比例",
  "effective_query": "研发费用比例",
  "category": null,
  "expanded_queries": [],
  "results": [
    {
      "title": "关于组织申报2025年宁波市制造业“大优强”（培育）企业并购项目的通知—附件3：研发费用加计扣除优惠明细表.pdf",
      "source": "10_政策与目录/政策数据库/企策顾问/申报通知/宁波市/软件与数字经济/2025-03-10__关于组织申报2025年宁波市制造业“大优强”（培育）企业并购项目的通知__954437624e184884bd21c08cd0a82a05/附件/附件3：研发费用加计扣除优惠明细表.pdf",
      "document_role": "10_政策与通知",
      "sensitivity": "public_reference",
      "index_layer": "content",
      "search_method": "segmented_fts",
      "适用地区": "宁波市"
    }
  ],
  "index_status": {
    "release_id": "local-20261120T054329.204911Z"
  }
}
```

### 第二级 · 团队云端知识服务

查本轮已暴露的 `jiaotang-kb` MCP 工具，调用一次 `knowledge_service_status` 或宿主等价状态工具。`connected: true` 且所需检索工具可调用时才执行查询。

- 企业名单组合 MCP `public_list_search` 与 `knowledge_search`（分别对应 `POST /v1/lists/search` 和 `POST /v1/search`）。权威名单核验可用 `authoritative_list_search`，按工具支持的企业、年度、批次、地区和状态筛选。
- 产品、行业、技术反查用 `recognition_search`（`POST /v1/recognition/search`）。三首组合用 `three_first_analysis`（`POST /v1/three-first/analyze`），保留实际返回的项目和地区分组。案例用 `knowledge_case_pack`。
- 关键命中按文档 ID 调用 `knowledge_document`（`GET /v1/documents/{id}`）读取全文，检查来源和适用范围。查询仅提交当前任务授权的条件，Bearer Token 由宿主安全凭据接口管理，连接状态脱敏记录。
- **命中**。检索返回与待补项相符，且可取得所需证据，使用已取得的结果结束该项检索。
- **未命中**。状态已连接，检索返回为空、无关或缺少所需证据，记录“本轮云端检索未命中”，进入下一级。
- **不可用**。MCP 或状态工具未暴露、`connected` 未返回 `true`、权限不足、所需工具不可调或连接超时时，记“本轮云端不可用”，直接进入下一级。同一轮出现此状态后跳过云端恢复探测和重试。

### 第三级 · 官方来源与用户文件

只补前两级仍缺的证据。查主管部门发布的原文和附件，或读用户为当前任务提供的文件。用管理办法确认政策条件和效力，用认定公示确认称号状态，用用户文件确认企业与项目事实。命中时记录文件名、发布机关或提供方及具体位置。适用来源均未取得匹配证据时，列出已查范围和缺少的文件或字段，结束本轮检索。

## 名单与产品证据

反向发现分别保留产品行业证据和认定证据，云端返回的 `verified_matches` 进入已核验表，`pending_candidates` 记录线索。三首按公示、认定、奖励、目录退出分别记事件，退出状态引用明确原文。缺具体产品时列企业、项目、年度、已有来源及缺少的材料。

跨年名单、复核及城市归属结合按检索顺序取得的企业身份时间轴，[企业数据源说明](../_runtime/enterprise-source-fallback.md)补当前主体，冲突回官方裁决。申报时间、截止日期与当年申报范围由客户按当期通知确认。技能依据管理办法判断条件、生成材料、开展体检。

有结构化结果时，核对 `coverage`、`pagination`、全部项目分组和分级结果，逐页处理实际返回的 `has_more`、`is_truncated`。来源、地区、年份、批次、同义词或产品证据覆盖缺项时说明当前范围。

业务判断沿用“公示即终局”。引用公示、拟支持、拟认定、拟入选等名单时，标题、正文、表格状态和统计口径均保留主管部门原文的状态词。原文发布正式认定、正式支持或正式入选结果时，使用对应正式状态。

## 完整度与计数

- `coverage_complete` 为 `true/false`，缺覆盖时记 `false`。`truncated` 为 `true/false/unavailable`。任一路径 `has_more=true` 或 `is_truncated=true` 时记 `true`。各实际路径提供分页状态且全部到底记 `false`。使用本地索引或 `knowledge_search` 等无分页状态的路径且其他路径未确认截断时记 `unavailable`。
- `verified`、`pending`、`noise`、`conflict` 同时说明单位、去重键、精确值或下限。文档数、名单行数、企业数和企业＋项目＋年度批次记录数分别统计。显式实体、各分级合计、总计和核验调用范围相互对照，冲突列明。
- `statement_conflicts` 按实际逐项检查填写。当前或未来批次的最终名单状态与主表覆盖分列，官方最终名单已可读时核对主表遗漏。
- `activation_ok`、`prompt_context_ok`、`delivery_check_ok` 分别记录。`state_origin=activation_fallback` 可说明激活持久化，提示词及交付观测采用 `prompt_hook_observable=false`、`delivery_check=unavailable` 等真实状态。
- 验收、保存、归档和日志按用户任务范围分别执行，宿主自动缓存按实际事件记录。

## 案例与政策资料

案例先查本地索引和原文件。进入第二级时，用 `knowledge_case_pack` 按 `project_id`、年度、行业和规模选取，按申报书或建设方案骨架及 `section` 对应附件分层取得。借鉴结构、指标组织和证据类型，当前客户事实取其自身材料。`auto_grouped` 为自动归组，重要关系回原件核对。

条件、评分和材料要求回查管理办法及其随文附件。已获评事实回查主管部门公示和名单。本地按返回的文档角色、阶段、效力和来源路径分辨资料，云端按实际返回的 `source_layer`、`source_labels`、`verification_status`、`validity_status` 分辨来源。报告表达采用[报告写作规则](../_runtime/report-writing.md)。

---
name: local-knowledge-retrieval
description: 检索团队知识服务中的政策、案例、模板、名单及项目经验，组合简称全称、年份批次、结构化名单和全文路径，保留实际覆盖范围与来源状态。
---

# 团队知识检索

按本轮可用工具访问 `jiaotang-kb` MCP。普通成员采用已连接的远程服务，管理员已配置本地索引时按本机规则使用；缺能力时衔接当前客户端连接流程，以会话文件、个人政策规则和官方来源继续任务。Bearer Token 由宿主安全凭据接口管理，输出使用脱敏连接状态。

## 查询路由

1. `knowledge_service_status` 或等价工具检查实际状态，`connected: true` 记连接成功；未连接、无权限、工具未暴露及检索未命中分别记录。
2. 解析企业、项目、地区、年份、批次、文件类型，参考 [search-orchestration.md](references/search-orchestration.md)。三首名单参考 [three-first-project-list-schema.md](references/three-first-project-list-schema.md)。
3. 已知企业名单组合 `POST /v1/lists/search` 与 `POST /v1/search`，MCP 对应 `public_list_search`、`knowledge_search`；产品、行业、技术反查采用 `POST /v1/recognition/search` 或 `recognition_search`；三首组合采用 `POST /v1/three-first/analyze` 或 `three_first_analysis`，保留全部项目和地区。
4. 首轮未命中时展开简称、全称、年份、批次、类型和地区变体。关键文档用 `GET /v1/documents/{id}` 或 `knowledge_document` 取全文。
5. 跨年名单、复核及城市归属结合企业身份时间轴，[企业数据源说明](../_runtime/enterprise-source-fallback.md)补当前主体，冲突回官方裁决。
6. 当期通知识别企业截止时间，按北京时间算剩余天数，并分别列企业截止与主管部门报送截止。

服务新增工具时刷新原 MCP，三首与反向发现使用同一连接。超时后可重发现工具并复核状态，仍待恢复时保留已有结果和未完成范围，其他资料渠道继续。

## 名单与产品证据

`authoritative_list_search` 适用于企业、年度、批次、地区和状态的名单核验；产品、行业反查使用 `recognition_search`，三首使用专表。查询参数按工具已支持字段，过滤结果对应实际条件。

反向发现分别保留产品行业证据和认定证据，`verified_matches` 进入已认定表，`pending_candidates` 列待核线索。三首按公示、认定、奖励、目录退出分别记事件；退出状态引用明确原文。具体产品待取时复用本轮材料和官方附件，仍缺项则交企业、项目、年度、来源及待取材料。

核对 `coverage`、`pagination`、全部项目分组和分级结果，逐页处理实际返回的 `has_more`、`is_truncated`。来源、地区、年份、批次、同义词或产品证据覆盖缺项时说明当前范围。

## 完整度与计数

- `coverage_complete` 为 `true/false`；`truncated` 为 `true/false/unavailable`。任一路径 `has_more=true` 或 `is_truncated=true` 时记 `true`；各实际路径提供分页状态且全部到底记 `false`；使用无分页状态的 `knowledge_search` 且其他路径未确认截断时记 `unavailable`。覆盖缺项记 `coverage_complete=false`。
- `verified`、`pending`、`noise`、`conflict` 同时说明单位、去重键、精确值或下限。文档数、名单行数、企业数和企业＋项目＋年度批次记录数分别统计；显式实体、各分级合计、总计和核验调用范围相互对照，冲突列明。
- `statement_conflicts` 按实际逐项检查填写。当前或未来批次的最终名单状态与主表覆盖分列，官方最终名单已可读时核对主表遗漏。
- `activation_ok`、`prompt_context_ok`、`delivery_check_ok` 分别记录。`state_origin=activation_fallback` 可说明激活持久化，提示词及交付观测采用 `prompt_hook_observable=false`、`delivery_check=unavailable` 等真实状态。
- 验收、保存、归档和日志按用户任务范围分别执行，宿主自动缓存按实际事件记录。

## 案例与政策资料

案例用 `knowledge_case_pack` 按 `project_id`、年度、行业和规模选取，按申报书或建设方案骨架及 `section` 对应附件分层取得。借鉴结构、指标组织和证据类型，当前客户事实取其自身材料。`auto_grouped` 为自动归组，重要关系回原件核对。

条件、评分、模板和维护侧重规则资料；最新通知、公示、名单、截止和具体批次侧重动态资料，结合官方原文核验。意图待明时可同时列条件和动态线索，围绕用户问题收敛。

后台以 `source_layer`、`source_labels`、`verification_status`、`validity_status` 排序，区分规则、动态、官方链接和实际核验。对外呈现可追溯文件、来源及已核结论；尚未取得原文的部分保持待核并继续交付已有结果。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

---
name: graphify
description: 按用户指定目录构建和更新知识图谱，支持关系追踪、路径、社区聚类、GraphRAG 及证据导航；用户提出图谱需求或点名 graphify 时使用。
---

# 知识图谱构建与查询

将代码、政策和项目资料转换为可持续更新的关系图。输入采用用户指定的客户、项目、专题或多主体范围，各项目输出独立 `graphify-out/`；普通关键词和全文查询按需使用知识服务。

## 范围与来源

1. 按 `references/project-profiles.md` 选择 `application-evidence`、`policy-corpus`、`ip-evidence` 或 `client-dossier`，确认目录、目标、隐私级别及输出。
2. 专精特新与小巨人记录项目类型及申请书版本，资料盘点、构图和资格判断分别呈现状态。
3. 客户资料采用 `privacy=restricted`，公开政策、公示和专利可用 `privacy=public`，保留来源及采集日期。敏感身份、账户、凭据和原始名单通过数据筛选及脱敏处理；外部后端传输按用户指令和宿主权限执行，规则见 `references/privacy-and-scope.md`。
4. 原文提取、模型推断和歧义分别标为 `EXTRACTED`、`INFERRED`、`AMBIGUOUS`。图谱用于导航与发现，政策现行性、企业登记、专利状态和财务原值由原始来源核验。

## 工具与构建

检测 `graphifyy` 能力：

```bash
command -v graphify || python3 -c "import graphify"
```

需要依赖时按当前环境使用 `uv tool install graphifyy` 或 `python3 -m pip install graphifyy`，向用户说明所用第三方工具与实际版本。

1. 初始化项目并生成领域提取规范：

```bash
python3 scripts/init_project.py PROJECT_ROOT --profile PROFILE --project-name "项目名称" --client-name "客户名称" --privacy restricted
python3 scripts/build_prompt.py --overlay references/domain-overlay.md --output PROJECT_ROOT/graphify-out/.project-extraction-spec.md
```

存在上游规范时可增加 `--upstream 基础规范路径`。按文件规模分批构建，保留 `graph.json`、交互式 HTML 和 `GRAPH_REPORT.md`。

2. 审计并抽样核对实体、关系方向、同名合并、来源、政策版本、专利状态和推断标记：

```bash
python3 scripts/audit_graph.py PROJECT_ROOT/graphify-out/graph.json --profile PROJECT_ROOT/.gongchuang-graphify.json --output PROJECT_ROOT/graphify-out/EVIDENCE_GRAPH_AUDIT.md
```

3. 告警结合原文裁决，后续按文件变化增量更新，保留旧图供回滚：

```bash
graphify <目录> --no-viz
graphify <目录> --update
graphify query "问题"
graphify path "实体A" "实体B"
graphify explain "实体名称"
```

交互图可移除 `--no-viz`；GraphRAG JSON、MCP 按工具实际能力提供，与团队知识服务各司其职。

## 业务查询与交付

政策版本、项目层级、企业产品技术、专利和证据关系参考 `references/domain-overlay.md`，查询参考 `references/query-templates.md`。

回答区分图谱事实及 `source_file`、`source_location`，推断及置信度，待外部核验事项和行动。核对关键节点到原文件、客户范围、隐私级别、冲突及增量覆盖。正式材料按相应业务技能组织，以当前可用证据形成稿件。

第三方工具 `graphifyy` 的版本、安装和许可证以实际发布说明为准；本技能提供原创业务适配方法。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

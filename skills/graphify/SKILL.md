---
name: graphify
description: 将代码、政策、项目资料或知识库目录构建为可查询的持久知识图谱。仅在用户明确要求知识图谱、关系图、路径追踪、社区聚类、GraphRAG或明确点名graphify时使用。
---

# 知识图谱构建与查询


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "graphify" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

把用户指定目录转换为可持续更新的知识图谱，用于发现文件、政策、项目、企业、产品、技术、专利和证据之间的关系。

## 使用边界

- 普通文件搜索、政策关键词检索和知识库全文查询继续使用云端知识库，不自动触发本技能。
- 只有用户明确要求知识图谱、关系追踪、最短路径、社区聚类或GraphRAG时触发。
- 不默认生成Obsidian目录；标准输出为交互式HTML、图数据JSON和图谱报告。
- 图谱中的推断关系必须与原文提取关系分开标记，不把模型推断写成政策或企业事实。
- 只处理用户指定的单一客户、单一项目或单一专题目录，不扫描主目录、磁盘根、整个知识库或混合客户根目录。
- 每个客户或项目使用独立的 `graphify-out/`；除非用户明确要求集团或多主体对比，不合并不同客户图谱。
- Graphify只用于关系导航、证据链检查和异常发现，不替代政策现行性、企业登记、专利法律状态或财务原值核验。

## 项目与隐私门禁

1. 先读 `references/project-profiles.md`，选择 `application-evidence`、`policy-corpus`、`ip-evidence` 或 `client-dossier`。
2. 涉及专精特新或小巨人时，先确认申请书项目类型与审核版本；未确认时只能盘点资料和构图，不形成达标结论。
3. 客户项目默认 `privacy=restricted`。不得因环境中存在模型密钥就把客户资料发送给第三方后端。
4. 发现凭据、身份证件、银行账号、原始员工花名册或未脱敏客户名单时，排除相应文件并只报告数量。
5. 公开政策、公示名单和公开专利可使用 `privacy=public`，但仍须保留来源和采集日期。

完整规则见 `references/privacy-and-scope.md`。

## 前置能力

本技能调用开源 `graphifyy` 工具。首次使用时先检测：

```bash
command -v graphify || python3 -c "import graphify"
```

未安装时向用户说明将安装第三方依赖，再执行以下任一方式：

```bash
uv tool install graphifyy
```

或：

```bash
python3 -m pip install graphifyy
```

## 构建流程

1. 确认输入目录、业务 Profile、隐私级别和输出目的。
2. 至少10个相关文件、预计超过20,000字、需要跨材料证据核对或会持续更新时再构图；小任务直接使用现有检索与审查技能。
3. 初始化项目：

```bash
python3 scripts/init_project.py PROJECT_ROOT \
  --profile PROFILE \
  --project-name "项目名称" \
  --client-name "客户名称" \
  --privacy restricted
```

4. 生成业务语义提取规范：

```bash
python3 scripts/build_prompt.py \
  --overlay references/domain-overlay.md \
  --output PROJECT_ROOT/graphify-out/.project-extraction-spec.md
```

如宿主或已安装的 Graphify 提供基础提取规范，可额外传入 `--upstream 基础规范路径`，再叠加本技能规则。
5. 统计文件数量、类型和规模；超过500份文件时按一级目录分批。
6. 执行完整构建，输出到项目目录下的 `graphify-out/`，至少保留 `graph.json`、交互式HTML和 `GRAPH_REPORT.md`。
7. 审计图谱：

```bash
python3 scripts/audit_graph.py \
  PROJECT_ROOT/graphify-out/graph.json \
  --profile PROJECT_ROOT/.jiaotang-graphify.json \
  --output PROJECT_ROOT/graphify-out/EVIDENCE_GRAPH_AUDIT.md
```

8. 抽样核对实体、关系、来源文件、政策版本、专利状态和推断标记；审计告警不自动改图。
9. 后续文件变化时优先增量更新，不重复全量构建。

常用命令：

```bash
graphify <目录> --no-viz
graphify <目录> --update
graphify query "问题"
graphify path "实体A" "实体B"
graphify explain "实体名称"
```

需要交互图时移除 `--no-viz`。需要提供给其他Agent时，可使用工具支持的GraphRAG JSON或MCP模式，但不得替代团队知识库现有MCP。

## 政府项目场景

- 政策版本图：政策、废止依据、替代文件、申报通知和执行细则。
- 项目关系图：国家、省、市、区县项目及其上下级、别名和申报条件。
- 企业能力图：产品、技术、专利、客户验证、产业链和可申报项目。
- 专利关系图：申请人、权利人、同族、引证、技术特征和产品映射。

业务实体、关系方向、来源等级和申报四项判断规则见 `references/domain-overlay.md`；常用问题见 `references/query-templates.md`。

## 查询与交付

回答必须区分：

1. 图谱事实：附 `source_file` 或 `source_location`；
2. 图谱推断：标明关系置信度；
3. 待外部核验：政策现行性、企业登记、专利法律状态和财务原值；
4. 行动项：缺少的材料、冲突关系或补证任务。

正式申报文本仍须经过套件的真实性、数据溯源、关联一致性和交付门禁，图谱报告不能替代正式申报材料。

## 验收

- 每个关键节点可追溯到原文件。
- 抽样关系不存在方向颠倒或同名实体误合并。
- `EXTRACTED`、`INFERRED`和`AMBIGUOUS`关系明确区分。
- 不同客户资料未进入同一图谱，受限资料未静默发送到外部模型。
- 政策版本、专利状态和事实冲突被显式保留，不以共现关系替代核验。
- 更新后旧图谱可回滚，新增文件能够进入增量结果。

## 来源说明

本技能是企业全生命周期助手的原创适配说明，运行时依赖第三方开源包 `graphifyy`。第三方软件的安装、版本和许可证以其发布页面为准，不随本技能复制第三方源码。

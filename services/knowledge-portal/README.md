# 企业全生命周期助手知识库服务

面向团队的统一权限知识库入口。网站使用英文账号和密码登录；普通成员通过本地 Agent 的设备公钥签名访问 API 和 MCP，管理员账号保留多设备 API Key 豁免。

## 安全边界

- 不设置部门或技能等级，所有有效用户拥有相同知识检索能力。
- 普通成员使用团队大模型时默认每天5次，管理员问答不限次数；用户自带API不计团队额度。
- 管理员不执行单设备限制；普通成员同一时间只允许一组有效设备公钥。
- 登录密码使用 Argon2 哈希保存。
- Session 和用户凭据仅保存 SHA-256 哈希；普通成员的明文 Token 只返回给本地安装代理，不在门户显示。
- 普通成员使用 Ed25519 逐请求签名，云端保存公钥和 nonce；私钥在 macOS 系统钥匙串或 Windows 当前用户 DPAPI 中保存。
- 登录账号使用英文；生成 API Token 时填写中文真实姓名，公司全称用于团队成员身份验证。
- 登录时可选择七天自动登录，未选择时沿用短会话时长。
- OSS、SSH、数据库密码和阿里云 AccessKey 不进入 Skills。
- 生产环境必须启用 HTTPS，禁止通过公网 HTTP 输入密码。

## 本地运行

```bash
cd services/knowledge-portal
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export JIAOTANG_SETUP_KEY="$(openssl rand -hex 24)"
export JIAOTANG_SECURE_COOKIES=false
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
```

首次打开 `/setup`，输入初始化密钥并创建管理员账号。
管理员可在控制台创建团队账号；成员首次登录后应立即修改初始密码。

## Agent 接入

普通成员：

1. 在门户点击“复制给 Agent”。
2. 把复制的文字粘贴到本地 Agent。
3. 门户向 Agent 提供一个 `jiaotang-agent-install/v1` HTTPS 安装说明。说明只包含签名 WorkBuddy 插件包、联网地址、本地改动、凭据保存方式、回滚方法和一次性 `bootstrap_url`，不包含任何动态命令字段。
4. 用户从已登录门户下载签名 WorkBuddy 插件包，核验 SHA-256 与 Ed25519 签名后运行包内对应系统的固定安装器。
5. WorkBuddy 启用插件时提示填写一次性 `bootstrap_url`，并按敏感配置保存；插件内置的 `jiaotang-kb` 随插件自动启动，不写入宿主级 MCP 配置。
6. 只有服务器记录到首次成功的签名 MCP 连接，门户和安装器才会报告“安装成功”；此前统一显示“安装未完成”。
7. 设备登记只把引导码标记为“安装中”。在 MCP 最终确认前，同一引导码可安全替换未完成的临时绑定并重试；服务器确认签名 MCP 连接后才最终消费引导码。
8. 安装码、API Token 和设备私钥不得显示、复制到聊天或写入普通配置；设备私钥只在本机生成并进入系统凭据存储。
9. 插件启用后会自动启动 `jiaotang-kb`；门户登记、凭据保存、首次验签和 MCP 连接四个阶段都完成后，才算真实接入。
10. 管理员可在“成员管理”查看安装阶段和最近结果；若安装说明未读到，门户显示“未收到结果”。

本流程支持 WorkBuddy 的 macOS 与 Windows 宿主。其他本地 Agent 不再使用网站动态安装命令；需要接入时必须采用该宿主原生、可审查并签名的扩展机制。

管理员可在门户生成管理员 API Key：

```text
JIAOTANG_KB_ENDPOINT=https://kb.example.com
JIAOTANG_KB_TOKEN=<管理员凭据>
```

验证凭据：

```bash
curl -H "Authorization: Bearer $JIAOTANG_KB_TOKEN" \
  "$JIAOTANG_KB_ENDPOINT/v1/me"
```

检索知识：

```bash
curl -X POST \
  -H "Authorization: Bearer $JIAOTANG_KB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"小巨人 产业链", "limit":8}' \
  "$JIAOTANG_KB_ENDPOINT/v1/search"
```

获取一条命中文档的完整提取文本：

```bash
curl -H "Authorization: Bearer $JIAOTANG_KB_TOKEN" \
  "$JIAOTANG_KB_ENDPOINT/v1/documents/123"
```

查看当前账号调用统计：

```bash
curl -H "Authorization: Bearer $JIAOTANG_KB_TOKEN" \
  "$JIAOTANG_KB_ENDPOINT/v1/usage"
```

查询并下载最新版 Skills：

```bash
curl -H "Authorization: Bearer $JIAOTANG_KB_TOKEN" \
  "$JIAOTANG_KB_ENDPOINT/v1/skills/latest"
curl -L -H "Authorization: Bearer $JIAOTANG_KB_TOKEN" \
  -o project-assistant-skills.zip \
  "$JIAOTANG_KB_ENDPOINT/v1/skills/latest/download"
```

## 固定 API 协议

| 接口 | 方法 | 用途 |
|---|---|---|
| `/v1/me` | `GET` | 验证用户凭据并返回当前账号 |
| `/v1/search` | `POST` | 查询 `knowledge_content.sqlite3` 全文索引 |
| `/v1/lists/search` | `POST` | 按企业、标准项目、年度、批次和地区查询公示名单实体 |
| `/v1/policies/search` | `POST` | 按标准项目、地区、文件阶段、有效性和年度查询政策 |
| `/v1/projects/match` | `POST` | 按地区与企业特征匹配理论候选项目 |
| `/v1/admin/project-alias-candidates` | `GET` | 按文档影响量和申报风险返回别名主动学习队列 |
| `/v1/admin/project-aliases` | `GET/POST` | 管理员查询或确认项目别名纠错，并重算受影响文档 |
| `/v1/admin/metadata-evidence` | `GET` | 管理员查询逐字段匹配证据、置信度和复核状态 |
| `/v1/admin/policy-verification` | `GET/POST` | 管理员领取或提交政策官网核验结果 |
| `/v1/admin/policy-propagations` | `GET` | 查询政策同源文档的逐文档核验传播证据 |
| `/v1/documents/{id}` | `GET` | 读取命中文档的完整提取文本和来源 |
| `/v1/usage` | `GET` | 查询当前账号的调用总量、接口分布和最近记录 |
| `/v1/skills/latest` | `GET` | 获取最新版 Skills 的版本、哈希、说明和下载地址 |

所有 `/v1` 接口接受网站生成的 `Authorization: Bearer jtk_xxx` API Key。普通成员还必须通过已登记的 Ed25519 公钥逐请求签名；管理员豁免设备签名。原始资料与运行索引的上传边界见项目根目录 `docs/cloud-upload-scope.md`。

## 知识库索引

生产环境通过 `JIAOTANG_INDEX_DIR` 指向包含以下文件的目录：

- `knowledge_content.sqlite3`
- `knowledge_inventory.sqlite3`
- `policy_versions.sqlite3`

API 以只读方式打开全文索引，不再把数千份文档重复导入账号数据库。账号、Session、Token、调用记录和 Skills 版本仍保存在 `JIAOTANG_DATA_DIR/knowledge.db`。

全文索引同时维护 `public_list_entities` 名单实体表，以及文档的标准项目名称、地区、文件阶段、有效性、年度和批次字段。第二阶段还维护 `project_alias_corrections` 人工纠错表、`metadata_match_evidence` 匹配证据表和 `policy_verification_queue` 官网核验队列。同源政策由 `policy_document_clusters` 和 `policy_document_cluster_members` 组织，逐文档传播记录保存在 `policy_verification_propagations`。项目地图匹配只做候选召回；“当期可申报”仍须回到管理办法、申报通知和企业可靠资料逐项核验。

管理员可访问 `/admin/metadata-review` 打开“知识校准台”。别名队列综合受影响文档、名单实体、高风险政策角色和近期资料计分；政策队列综合入队优先级、文件阶段、有效性不确定性、标准项目映射、年度和下游影响计分。排序只决定展示优先级，不会自动确认别名或政策有效性。

同源簇优先按正式文号识别。无文号时，只有归一化标题完全一致，且标准项目、地区、年度一致的文档才会合并。不使用模糊标题相似度自动聚簇。核验后只同步簇内且核验原因相同的待办，并为每份目标文档单独保存传播证据。

已有全文索引可生成一个不覆盖原文件的结构化副本：

```bash
PYTHONPATH=. python3 scripts/upgrade_structured_knowledge_index.py \
  /path/to/knowledge_content.sqlite3 \
  --output /path/to/knowledge_content.structured.sqlite3
```

脚本先复制原索引，再补充字段、生成名单实体并执行 SQLite 完整性检查；只有验收新文件后才由管理员切换生产路径。

使用60条顾问场景金标准验收结构化索引：

```bash
PYTHONPATH=. python3 scripts/evaluate_structured_knowledge.py \
  --database /path/to/knowledge_content.structured.sqlite3
```

默认门槛为核心字段准确率不低于95%，名单、政策和项目地图的前五位命中率不低于90%。

管理员增量上传会把原始文件写入 `JIAOTANG_KNOWLEDGE_FILES_DIR`，对文本执行 SHA-256 查重、提取和临时索引校验，通过后原子替换全文索引。扫描件不在网站统一 OCR；用户应先由本地 Agent 完成 OCR，再上传可提取文本的 PDF、Markdown 或其他受支持文件。网站检测到扫描件时仅标记“需本地 OCR”，不调用第三方 OCR 服务。

## 内网并发验收

服务启动且管理员初始化后，可模拟 50 个成员自主注册、创建独立用户凭据并并发检索：

```bash
python3 scripts/load_test_portal.py \
  --base-url http://服务器内网地址:8100 \
  --users 50 \
  --requests-per-user 2
```

测试账号只用于隔离的验收环境。生产环境不得运行该脚本。

## 自动部署与生产冒烟测试

部署脚本会校验生产环境变量、创建时间戳备份、上传应用、重启服务、执行固定路由检查，并在失败时恢复应用文件：

```bash
export JIAOTANG_DEPLOY_HOST=root@服务器地址
export JIAOTANG_DEPLOY_KEY="$HOME/.ssh/jiaotang_kb_aliyun"
./scripts/deploy_production.sh
```

生产 Token 冒烟测试不会输出 Token，仅报告身份、检索、文档、调用统计和 Skills 状态：

```bash
export JIAOTANG_KB_ENDPOINT=https://knowledge.example.com
export JIAOTANG_KB_TOKEN=jtk_xxx
./scripts/smoke_test_production.sh
```

若当前网络无法直接建立公网 TLS，可在服务器上设置 `JIAOTANG_RESOLVE_IP=127.0.0.1` 后执行同一测试。

## 服务器部署前提

1. 域名 A 记录指向服务器公网 IP。
2. 阿里云防火墙开放 TCP `80` 和 `443`，SSH 仅用于管理员维护。
3. 使用 Nginx 反向代理 `127.0.0.1:8100`。
4. 使用 Let's Encrypt 或阿里云证书启用 HTTPS 后，才开放登录页面。
5. 服务器部署密钥可轮换；换电脑时追加新公钥，验证成功后再停用旧公钥。
6. 安装 `jiaotang-kb-health.timer` 每五分钟执行健康探测；失败记录进入 systemd journal。
7. 每日备份账号数据库、每周备份全文索引；阿里云磁盘快照负责原始资料目录的灾难恢复。可用 `JIAOTANG_BACKUP_INDEX=true` 手工强制执行索引备份。

## OSS 增量灾备

生产服务器每天 04:10 比对本地同步清单，仅上传新增或发生变化的原始资料与索引。周日同步额外生成一份带时间戳的索引快照。SQLite 文件上传前通过在线备份接口生成一致性副本，避免同步写入中的数据库文件。

服务器保留最近 12 份索引热回滚快照，超过窗口的快照按年月移入 `/var/backups/jiaotang-kb/index-snapshot-archive`。归档策略不永久删除文件；OSS 原始资料沿用 `production/knowledge`，生产索引位于 `production/index/current`，周期快照位于 `production/index/snapshots`。

所需环境变量：

```text
JIAOTANG_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
JIAOTANG_OSS_BUCKET=your-private-bucket
JIAOTANG_OSS_PREFIX=production
JIAOTANG_OSS_ACCESS_KEY_ID=通过服务器安全环境配置
JIAOTANG_OSS_ACCESS_KEY_SECRET=通过服务器安全环境配置
```

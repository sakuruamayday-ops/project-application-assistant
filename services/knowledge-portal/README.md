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
.venv/bin/pip install --require-hashes -r requirements.lock
export JIAOTANG_SETUP_KEY="$(openssl rand -hex 24)"
export JIAOTANG_SECURE_COOKIES=false
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
```

`requirements.in`、`requirements-test.in` 和 `requirements-build.in` 只用于人工维护顶层依赖；运行环境不得直接解析这些文件。`requirements.lock` 与 `requirements-test.lock` 固定全部传递依赖并逐制品绑定 SHA-256，前者用于生产，后者额外固定 pytest 等测试工具。`requirements-build.lock` 单独固定 pip、setuptools、wheel 及其传递依赖，只用于把锁内源码包预构建为 wheel，不进入生产应用环境。

## Python 依赖锁与离线 wheelhouse

依赖升级必须在 Python 3.12 环境中使用固定的 `uv 0.11.28`：

```bash
python scripts/compile_python_locks.py
python scripts/python_supply_chain.py lock-metadata-verify \
  --portal-dir .
```

生成后必须评审 `requirements.lock`、`requirements-test.lock` 和 `requirements-lock-metadata.json` 的差异。元数据把两个顶层输入、两份全传递锁和生成器身份绑定在一起；任何输入或锁的单边修改都会导致 CI 失败。该流程只解析依赖与生成哈希，不执行公共漏洞查询。

CI 使用 Python 3.12 构建两个 wheelhouse：

- 测试 wheelhouse 仅供同一流水线离线安装并执行测试，不发布。
- 生产 wheelhouse 作为 `portal-python312-linux-x86_64-wheelhouse` 制品发布，目录中只允许 wheel、由最终 wheel 重新生成的 `wheelhouse-install.lock`、`wheelhouse-manifest.json` 和 `wheelhouse-manifest.sha256`。同一制品还包含目录外的 `portal-production-dependency-release-record.json`，记录 GitHub Actions 的事件、分支、精确 commit、运行编号及依赖身份。

manifest 绑定应用锁、构建工具锁、最终 wheel 安装锁、Python ABI、操作系统、CPU 架构、制品精确文件集、大小和 SHA-256。生产安装必须从受控发布记录取得期望的 manifest SHA-256，不能只信任 wheelhouse 内部的摘要旁车：

```bash
EXPECTED_WHEELHOUSE_MANIFEST_SHA256=由受控发布记录注入
new_release/.venv/bin/python \
  new_release/scripts/python_supply_chain.py install \
  --lock new_release/requirements.lock \
  --build-lock new_release/requirements-build.lock \
  --wheelhouse new_release/wheelhouse \
  --expected-manifest-sha256 \
  "${EXPECTED_WHEELHOUSE_MANIFEST_SHA256}"
```

构建命令只接受 CPython 3.12。构建阶段先以 `--require-hashes` 下载应用锁和构建工具锁中的精确制品；只发布源码包的依赖在固定 builder 中使用 `--no-index --no-build-isolation` 预构建，并禁用本地原生扩展编译。源码包如产出平台相关 wheel 会失败关闭；crcmod 因此使用其官方纯 Python 回退实现，避免编译器、临时路径和本机 ABI 造成不可复现 wheel。构建完成后再根据最终 wheel 重建逐 wheel 哈希安装锁。生产安装固定使用 `--no-index --require-hashes --only-binary=:all: --no-deps`。因此生产主机既不会访问包索引，也不会重新选择版本或构建源码包；锁、ABI、manifest、wheel 缺失或不一致时均失败关闭。构建 wheelhouse 是唯一允许访问包索引的阶段。

受控发布在组装源码和 wheelhouse 后应执行：

```bash
python scripts/python_supply_chain.py verify \
  --lock requirements.lock \
  --build-lock requirements-build.lock \
  --wheelhouse wheelhouse \
  --expected-manifest-sha256 "${EXPECTED_WHEELHOUSE_MANIFEST_SHA256}" \
  --identity-output dependency-build-identity.json
```

随后把 `dependency_identity_sha256`、`dependency_lock_sha256`、`dependency_build_lock_sha256`、`wheelhouse_install_lock_sha256`、`wheelhouse_manifest_sha256`、`wheelhouse_content_identity_sha256` 和依赖发布记录哈希纳入发布来源／构建身份。生产部署只接受 `push` 到 `refs/heads/main` 且 `source_commit` 与部署源码完全相同的 CI 记录；PR wheelhouse 不能直接部署。这样源码 commit 相同但应用锁、构建工具锁、最终安装锁或 wheelhouse 不同的构建也会被识别为不同产物。

首次打开 `/setup`，输入初始化密钥并创建管理员账号。
管理员可在控制台创建团队账号；成员首次登录后应立即修改初始密码。

## 管理员 Kindle 阅读库

`/admin/kindle` 提供仅管理员可见的个人 Kindle 阅读库，包含电子书上传与软删除、元数据、Calibre 格式转换、30分钟4位取书码、`My Clippings.txt` 书摘、阅读统计、回本计划和壁纸。Kindle 固定访问 `/k`，页面为无 JavaScript 的低带宽 HTML；连续输错取书码会触发临时限速。

电子书、转换文件、封面和壁纸保存在 `JIAOTANG_DATA_DIR/kindle-library`，随账号数据库一并纳入生产备份。生产主机需要提供 `ebook-convert`；正式部署脚本会在缺失时安装 Calibre。

## Agent 接入

普通成员：

1. 在门户点击“复制给 Agent”。
2. 把复制的文字粘贴到本地 Agent。
3. 门户先向 Agent 提供 `jiaotang-agent-install/v1` 审查说明。Agent 必须先确认当前宿主是 WorkBuddy 5 或更高版本。审查阶段只包含签名 WorkBuddy 插件包、联网地址、本地改动、凭据保存方式和回滚方法，不包含 `bootstrap_url`，也不包含任何动态命令字段。
4. 用户核对审查结果后，必须回到门户点击“我已审查，继续安装”；门户此时才开放一次性 `bootstrap_url`，并生成明确授权 WorkBuddy 应用内市场安装的第二阶段提示。
5. 第二阶段协议提供与本次安装码及已审查发布包绑定的一次性受限下载地址，无需复用浏览器 Cookie；用户核验 SHA-256 与 Ed25519 签名，解压后在 WorkBuddy 内通过 `/plugin marketplace add` 和 `/plugin install` 完成安装。
6. WorkBuddy 5.3.5 从签名插件根目录 `.mcp.json` 加载 `jiaotang-kb`。未绑定时本地 MCP 只暴露 `jiaotang_kb_setup` 与无敏感信息状态工具；一次性 `bootstrap_url` 仅作为 setup 工具参数使用，不写入普通配置。成功后长期凭据进入系统安全存储，插件切换为远端知识库代理。
7. 只有服务器记录到首次成功的签名 MCP 连接，门户和安装器才会报告“安装成功”；此前统一显示“安装未完成”。
8. 设备登记使用“预登记—系统凭据保存与回读—本机签名激活”两阶段事务。预登记不创建有效 Token、设备绑定或公钥；只有凭据回读成功后，服务器才在单个事务中激活。
9. 同一预登记和激活请求必须幂等；凭据保存失败只留下会过期的预登记意图，不形成半绑定。
10. 安装码、API Token 和设备私钥不得显示、复制到普通聊天回复或写入普通配置；设备私钥只在本机生成并进入系统凭据存储。
11. 插件启用后会自动启动 `jiaotang-kb`；门户登记、凭据保存、首次验签和 MCP 连接四个阶段都完成，且 `tools/list` 实际枚举出 `knowledge_search`、`knowledge_document` 和 `knowledge_service_status` 并成功调用任一只读工具后，才算真实接入。
12. 登录用户可在 Skills 中心打开一键诊断页，查看正式包摘要、Ed25519 签名状态、脱敏登记 URL 与四阶段状态；诊断页不包含安装码、Token、私钥或完整设备公钥。
13. 管理员可在“成员管理”查看安装阶段和最近结果；若安装说明未读到，门户显示“未收到结果”。

自动两步安装只适配 WorkBuddy 5 的 macOS 与 Windows 宿主。其他 Agent 不进入本流程，也不得使用 WorkBuddy 插件包。

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

## 项目算法包更新

项目算法包由服务端统一加载。团队通过现有 REST API 与 MCP 使用，无需因规则更新重新下载 Skills，也无需增加新的 MCP 工具。

正式规则采用“稳定管理办法＋年度通知＋属地覆盖层”。仅将已经核验为现行、保存官方链接和原文条款、并完成人工确认的规则写入 `references/project-algorithm-rule-sources`，随后执行：

```bash
.venv/bin/python scripts/manage_project_algorithm_packs.py generate-all
.venv/bin/python scripts/validate_project_algorithm_packs.py
```

系统只记录检索命中的标准项目与简称，不保存 REST 或 MCP 原始查询正文。管理员可根据近7日真实团队查询频率查看路由型项目补齐顺序，也可输出独立队列：

```bash
.venv/bin/python scripts/manage_project_algorithm_packs.py priority-queue \
  --database /srv/jiaotang/data/portal.sqlite3 \
  --days 7
```

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

部署脚本不会再原地覆盖应用，也不会读取或整理历史部署备份。每次部署都会写入唯一且不可覆盖的 `/opt/jiaotang-kb-release-slots/<deployment_id>`，完成离线校验后原子切换 `/opt/jiaotang-kb-runtime/current`，并让单一 `previous` 指针保留上一个运行槽。健康或固定路由校验失败时只把 `current` 指回 `previous`；失败的新槽保留待审，不自动删除：

```bash
export JIAOTANG_DEPLOY_HOST=root@服务器地址
export JIAOTANG_DEPLOY_KEY="$HOME/.ssh/jiaotang_kb_aliyun"
export JIAOTANG_WHEELHOUSE_DIR=/受控下载目录/portal-production-wheelhouse
export JIAOTANG_DEPENDENCY_RELEASE_RECORD=/受控下载目录/portal-production-dependency-release-record.json
export JIAOTANG_EXPECTED_WHEELHOUSE_MANIFEST_SHA256=由对应main分支CI记录独立核对的摘要
./scripts/deploy_production.sh
```

部署脚本先在本地核验 wheelhouse、外部绑定摘要、依赖身份和 main 分支 CI 发布记录，再把源码、锁、wheelhouse 和发布记录一起写入新槽。服务器安装阶段设置 `PIP_NO_INDEX=1`，只从该槽内的 wheelhouse 安装；生产主机不会访问 PyPI。若服务器启用了私有 Kindle 管理扩展，部署只会把 `app/kindle_library.py`、对应两个页面模板和私有导航模板四个白名单文件复制到新槽，并生成只含路径、大小和 SHA-256 的 `private-overlay-manifest.json`；其身份摘要会进入 `/build`，私有内容不会回传本地或进入公开仓库。

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
6. 安装 `jiaotang-kb-health.timer` 每五分钟执行综合健康探测；门禁覆盖 failed unit、索引状态新鲜度、磁盘阈值以及索引 current/previous 世代一致性。关键 oneshot 和门户服务通过 `OnFailure` 写入结构化失败状态。
7. 既有日常备份配置和历史备份保持原样；本轮部署不会启动备份任务，也不会读取、盘点或处置备份目录。
8. 门户主进程只读取 `/etc/jiaotang-kb-app.env`。OSS 发布和索引刷新只读取 root-only 的 `/etc/jiaotang-kb-ops.env`，门户进程不得继承 AccessKey、STS Token 或索引发布签名密钥。

## OSS 原子索引发布

旧式服务器相对路径 OSS 同步已永久停用，`jiaotang-kb-oss-sync.timer/path` 在部署时会被禁用。本轮不安装或启用任何快照保留、历史对象扫描、暂存迁移或部署备份整理单元，避免触及明确排除的存量处置流程。

生产索引以不可变世代发布：

```text
production/index/releases/<release_id>/<白名单文件>
production/index/releases/<release_id>/release.json
production/index/releases/<release_id>/release.sig
production/index/current.json
```

每个 release 都绑定文件名、大小、SHA-256 和 CRC64。上传前后复算摘要，OSS 对象禁止覆盖，并执行下载抽验。全部文件和签名清单核验通过后，才使用 `If-Match` 或首次写入条件原子切换 `current.json`；并发发布发生 CAS 冲突时失败，不覆盖后来者。

服务器下载并验签完整 release 后保存到 `JIAOTANG_INDEX_DIR/releases/<release_id>`，通过 `current` 符号链接一次切换整代文件，上一代由 `previous` 标识。若服务器仍使用既有根索引文件，首次 bootstrap 只在根文件与签名 release 逐项一致时建立只读身份，不移动、替换或隔离根文件；此兼容模式拒绝切换到不同 release，直至另行授权迁移。切换后索引或应用健康检查失败时自动回滚 previous 并再次复检。OSS 不可用时默认失败关闭；只有运维人员显式运行 `jiaotang-kb-refresh-index --allow-stale`，且本地 current 仍通过完整性校验时，才允许临时使用旧缓存。

索引 release 使用 HMAC-SHA256 认证。首次迁移会在 root-only 运维环境文件中生成至少 32 字节的随机密钥。轮换时：

1. 把旧的 `JIAOTANG_OSS_RELEASE_SIGNING_SECRET` 追加到逗号分隔的 `JIAOTANG_OSS_RELEASE_VERIFY_SECRETS`。
2. 写入新的 `JIAOTANG_OSS_RELEASE_SIGNING_SECRET`。
3. 发布并验证新 current。
4. 仅在 current、previous 和保留 release 都不再引用旧 key ID 后，才移除旧验签密钥。

不得先删除旧密钥，否则 previous 自动回滚会因无法验签而失效。

所需环境变量：

```text
JIAOTANG_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
JIAOTANG_OSS_BUCKET=your-private-bucket
JIAOTANG_OSS_PREFIX=production
JIAOTANG_OSS_AUTH_MODE=static
JIAOTANG_OSS_ACCESS_KEY_ID=通过服务器安全环境配置
JIAOTANG_OSS_ACCESS_KEY_SECRET=通过服务器安全环境配置
JIAOTANG_OSS_RELEASE_SIGNING_SECRET=至少32字节的root-only随机密钥
```

`JIAOTANG_OSS_AUTH_MODE` 也支持 `sts` 和 `ram-role`。STS 必须同时提供 `JIAOTANG_OSS_SECURITY_TOKEN`；RAM Role 必须提供受控元数据地址 `JIAOTANG_OSS_RAM_ROLE_AUTH_HOST`。门户主进程环境中不得出现这些变量。

脚本不会自动创建 RAM Role、访问日志、Inventory、跨区域复制或其他可能收费的云资源。可运行 `check_oss_governance.py` 只读检查版本控制、加密、职责分离、访问日志、Inventory 和 CRR，再由管理员决定是否启用。

本轮代码不会读取、盘点、移动、隔离、恢复验证或删除既有历史对象、既有暂存和历史部署备份；这些工作保留到主人另行授权的“清单—隔离—恢复验证—确认处置”任务。同样，本说明不代表已经完成从备份恢复到临时实例的实际演练，也不据此宣称已取得 RPO/RTO 实测值。

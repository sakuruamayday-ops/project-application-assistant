# API与MCP配置指南

本指南供首次安装“企业全生命周期助手”的团队成员使用。模型、企业数据、专利数据、浏览器、OCR和文档工具均使用用户自己的账号与宿主平台能力，并按相应平台要求完成配置。

## 零、普通成员只做一次复制

普通成员无需运行命令、填写 Token 或修改 MCP 配置：

1. 登录团队门户，进入“连接我的 Agent”。
2. 点击“复制给 Agent”。
3. 将复制的整段文字粘贴到当前本地 Agent 对话框。

Agent 会读取十分钟有效的一次性引导清单，识别 macOS 或 Windows 以及当前宿主，生成本机 Ed25519 设备密钥，完成 MCP 配置并验证连接。私钥不会上传；macOS 保存到系统钥匙串，Windows 使用当前用户 DPAPI 加密保存。

当前内置适配 WorkBuddy、Codex、Claude Code 和通用 MCP 配置。其他 Agent 只要具备本地命令执行、用户配置文件写入和 stdio MCP 能力，也可按引导清单自动完成。纯云端 Agent 不属于此接入范围。

管理员账号不执行单设备限制，仍可在门户使用管理员 API Key。

## 一、团队云端知识API

### 适用Skill

`local-knowledge-retrieval`、`project-application-assistant`、`policy-retrieval`、`project-matching`、`project-feasibility`、`peer-benchmarking`、`industry-positioning`、12个项目类别Skill和`enterprise-panorama-analysis`。

### 配置步骤

1. 登录团队门户并完成团队成员身份验证。
2. 点击“复制给 Agent”，把文字发送给需要使用知识库的本地 Agent。
3. Agent 自动登记本机公钥、保存本机私钥、配置 `jiaotang-kb` MCP，并调用 `/v1/me` 验证。
4. Agent 报告“配置成功”后即可直接检索；成员不应接触或保存 Token、私钥和签名请求头。

知识服务还提供三个结构化只读接口：

- `/v1/lists/search`：查询公示名单中的企业、项目、年度、批次和地区。
- `/v1/policies/search`：按标准项目名称、地区、文件阶段和有效性查询政策。
- `/v1/projects/match`：从项目地图召回理论候选项目，不表示项目当前开放或企业已经符合。

管理员还可以通过 `/v1/admin/project-aliases` 维护人工确认别名，通过 `/v1/admin/metadata-evidence` 查看命中证据，并通过 `/v1/admin/policy-verification` 完成官方网站核验。人工确认操作会先生成索引快照，再原子更新结构化索引。

### 权限边界

- 普通成员只能读取团队云端知识、查询自己的调用记录和下载最新版Skills。
- 普通成员账号同一时间只能存在一组有效设备公钥。仅复制 Token 或静态设备 ID 无法调用。
- 每个请求都必须包含短时设备签名和一次性 nonce；签名过期、伪造或重放会被拒绝。
- 换机时先在门户执行“更换绑定设备”，旧 Token、旧 OAuth 授权、旧设备公钥和未使用安装码立即失效，再把新的“一键配置”发送给新设备 Agent。
- 成员自行维护的地区政策保存在本地工作区 `project-rules/`，不会写入或覆盖团队云端知识库。
- 云端资料上传、索引更新和Skills发布仍由网站管理员执行。
- 云端知识服务是REST API，不是MCP地址，不要直接填入 `mcpServers`。

### 个人偏好接口

普通用户不需要手工调用以下接口，网站和首次配置向导会自动处理。此处仅供管理员排障：

个人偏好与知识库使用同一个个人访问凭据：

- `GET /v1/preferences`：读取当前结构化偏好和修订号。
- `PUT /v1/preferences`：提交完整偏好，并通过 `base_revision` 防止跨设备静默覆盖。
- `GET /v1/preferences/history`：查看个人历史版本。
- `POST /v1/preferences/undo`：撤销上一版并生成新修订。
- `POST /v1/preferences/reset`：恢复官方默认并保留审计历史。

本地优先运行 `first-run-configuration/scripts/manage_preferences.py sync`，不要手工拼接请求。偏好文件不保存Token、密码、客户资料，也不能关闭来源核验、政策有效性和财务真实性等保护规则。

## 二、MCP通用配置

优先使用宿主平台已经提供的原生工具。只有确实缺少企业查询、专利检索或浏览器能力时再增加MCP服务器。

### stdio型MCP

在宿主平台的MCP配置区域增加以下结构，并将占位符替换为供应商官方启动命令。不同平台字段名可能略有差异，以宿主官方说明为准。

```json
{
  "mcpServers": {
    "provider-name": {
      "command": "<官方MCP启动命令>",
      "args": ["<官方参数>"],
      "env": {
        "PROVIDER_API_KEY": "${PROVIDER_API_KEY}"
      }
    }
  }
}
```

实际密钥可按宿主平台要求写入系统环境、平台凭据或配置文件。

### HTTP型MCP

只有供应商明确提供MCP HTTP地址时使用：

```json
{
  "mcpServers": {
    "provider-name": {
      "type": "http",
      "url": "https://供应商提供的MCP地址",
      "headers": {"Authorization": "Bearer ${PROVIDER_MCP_TOKEN}"}
    }
  }
}
```

不要把普通REST API地址误填成MCP地址。焦糖知识库普通成员也不要手工采用此静态 Header 示例；设备签名由门户安装的本地 `jiaotang-kb` 代理逐请求生成。

### MCP验证步骤

1. 保存配置并完全重启宿主平台。
2. 打开平台的MCP状态页或工具列表，确认服务器显示已连接。
3. 只调用无参数的状态工具或最小只读查询。
4. 使用一家非敏感企业、一个公开专利号或一个公开政府网页验证返回结构。
5. 检查调用额度、超时和错误信息后再处理客户任务。
6. 连接失败时禁用该MCP并执行Skill降级路径，不得补造返回结果。

## 三、天眼查MCP

### 适用Skill

`enterprise-profile`、`enterprise-panorama-analysis`、`local-knowledge-retrieval`，用于企业主体分诊、现名与曾用名、工商变更、当前登记地区和关联主体发现。

### 操作步骤

1. 通过天眼查官方提供的合法MCP入口完成授权，凭据只保存在宿主安全配置中。
2. MCP连接成功后，在统一向导中确认 `TYC_MCP_READY=true`，不把Cookie、Token或授权Header写入Skill。
3. 使用一家非敏感企业串行验证主体搜索、基本工商、登记信息、工商变更和历史登记。
4. 记录实际可用工具和返回字段；不得把一次成功描述为永久免费或无限调用。
5. 批量身份补全采用串行、缓存、指数退避和断点续传。出现429、418或其他限流时停止并记录实际响应。
6. 天眼查用于当前企业身份和变更分诊，不覆盖主管部门名单中的认定年度、批次、状态和认定时地区。

## 四、企查查API或MCP

### 适用Skill

`enterprise-profile`、`enterprise-panorama-analysis`，并为项目匹配、可行性和知识产权评估提供企业事实。

### 操作步骤

1. 阅读 `docs/config/qcc.md`，通过企查查官方或合法授权入口取得个人API Key。
2. 在用户环境或宿主安全凭据中设置 `QCC_API_KEY`。
3. 按企查查或连接器官方说明添加MCP；如果只有REST API，则使用合法连接器或自建适配器，不把REST地址冒充MCP。
4. 默认只开放企业查询，不开放修改、导出全库或超出授权范围的能力。
5. 使用一家非敏感企业验证名称、统一社会信用代码、登记状态和授权字段。
6. 企查查不可用时，回退到用户材料和政府公开来源；不得用过期缓存补造企业现状。

## 五、专利数据API或MCP

### 适用Skill

`patent-data-foundation`、`patent-search-core`、`patent-claim-analysis`、`patent-similarity-search`、`patent-fto-analysis`、`patent-direction-planner`、`patent-layout-planning`和`patent-benchmark-landscape`。

### 操作步骤

1. 选择具有合法检索和输出权限的专利数据供应商或官方公开数据源。
2. 确认许可地域、字段范围、批量限制、同族数据、法律状态和权利要求全文权限。
3. 按供应商说明配置API或MCP。建议在安全凭据中统一使用：

```text
PATENT_DATA_PROVIDER=<供应商标识>
PATENT_API_ENDPOINT=<供应商REST地址，仅REST适配器读取>
PATENT_API_KEY=<个人或团队合法凭据>
```

4. 使用一个公开专利号验证申请号标准化、公开文本、授权文本、法律状态和同族字段。
5. 只有摘要时不得输出权利要求保护范围、FTO或稳定性结论。
6. 供应商不可用时可以根据用户提供的专利文件分析，但必须明确当前检索层缺失。

## 六、浏览器与Playwright MCP

### 适用Skill

`web-task-operator`、`third-party-data-indexing`、动态政策检索和登录后企业数据查询。

### 操作步骤

1. 先检查宿主是否已有浏览器能力；已有时无需重复安装MCP。
2. 缺少时，仅从宿主平台或浏览器MCP项目的官方渠道安装。
3. 按官方启动命令添加stdio型MCP，不在配置中写网站账号密码。
4. 打开目标网站登录页后，由用户亲自输入密码、扫码或完成验证码。
5. Agent只读取业务页面，不读取Cookie、Local Storage、密码库或认证Header。
6. 用一次搜索、筛选和单页读取验证能力；批量任务再逐步增加页数和间隔。
7. 遇到验证码、付费限制、限频或访问拒绝立即停止，不绕过访问控制。

## 七、企策顾问

`third-party-data-indexing` 为实验性能力，默认关闭。

1. 用户在正常浏览器中打开企策顾问并亲自登录，优先扫码。
2. 使用 `web-task-operator` 读取列表、详情和公开附件。
3. 首次只导出一页脱敏业务数据，确认字段、去重键和网站允许的频率。
4. 不向Agent发送Cookie、完整cURL、Authorization或CSRF令牌。
5. 企策顾问数据只作项目发现线索；正式条件、日期、金额和名单回政府原文核验。

## 七、政府网页检索

`policy-retrieval`、`project-rule-manager`和项目类别Skill优先使用宿主浏览器或官方搜索能力，不要求专用API Key。

1. 设置用户默认省、市、区县。
2. 优先访问政府门户、主管部门和当期通知原文。
3. 保存标题、文号、发布日期、主管部门、URL和正文位置。
4. 将用户自行维护的规则保存到本地 `project-rules/`。
5. 搜索未命中只能写“当前检索层未命中”。

## 八、本地OCR

扫描件OCR由用户本地Agent完成，网站不统一配置OCR密钥或服务。

1. 优先使用宿主已有OCR能力。
2. 缺少时按 `docs/config/paddle-ocr.md` 在用户电脑安装PaddleOCR或配置用户自己的OCR服务。
3. 输出可检索PDF，或输出Markdown加原文件名和页码映射。
4. 抽样复核企业名称、序号、金额、日期和表格列。
5. 完成OCR后再上传网站；直接上传纯扫描件只会标记“需本地OCR”。

## 九、PDF、Word和Excel

通用PDF、Word、Excel、PowerPoint工具不随本技能包分发。用户从宿主平台官方渠道安装。

- `enterprise-panorama-analysis` 可使用宿主PDF能力生成报告。
- 包内渲染脚本只是确定性后备方案，不代替宿主通用文档工具。
- 缺少PDF能力时先输出HTML或Markdown，不声称PDF已经生成。

## 十、首次配置检查

1. 云端 `/v1/me` 返回当前英文账号。
2. 云端测试检索能返回原文件和文档ID。
3. 本地 `project-rules/` 可以创建规则、来源和版本目录。
4. 企查查或企业数据工具完成一次非敏感查询。
5. 专利业务需要时完成一个公开专利号测试。
6. 浏览器能力完成一次公开政府网页读取。
7. 本地OCR完成一页扫描件抽样。
8. 宿主PDF能力能够生成并重新打开测试报告。

任一可选能力未配置时，Skill必须说明降级范围。团队知识凭据建议使用网站自助连接测试或宿主安全凭据配置；供应商密钥不得写入Skill包、共享文档或Git。

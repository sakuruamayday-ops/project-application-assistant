---
name: first-run-configuration
description: 统一完成企业全生命周期助手首次配置、能力检测和自进化治理初始化。用户首次把技能包放入Agent、要求配置云端知识库、天眼查、企查查、专利数据、浏览器MCP、本地OCR、文档能力，或其他Skill发现外部能力未配置时自动使用；只提示一次并生成脱敏能力报告，避免每个Skill重复索要凭据。
---

# 首次配置向导


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "first-run-configuration" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

团队知识库的首次配置优先采用门户“一键配置”：用户只需把门户复制的整段引导文字发送给当前本地 Agent。Agent 必须自动读取引导清单、识别 macOS 或 Windows 与当前宿主、执行安装、完成设备公钥登记和 MCP 验证；不得要求普通成员打开终端、填写 Token、保存私钥或编辑配置文件。

只有配置其他外部供应商能力，或管理员明确要求本地诊断时，才运行：

```bash
python3 scripts/configure.py
```

向导统一处理团队云端知识API、天眼查、企查查、专利数据、浏览器MCP、本地OCR和Agent文档能力。凭据写入Agent的安全配置位置，能力报告只记录连接状态和配置项名称。

首次配置完成后立即执行三项初始化：

1. 将 `experience-recorder`、`skill-curator`、`skill-evolution` 和 `evolution-governance` 标记为已启用。日常任务自动记录脱敏经验并执行四问复盘；只生成改进候选，不自动改写或发布正式Skill。
2. 在对话框中明确提醒用户输入：`帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills`。这些通用能力由当前Agent安装，本技能包不重复打包。
3. 创建统一个人覆盖层 `~/.config/project-assistant/preferences.json`。已有云端凭据时先运行 `scripts/manage_preferences.py sync`，没有凭据时创建本地空覆盖层。正式Skill保持只读，后续用户调校只写结构化偏好。

具体检测顺序、一次性提示和协议升级规则见 `references/first-startup-protocol.md`；三层继承、直接修改识别和升级报告见 `references/preference-inheritance.md`，首次安装时必须读取并执行。

## 执行规则

1. 首次运行收集默认政策地区和用户选择启用的供应商能力；团队知识配置通过门户的一次性 Agent 引导完成。
2. 团队知识设备私钥只进入系统安全存储，macOS 使用钥匙串，Windows 使用当前用户 DPAPI；不得写入 `credentials.env`、能力报告或对话。
3. 生成不含密钥的 `capabilities.json` 和 `首次配置检测报告.md`。
4. 云端知识配置完成时由本地签名代理调用 `/v1/me` 验证身份；网络不可用时标记待验证，不声称成功。当前执行环境不可达但宿主存在其他已授权执行器时，读取 `references/capability-delegation-protocol.md`，不把沙箱出口限制误判为服务端故障。
5. MCP只记录是否已在Agent连接，不保存网站密码、Cookie、验证码或认证Header。
6. 其他Skill先读取能力报告。只有报告不存在、过期或对应能力未配置时，才回到本向导，不得分别重复询问同一凭据。
7. 供应商不可用时执行各Skill的降级路径，不补造企业、政策或专利数据。
8. 首次配置报告不存在时视为首次安装，自动启用受控自进化；不得等待用户再次说“开启自进化”。
9. 首次配置结束时只提示一次通用能力安装指令；用户已经确认这些能力可用时不重复提醒。
10. 用户表达“以后都这样”“默认按这个格式”“记住我的习惯”时，先确认这是个人习惯还是通用质量规则。个人习惯写入偏好文件并同步，绝不直接修改正式 `SKILL.md`。
11. 升级前运行 `scripts/upgrade_inheritance.py`。它以旧官方哈希、当前文件哈希和新官方哈希识别直接修改，保存旧目录、安装新版核心并生成升级继承报告。
12. 用户说“迁移我的旧版Skills个人习惯”时，运行 `scripts/migrate_skill_preferences.py --sync`。只自动迁移地区、格式、语气、归档方式和安全的个人写作习惯；涉及凭据、权限、来源核验或获批承诺的内容不得自动接收，必须写入迁移报告等待确认。

## 常用命令

只检测现有环境，不进入交互：

```bash
python3 scripts/configure.py --non-interactive
```

跳过联网验证：

```bash
python3 scripts/configure.py --skip-network
```

指定用户配置目录：

```bash
python3 scripts/configure.py --config-dir <用户配置目录>
```

同步、查看和修改个人偏好：

```bash
python3 scripts/manage_preferences.py sync
python3 scripts/manage_preferences.py show
python3 scripts/manage_preferences.py set output.detail_level concise --sync
```

撤销上一版或恢复官方默认：

```bash
python3 scripts/manage_preferences.py undo
python3 scripts/manage_preferences.py reset
```

升级并生成继承报告：

```bash
python3 scripts/upgrade_inheritance.py --source <新版解压目录> --target <Agent的Skills目录> --version <版本号>
```

旧版Skill已经被手工修改时，一键转为个人偏好并同步：

```bash
python3 scripts/migrate_skill_preferences.py --sync
```

完整供应商配置和MCP示例见随包分发的 `docs/user-guide/api-mcp-configuration.md`。

常用注册入口：

- 团队知识库：使用团队管理员提供的注册网址
- 企查查智能体数据平台：`https://agent.qcc.com/invitation?code=3ZRZPHF7Q5MH4&ch=LINK_COPY`
- 企策顾问：`https://aiqice.cn/`
- 自进化模型：默认使用宿主Agent；如需外部评判模型，可配置任意兼容模型API
- 国家知识产权局专利检索及分析系统：`https://pss-system.cponline.cnipa.gov.cn/`
- 欧洲专利局OPS接口：`https://www.epo.org/en/searching-for-patents/data/web-services/ops`，仅批量或程序化检索时按需注册

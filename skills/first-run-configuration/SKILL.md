---
name: first-run-configuration
description: 统一完成企业全生命周期助手首次配置、能力检测和自进化治理初始化。用户首次把技能包放入Agent、要求配置云端知识库、天眼查、企查查、专利数据、浏览器MCP、本地OCR、文档能力，或其他Skill发现外部能力未配置时自动使用；只提示一次并生成脱敏能力报告，避免每个Skill重复索要凭据。
---

# 首次配置向导


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

宿主若只暴露 `run_code`，`skill`、`read`、`web_search`、校验器等工具均须在其中以 `await tools.<name>(...)` 调用，不得根级调用隐藏工具。先按 `SKILL.md` 或参考文档执行命令。脚本名或命令表示执行入口，不是预读源码许可；首次执行前不得读取 `scripts/**`、`examples/**`、`tests/**`、`*.example.*`、`package.json`，也不得列出技能目录。只有文档命令已经真实失败，且错误仍不足以确定调用契约时，才可定向读取与该失败直接相关的一个源码文件。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

共创独立客户端先读取本轮实际暴露的工具、已验签内置技能和连接状态。已有能力直接使用；只有当前任务确实需要且本轮缺失的能力才进入对应配置。团队知识门户负责账号知识服务连接，不承担客户端或 Skills 的重复安装。技能数量由当前验签清单和实际发现结果分别计算，不沿用旧版本常量。

团队知识库始终复用唯一的 `jiaotang-kb` MCP。服务端新增工具或统一分析入口时，安装和升级只刷新原连接的工具列表，不创建第二个知识库 MCP，不重新索要凭据。

只有配置其他外部供应商能力，或管理员明确要求本地诊断时，才运行：

```bash
python3 scripts/configure.py
```

向导统一处理团队云端知识API、天眼查、企查查、专利数据、浏览器MCP、本地OCR和Agent文档能力。凭据写入Agent的安全配置位置，能力报告只记录连接状态和配置项名称。

首次配置按以下顺序完成：

1. 将 `experience-recorder`、`skill-curator`、`skill-evolution` 和 `evolution-governance` 标记为可用。适用任务在最终对话中执行一次四问并形成脱敏经验候选；没有对应授权时不写入持久记忆、审计日志或知识库，也不自动改写或发布正式Skill。
2. 先检查本轮工具目录。`jiaotang-kb` 已存在时实际调用 `knowledge_service_status` 或等价状态工具；当前任务需要知识库但工具缺失时，才在已授权范围内刷新连接。连接仍失败时明确报告受影响能力，其他不依赖知识库的工作继续。
3. Word、PDF、Excel、PPT、OCR 和联网检索等能力以本轮可调用工具为准。已内置或已可调用时不得要求用户重复安装；确实缺失时只提示对应的一项配置或替代路径。
4. 只有用户明确授权保存长期个人习惯时才创建或更新 `~/.config/project-assistant/preferences.json`。偏好同步或备份失败只影响长期习惯持久化，须提示用户，但不得阻塞本轮业务执行。正式Skill保持只读。

具体检测顺序、一次性提示和协议升级规则见 `references/first-startup-protocol.md`；三层继承、直接修改识别和升级报告见 `references/preference-inheritance.md`，首次安装时必须读取并执行。

## 执行规则

1. 首次运行只收集当前任务必需且尚未具备的设置；本轮工具已经证明可用的能力不重复配置。
2. 团队知识服务使用当前登录用户的个人Bearer Token。Token只写入当前宿主的安全凭据存储，不得写入公共代码、能力报告、普通日志或最终回复。
3. 生成不含密钥的 `capabilities.json` 和 `首次配置检测报告.md`。逐项区分工具已列出、状态调用成功、业务读取成功和完整流程成功；保留本轮实际失败及恢复经过，不能因随后成功就写全部调用无错误。输入编号和覆盖范围按实际读取内容列示，不猜测编号区间。只读诊断不触发安装、配置写入或偏好初始化。
4. 云端知识配置完成时实际调用`knowledge_service_status`，只有返回`connected: true`才视为完成；网络不可用时标记待验证，不声称成功。当前执行环境不可达但宿主存在其他已授权执行器时，读取 `references/capability-delegation-protocol.md`，不把沙箱出口限制误判为服务端故障。
5. MCP只记录是否已在Agent连接，不保存网站密码、Cookie、验证码或认证Header。
6. 其他Skill先看本轮工具目录和实际调用结果，再将能力报告作为历史快照参考。报告不存在或过期本身不触发向导；只有任务所需能力确实缺失时才回到对应配置，且不得重复询问已提供的凭据。
7. 供应商不可用时执行各Skill的降级路径，不补造企业、政策或专利数据。
8. 首次配置报告不存在不等于能力缺失，也不自动触发配置。用户明确进入首次配置时可以写入本次能力检测报告；持久偏好、经验日志和知识库仍分别遵守各自授权。
9. 只有当前任务需要知识库时，尚未通过运行时工具验证的连接才保持该能力待验证；它不阻塞纯本地文档或其他不依赖知识库的工作。用户已经确认对应能力可用时不重复提醒。
10. 用户表达“以后都这样”“默认按这个格式”“记住我的习惯”时，先确认这是个人习惯还是通用质量规则。个人习惯写入偏好文件并同步，绝不直接修改正式 `SKILL.md`。
11. 升级前备份原技能目录；独立客户端的连接配置由客户端连接管理器维护，通用 Agent 只有在用户明确修改连接时才更新 `jiaotang-kb` 条目并保留其他 MCP。失败时恢复技能目录和本次实际改动的配置，并报告失败阶段。
12. 用户说“迁移我的旧版Skills个人习惯”时，运行 `scripts/migrate_skill_preferences.py --sync`。只自动迁移地区、格式、语气、归档方式和安全的个人写作习惯；涉及凭据、权限、来源核验或获批承诺的内容不得自动接收，必须写入迁移报告等待确认。
13. 用户已授权且范围未变化的配置或检测动作直接继续，不重复请求确认；付款、对外提交、权限扩大和隐私边界变化仍须按宿主规则确认。

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

用户已明确授权保存长期偏好时，才随首次配置创建个人覆盖层：

```bash
python3 scripts/configure.py --non-interactive --initialize-preferences
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

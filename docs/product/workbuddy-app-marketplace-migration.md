# WorkBuddy 应用内插件市场迁移

状态：V1.4.5 已实施，用户安装收敛为一次复制粘贴。

## 决策

- 用户安装包不再包含或启动 macOS `.command`、Windows `.cmd`、`.ps1` 固定安装器。
- macOS 与 Windows 共用一个跨平台 WorkBuddy 插件市场 ZIP，不再生成或维护系统专用版本。
- 客户端不调用 WorkBuddy 外部 CLI，不检测 WorkBuddy 进程，也不要求退出 WorkBuddy。
- 用户登录门户后点击“一键安装”，只需向 WorkBuddy 粘贴一段完整指令。
- 该指令在 Agent 授权范围内完成以下操作：

```text
安装或更新 49 项 Skills
启用失败放行的最小行为 Hook
只替换 mcpServers.jiaotang-kb 并保留其他 MCP
重载 WorkBuddy 一次
枚举三个知识工具并调用 knowledge_service_status
```

- 公共 WorkBuddy 包只包含市场清单、插件清单、49 项 Skills、最小行为 Hook、必要参考资料和业务脚本。个人 Token 不进入公共包。

## V1.4.5 正式发布门禁

1. 使用已重签的 `skill-release-manager` 生成唯一 WorkBuddy 候选包；服务端发布通道仍校验候选包完整性和固定发布者。
2. 确认包内存在 49 项 Skills、市场清单、插件清单和最小行为 Hook，且最小 Hook 只声明 `UserPromptSubmit` 与 `Stop`。
3. 确认插件声明 `mcp_configuration_mode: user_remote_streamable_http`，不内嵌用户 MCP 配置或真实个人 Token。
4. 确认候选包没有旧本地知识库服务、启动器、便携运行时或用户侧逐轮哈希检查。
5. 门户端到端测试必须验证 Token 复用、只替换 `jiaotang-kb`、保留其他 MCP、一次重载和 `connected: true` 验收。

## 兼容性

既有历史包不会被远程修改。V1.4.5 安装指令会在处理前备份旧插件目录和用户 MCP 配置，更新或替换旧插件，只替换 `mcpServers.jiaotang-kb`，保留其他 MCP。

历史数据库中的 `macos`、`windows` 目标只作为兼容来源保留；服务端将其中最新的
WorkBuddy 签名包映射为统一 `workbuddy` 通道。旧平台下载 URL 使用临时兼容跳转，不再作为
新发布目标，也不在页面和管理器中展示。

## 下载权限边界

插件市场 ZIP 在用户登录后可以直接下载。当前没有改成匿名公开下载，是因为该 ZIP 是完整商业套件，包含 49 项技能、最小行为 Hook 和必要业务资料，并受账号与源码使用许可约束。公共 ZIP 不包含任何用户个人 Token。

如以后决定开放匿名下载，应把“公开 Skills 内容”和“登录后签发的知识库访问配置”拆成两层。知识库授权仍由登录页生成个人 Token，该调整属于授权与商业分发策略变化，不在 V1.4.5 安装简化范围内。

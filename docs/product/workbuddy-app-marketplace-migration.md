# WorkBuddy 应用内插件市场迁移

状态：已进入产品代码，等待下一次正式发布时同步升级并重签 `skill-release-manager`。

## 决策

- 用户安装包不再包含或启动 macOS `.command`、Windows `.cmd`、`.ps1` 固定安装器。
- 客户端不调用 WorkBuddy 外部 CLI，不检测 WorkBuddy 进程，也不要求退出 WorkBuddy。
- 用户下载并核验本地插件市场 ZIP，解压后在 WorkBuddy 内执行：

```text
/plugin marketplace add <解压目录>/jiaotang
/plugin install jiaotang-workbuddy-skills@jiaotang
/plugin enable jiaotang-workbuddy-skills@jiaotang
/reload-plugins
```

- 发布端仍须在隔离 `HOME` 与 `CODEBUDDY_CONFIG_DIR` 中使用真实宿主 CLI 完成
  `validate → marketplace add → install → enable → Skill 触发`。该 CLI 只用于发布回归，
  不进入用户安装流程。

## 下一次正式发布门禁

1. 修改并重签 `skill-release-manager`，使 WorkBuddy 套件生成器只输出签名市场 ZIP，
   不生成旁车安装器及其签名文件。
2. 重新生成 WorkBuddy macOS 与 Windows 候选包，确认归档中没有 `.command`、`.cmd`
   或 `.ps1` 安装入口。
3. 保留 `.codebuddy-plugin/marketplace.json`、插件清单、MCP 连接器、Ed25519 签名清单
   和逐文件 SHA-256。
4. 在 macOS 与 Windows WorkBuddy 内用斜杠命令完成真实安装、启用、更新、卸载和技能触发。
5. 只有正式发布指令到达后才能重签发布器、生成候选包、递增版本或部署生产。

## 兼容性

既有 V1.3.1.2 包不会被远程修改。新版客户端即使下载到含旧安装器的历史包，也只定位 ZIP
并显示 WorkBuddy 应用内市场指引，不会提取或执行旧安装器。

## 下载权限边界

插件市场 ZIP 在用户登录后可以直接下载，技术上没有“不能直接下载”的限制。当前没有改成匿名
公开下载，是因为该 ZIP 是完整商业套件，包含 49 项技能、共享运行时、Hooks 和 MCP 连接器，
并受账号、设备与源码使用许可约束。市面上可匿名下载的单技能通常以公开 Git 仓库或公共市场
发布，不包含焦糖的一次性 `bootstrap_url`、设备绑定和私有知识库访问能力。

如以后决定开放匿名下载，应把“公开 Skills 内容”和“登录后签发的知识库访问配置”拆成两层，
只公开不含凭据的签名插件市场包；设备绑定、`bootstrap_url` 和 MCP 授权继续要求登录。该调整
属于授权与商业分发策略变化，不能在本次安装方式修复中默认放开。

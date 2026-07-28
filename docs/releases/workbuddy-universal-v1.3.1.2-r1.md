# WorkBuddy 跨平台分发修订 V1.3.1.2-r1

这是企业全生命周期助手 V1.3.1.2 的分发修订，不是新的 Skills 内容版本。
49 项业务技能、知识库连接器、设备凭据协议和既有安装均未改变。

## 修复

- macOS 与 Windows 改用同一个 WorkBuddy 本地插件市场 ZIP。
- 移除包外 `.command`、`.cmd`、`.ps1` 固定安装器。
- 停用 WorkBuddy 外部 CLI、进程等待和运行锁。
- 安装与启用只在正在运行的 WorkBuddy 内通过 `/plugin` 完成。
- 保留门户 `bootstrap_url` 生成、复制和手工复制兜底。

## 正式候选

- 文件：`jiaotang-workbuddy-skills-V1.3.1.2-workbuddy-suite.zip`
- SHA-256：
  `81fe184d9bd0f1e9332a04bc10ab20c0a9db0c6d6231f0fa61922f166a53a482`
- 发布者指纹：
  `SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI`
- 插件级签名：通过
- 签名文件哈希：404 项通过
- 包外固定安装器：0
- 宿主状态：`manual-in-app-required`

## 安装

1. 下载并核对 ZIP 与 `SHA256SUMS.txt`。
2. 解压后完整保留 `jiaotang` 目录。
3. 在 WorkBuddy 中输入 `/plugin`。
4. 添加解压后的 `jiaotang` 本地市场。
5. 安装并启用 `jiaotang-workbuddy-skills@jiaotang`。
6. 从焦糖门户复制一次性 `bootstrap_url`，粘贴到插件敏感配置。
7. 新建会话并完成 Skills 清单、MCP 工具和知识检索验收。

## 兼容性

- 不强制既有用户更新。
- 不改变既有插件、设备绑定、系统凭据或 MCP 接入。
- 原 V1.3.1.2 Windows 资产保持不可变，仅作为历史证据保留。
- 本发布为独立非 Latest 分发修订，不替换 V1.3.1.2 内容 Release。

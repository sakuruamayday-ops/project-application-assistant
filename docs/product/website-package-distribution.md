# 网站安装包分发策略

状态：正式执行

更新日期：2026 年 7 月 28 日

## 产品入口

焦糖不再把原生 Skills Manager 或 PWA 管理器作为正式入口。知识门户的
“Skills → 版本与下载”是唯一正式分发面，负责展示当前版本、SHA-256、发布说明、
平台适配状态和下载按钮。

## 包型

| 包型 | 内容 | 用户选择 |
|---|---|---|
| 通用 Skills 包 | 49 项正式 Skills 与各自签名材料 | 宿主支持标准 Agent Skills，但不需要焦糖平台 Hooks 时使用 |
| 平台增强包 | 同一套 Skills，加该宿主官方支持的 Hooks、插件描述和 MCP 声明 | 希望获得完整约束、生命周期触发和知识库连接时使用 |

平台增强包已经包含通用 Skills。用户只安装一个包，不叠加安装。

## 当前发布矩阵

| 平台 | 官方能力基线 | 网站状态 |
|---|---|---|
| 通用 Agent Skills | `SKILL.md` 目录或导入机制 | 正式可下载 |
| WorkBuddy | 本地插件市场、Hooks、MCP | 跨平台增强包正式可下载 |
| TRAE | Skills 导入与 Hooks | 专用包适配中，先使用通用版 |
| Qoder | 用户级 Skills、IDE 与 CLI Hooks | 专用包适配中，先使用通用版 |
| 通义灵码 / Qoder CN | 用户级 Skills 与 Hooks | 等待版本门禁和实机验收，先使用通用版 |
| Kimi Code | 插件可声明 Skills、Hooks 与 MCP | 专用插件包适配中，先使用通用版 |
| Cherry Studio | Skills 与 MCP | 专用包适配中，先使用通用版 |

“适配中”不是可安装声明。网站不为这些平台生成占位 ZIP，也不显示平台专用下载按钮。

## 开放下载门禁

每个平台增强包必须同时满足：

1. 官方文档明确支持所使用的 Skills、Hooks、插件或 MCP 机制。
2. 包结构、配置字段和版本范围有固定校验器。
3. 安装前展示写入位置、联网域名、凭据类型和回滚方式。
4. 不使用外部 CLI、运行锁、动态命令或管理员权限绕过宿主安全边界。
5. 在对应真实宿主完成安装、升级、卸载、回滚和新会话触发验收。
6. 发布清单、逐文件 SHA-256 和发布者签名校验全部通过。

任一项未满足，网站只能显示“适配中”并提供通用版。

## 官方文档基线

- TRAE Skills：<https://docs.trae.ai/ide/skills>
- Qoder Hooks：<https://docs.qoder.com/extensions/hooks>
- 通义灵码 / Qoder CN Hooks：
  <https://help.aliyun.com/zh/lingma/qoder-cn/user-guide/hooks>
- Kimi Code Plugins：
  <https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html>
- Cherry Studio Skills：
  <https://docs.cherry-ai.com/docs/en-us/advanced-basic/skills>

平台版本与导入接口可能变化。每次开发专用包前重新核对官方文档，不能把本页记录当作永久兼容承诺。

## 兼容与回滚

- 本次只改变网站分发入口，不修改现有用户机器上的任何 Skills、插件、Hooks、MCP、
  设备绑定或系统凭据。
- WorkBuddy 使用 V1.3.1.4 跨平台统一包；本次将设备登记改为凭据保存后再激活的两阶段事务，并增加无敏感信息的一键诊断页，不改变 49 项业务技能内容。
- 原生客户端 v0.2.0 的 GitHub Release 不删除、不替换，只停止门户转发。
- 旧 `/skills-manager`、原生客户端下载和客户端手册地址统一跳转到
  `/skills#skills-downloads`。

# 焦糖 Skills 管理器 0.2.0

状态：已于 2026 年 7 月 28 日 11:22 北京时间完成 GitHub Release；
实际产物、审计证据与门户发布清单已独立复核。

正式发行记录：
https://github.com/sakuruamayday-ops/project-application-assistant/releases/tag/skills-manager-v0.2.0

Skills 管理器 0.2.0 是独立于企业全生命周期助手 Skills 版本的可选桌面客户端。
它不修改 V1.3.1.2 的 49 项 Skills、既有设备绑定、知识库凭据或已安装目录。
已在使用 PWA、通用 ZIP 或 WorkBuddy 插件的用户可以继续使用，无需强制安装本客户端。

## 本次能力

- 在 macOS 与 Windows 上扫描已安装的主流 Agent 平台。
- 对具备稳定用户级 Skills 目录的平台生成可审查计划并一键导入。
- WorkBuddy 继续使用同一个跨平台插件市场 ZIP，不再调用固定安装器或运行锁。
- 平台适配器可作为纯数据远程更新；更新包必须通过固定 Ed25519 公钥验签，并使用
  单调递增 sequence 阻止旧签名包回放降级。
- 通用 Skills 与 WorkBuddy 内容继续独立执行发布者公钥、签名清单和逐文件 SHA-256
  校验。桌面客户端本身不捆绑 Skills 内容。
- 扫描、下载验签、导入、回滚和适配器更新写入本地脱敏、哈希链审计日志。
- 已登记内容更新前建立同盘备份；回滚时当前内容进入 displaced 目录，不永久删除。

## 分发与系统提示

本版本采用 `user_authorized_unsigned` 分发：

- macOS 安装包不含 Developer ID 签名和 Apple 公证。用户需要在本机明确授权运行；
  企业策略仍可能拒绝例外。
- Windows 安装包不含 Authenticode 签名。用户需要在本机明确确认运行；
  Smart App Control、杀毒软件或组织策略仍可能阻断。
- 管理员权限只能处理本机文件权限，不能替代发布者证书，也不能消除未知发布者提示。
- 不提供关闭 Gatekeeper、SmartScreen、杀毒软件或企业安全策略的绕过命令。

## 兼容性

- macOS 与 Windows 桌面客户端使用同一套功能与远程适配器协议。
- 原有 PWA 继续作为无需安装的默认入口。
- 桌面客户端版本为 0.2.0，与 Skills V1.3.1.2 分开演进。
- 本次不发布新的 Skills 版本，也不要求 macOS Skills 用户更新。

## 发行资产

- macOS arm64：`Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-arm64.dmg`，SHA-256 `45311c298833d68650d8f52f7069aaae157288db7366d1c8c65e2a0b935ca869`
- macOS x64：`Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-x64.dmg`，SHA-256 `35433b834d60746f0328310bd9ba19e7c3470762ae9a591fb0eb59aed24953e7`
- Windows x64：`Jiaotang-Skills-Manager-0.2.0-unsigned-local-win-x64.exe`，SHA-256 `b1c855432062ca90cb2a449186d335c57c0ca64d1143dc8197e9f40087fcb140`
- Word 手册：`Jiaotang-Skills-Manager-0.2.0-User-Manual.docx`，SHA-256 `5c85a052a0f73e87dc47a0460c56fe47b4a79d851e95c2b460a2b0468fb2bb9e`
- 审计报告：`release-audit.json`，SHA-256 `c3906dc965d0e0240677c0a91790369f50553ecff1721abeb662845b6d75baab`
- 门户回填清单：`native-release.published.json`，SHA-256 `d5383ee2e19a17a667a49a75bb2bb5c650aa98292bafd531540495c7704467fe`
- 汇总校验：`SHA256SUMS.txt`，SHA-256 `eb9c992809a74045a7f276313c3858f48d56088e5bc8215e8e78e3575caf71c1`

门户仅在第二阶段提交复核文件名、大小与 SHA-256 后开放稳定下载地址。

# 焦糖 Skills 管理器 0.2.0

状态：待 GitHub Release 与门户回填验收完成后更新。

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

- `Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-arm64.dmg`
- `Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-x64.dmg`
- `Jiaotang-Skills-Manager-0.2.0-unsigned-local-win-x64.exe`
- `Jiaotang-Skills-Manager-0.2.0-User-Manual.docx`
- `SHA256SUMS.txt`
- `release-audit.json`
- `native-release.published.json`

GitHub Release 先生成不可变产物和实际 SHA-256。门户只在独立回填提交复核文件名、
大小与 SHA-256 后开放稳定下载地址。

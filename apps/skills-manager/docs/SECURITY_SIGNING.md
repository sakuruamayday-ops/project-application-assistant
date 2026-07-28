# 桌面发行信任模式与安全门禁

## 当前发布决策

在没有 Apple Developer ID 和 Windows Authenticode 证书的阶段，原生客户端采用显式的 `unsigned-local-authorization` 模式交付。安装包文件名、发行审计和界面都必须说明其没有平台发布者身份，需要用户在本机策略允许时主动授权。

HTTPS PWA `/skills-manager` 继续保留，适合不愿安装本地程序或设备策略禁止未知发布者应用的用户。未来取得证书后再启用 `signed` 模式；两种模式不得混用或共用含糊的产物名。

Skills 管理器同时校验两条互不替代的信任链：

1. 桌面应用信任链：`signed` 模式使用 macOS Developer ID、公证或 Windows Authenticode；`unsigned-local-authorization` 模式只记录本机例外，不声明发布者身份。
2. Skills 内容信任链：门户 HTTPS 来源、发布包 SHA-256、固定 Ed25519 发布公钥指纹、OpenSSH 签名，以及签名清单内逐文件 SHA-256。

应用通过系统验证，不代表下载的 Skills 一定可信；Skills 验签成功，也不能替代操作系统对应用安装程序的验证。本地授权模式只改变第一条链的信任声明，第二条链不得降级。

## 两种发行门禁

平台签名模式保持默认，必须显式提交发行物：

```bash
npm run release:verify -- --artifact dist/对应发行物
```

本地授权模式必须同时显式声明模式和产物；文件名必须包含 `-unsigned-local-`：

```bash
npm run release:verify:unsigned-local -- \
  --artifact dist/Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-arm64.dmg \
  --audit-output dist/release-trust-macos.json
```

校验成功后生成 `jiaotang-skills-manager-release-audit/v1` 审计文件，至少包含管理器版本、产物 SHA-256、字节数、校验模式和 `local-user-exception` 信任级别。该审计必须通过 `skills_content_scope` 明确记录“不捆绑、不验证 Skills 内容”；它只证明桌面客户端发行物状态，不得硬编码 Skills 已验签。跨平台合并审计另行记录随 Release 发布的 Word 用户手册文件名、大小和 SHA-256。默认 `signed` 门禁不会静默接受未签名文件。

## macOS

平台签名包必须：

- 使用 `Developer ID Application` 证书签署应用及全部嵌套可执行文件。
- 启用 Hardened Runtime，并使用 `build/entitlements.mac.plist`。
- 使用 Apple notary service 公证 DMG，公证成功后执行 staple。
- 在隔离属性存在的干净测试机上打开并完成一次安装、更新和回滚验证。

建议的发布环境变量由 CI 密钥库注入，不写入仓库：

- `CSC_LINK`
- `CSC_KEY_PASSWORD`
- `APPLE_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`
- `APPLE_TEAM_ID`

构建后门禁：

```bash
codesign --verify --deep --strict --verbose=2 "焦糖 Skills 管理器.app"
spctl --assess --type execute --verbose=4 "焦糖 Skills 管理器.app"
xcrun stapler validate "Jiaotang-Skills-Manager-0.2.0-mac-arm64.dmg"
npm run release:verify -- --artifact "Jiaotang-Skills-Manager-0.2.0-mac-arm64.dmg"
```

本地授权 macOS 包使用 `identity: null`、`hardenedRuntime: false` 和 `CSC_IDENTITY_AUTO_DISCOVERY=false` 构建，不主动执行应用级 ad-hoc 签名，也不能带 Developer ID。Apple silicon 的主 Mach-O 可能保留系统运行所需的 `adhoc,linker-signed` 标记；它没有 Authority、Team ID 或资源封印，不构成发布者签名。发行门禁验证 DMG 完整性，挂载后确认应用不能通过完整代码签名验证，并且不存在发布者身份。用户首次打开被阻止时，可到“系统设置 → 隐私与安全性”找到对应应用并选择“仍要打开”，随后完成本机认证。不得通过 `xattr -dr` 删除隔离属性，也不得关闭 Gatekeeper。

## Windows

平台签名安装器必须：

- 使用受信任的代码签名身份，例如受信 CA 证书或 Microsoft Artifact Signing，对主程序、辅助可执行文件和 NSIS 安装器签名；也可评估 Microsoft Store 分发。
- 固定发布者名称，持续使用同一证书主体；证书轮换要保留可审计记录。
- 使用 RFC 3161 时间戳，避免证书到期后历史签名失效。
- 在 Windows 发布机上使用 `signtool verify /pa /all` 与 PowerShell 双重验证。
- 在开启 Microsoft Defender 与 SmartScreen 的干净 Windows 10/11 环境完成安装、更新、回滚测试。

示例门禁：

```powershell
signtool verify /pa /all /v .\Jiaotang-Skills-Manager-0.2.0-win-x64.exe
Get-AuthenticodeSignature .\Jiaotang-Skills-Manager-0.2.0-win-x64.exe
npm run release:verify -- --artifact .\Jiaotang-Skills-Manager-0.2.0-win-x64.exe
```

`Status` 必须为 `Valid`。SmartScreen 还会参考发布者信誉；稳定的证书主体与持续签名发布有助于积累信誉，但不能承诺首次下载一定不出现提醒。不得把“关闭 Defender”或“忽略未知发布者”作为正式安装步骤。

本地授权 Windows 包使用 `signExecutable: false` 构建，保留图标和版本资源，但 PE 证书表必须为空。系统策略允许时，用户可在 SmartScreen 界面查看“更多信息”并明确选择继续运行。该操作不是 Authenticode 签名，也不会建立发布者信誉。

UAC 管理员授权只允许程序执行需要提升权限的操作。当前 NSIS 采用用户级安装，Skills 也写入用户目录，因此正常安装不以管理员权限为前提。Windows 11 Smart App Control 或企业策略可能完全禁止未签名应用，遇到这种情况应改用 PWA，不承诺管理员授权一定能够绕过。

## 本地授权边界

- macOS 用户可以在“隐私与安全性”中对某个未知开发者应用选择“仍要打开”，该操作会保存本机例外，但应用依旧没有 Developer ID 和 Apple 公证。
- Windows 在部分策略下允许用户从 SmartScreen 提示中选择继续运行；企业策略或 Smart App Control 可能完全禁止继续。
- 管理员权限适合安装系统级组件，不适合用来写入 `~/.agents/skills`、`~/.trae-cn/skills` 或 `%USERPROFILE%` 下的 Skills。此类用户级同步默认不提权。
- 本地授权包必须保留 `unsigned-local` 文件名、SHA-256 和发行审计，不得展示“已通过操作系统验证”。
- 取得证书后可以并行提供平台签名包，但不得把既有未签名文件原地改名为签名包。

## WorkBuddy 应用内插件市场

管理器不会执行门户返回的任意命令，也不启动 `.command`、`.cmd`、PowerShell 或 WorkBuddy 外部 CLI。它只会：

1. 下载跨平台 WorkBuddy 插件市场包。
2. 完成 Ed25519 签名与清单内全部文件哈希校验。
3. 在文件管理器中定位已验证 ZIP。
4. 用户解压后，在正在运行的 WorkBuddy 内执行 `/plugin marketplace add <解压后的市场目录>`，再安装并启用 `jiaotang-workbuddy-skills@jiaotang`。

应用内命令由 WorkBuddy 自己处理，不占用第二个宿主进程，因此不再设置“完全退出 WorkBuddy”的运行锁。macOS 与 Windows 使用同一个候选包，并在发布前分别完成实机验收。

## 发布阻断条件

- 发行物没有明确选择 `signed` 或 `unsigned-local-authorization` 模式。
- `signed` 模式下应用未签名、签名失效、公证未 staple，或 Windows Authenticode 状态不是 `Valid`。
- 本地授权模式下文件名缺少 `unsigned-local`、macOS 应用意外带发布者或应用级签名、Windows PE 证书表非空，或发行审计不是 `pass`。
- 发布包 SHA-256 与门户元数据不一致。
- Word 用户手册未纳入 Release、总校验和或合并发行审计。
- 发布后生成的 published 门户清单未经复核就直接改写仓库，或 pending 与 published 状态、SHA-256 不自洽。
- Ed25519 公钥指纹不是信任清单中的固定值。
- 签名清单缺文件、路径越界、重复路径或任一文件哈希不一致。
- 干净系统安装、更新、回滚测试未完成。

任一条件命中时，可以继续提供 PWA 和既有签名 Skills 包，但不得发布新的原生管理器安装包。

# 桌面发行签名与安全门禁

## 当前发布决策

在没有 Apple Developer ID 和 Windows Authenticode 证书的阶段，正式双端入口是知识门户的 HTTPS PWA `/skills-manager`。PWA由已部署网站承载，不把未签名 Electron 构建交给用户，也不要求用户放宽操作系统安全策略。

本目录中的原生构建仅允许工程验证。下述门禁全部通过后，才能把原生客户端从“开发预览”改为“正式发布”；PWA不会降低或替代这些门禁。

Skills 管理器同时校验两条互不替代的信任链：

1. 桌面应用信任链：macOS 使用 Developer ID、Hardened Runtime 与 Apple 公证；Windows 使用 Authenticode 代码签名。
2. Skills 内容信任链：门户 HTTPS 来源、发布包 SHA-256、固定 Ed25519 发布公钥指纹、OpenSSH 签名，以及签名清单内逐文件 SHA-256。

应用通过系统验证，不代表下载的 Skills 一定可信；Skills 验签成功，也不能替代操作系统对应用安装程序的验证。正式发布必须两条链都通过。

## macOS

正式包必须：

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
xcrun stapler validate "Jiaotang-Skills-Manager-0.1.0-mac-arm64.dmg"
npm run release:verify -- --artifact "Jiaotang-Skills-Manager-0.1.0-mac-arm64.dmg"
```

任何一项失败都不得把文件标记为正式版本，也不应指导用户绕过 Gatekeeper。开发预览包只能标记为“未签名测试版”。

## Windows

正式安装器必须：

- 使用受信 CA 签发的 OV 或 EV 代码签名证书，对主程序、辅助可执行文件和 NSIS 安装器签名。
- 固定发布者名称，持续使用同一证书主体；证书轮换要保留可审计记录。
- 使用 RFC 3161 时间戳，避免证书到期后历史签名失效。
- 在 Windows 发布机上使用 `signtool verify /pa /all` 与 PowerShell 双重验证。
- 在开启 Microsoft Defender 与 SmartScreen 的干净 Windows 10/11 环境完成安装、更新、回滚测试。

示例门禁：

```powershell
signtool verify /pa /all /v .\Jiaotang-Skills-Manager-0.1.0-win-x64.exe
Get-AuthenticodeSignature .\Jiaotang-Skills-Manager-0.1.0-win-x64.exe
npm run release:verify -- --artifact .\Jiaotang-Skills-Manager-0.1.0-win-x64.exe
```

`Status` 必须为 `Valid`。SmartScreen 还会参考发布者信誉；稳定的证书主体与持续签名发布有助于积累信誉，但不能承诺首次下载一定不出现提醒。不得把“关闭 Defender”或“忽略未知发布者”作为正式安装步骤。

## WorkBuddy 固定安装器

管理器不会执行门户返回的任意命令。它只会：

1. 下载已声明的 macOS 或 Windows WorkBuddy 通道包。
2. 完成 Ed25519 签名与清单内全部文件哈希校验。
3. 从签名包中提取固定名称的 `.command` 或 `.cmd` 安装器。
4. 在用户明确确认且 WorkBuddy 完全退出后启动固定安装器。

Windows 端使用 `.cmd` 直接安装；macOS 端继续使用 `.command`。平台包独立发布，Windows 热修复不会强制 macOS 更新。

## 发布阻断条件

- 尚未取得相应平台发行证书，却准备把原生构建提供给终端用户。
- 应用未签名、签名失效或公证未 staple。
- 安装器的 Authenticode 状态不是 `Valid`。
- 发布包 SHA-256 与门户元数据不一致。
- Ed25519 公钥指纹不是信任清单中的固定值。
- 签名清单缺文件、路径越界、重复路径或任一文件哈希不一致。
- 干净系统安装、更新、回滚测试未完成。

任一条件命中时，可以继续发布PWA和既有签名Skills包，但不得发布新的原生管理器安装包。

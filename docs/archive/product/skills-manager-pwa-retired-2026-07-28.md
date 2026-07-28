# 焦糖 Skills 管理器 PWA 历史设计

> 归档说明：该入口已于 2026 年 7 月 28 日退役。以下内容仅保留历史设计与发布审计，不再作为当前安装说明。

## 发布结论

知识门户中的 `/skills-manager` 继续作为默认入口。PWA 通过现有 HTTPS
站点和门户会话交付，不依赖桌面客户端，也不会因为桌面客户端尚未发布而失效。

V0.2.0 增加可选的 macOS 与 Windows 桌面客户端，用于扫描本机已经安装的
Agent 平台并执行一键导入。当前分发策略为
`user_authorized_unsigned`：安装包不使用 Developer ID 或 Authenticode
签名，由用户在自己的机器上明确下载、核对 SHA-256 并完成系统授权。
桌面客户端版本与 Skills 发布版本相互独立。

`native-release.json` 目前是 `pending` 清单。流水线先发布不可变 GitHub Release，
再生成附带实际 SHA-256 的 `native-release.published.json`；该文件经人工复核并在
独立提交中回填门户后，门户才开放下载。流水线不会自动改写仓库。

## 能力协商

页面启动时读取 `platform-capabilities.json`，并逐项确认：

1. 当前是安全上下文。
2. WebCrypto 可计算下载包 SHA-256。
3. 浏览器支持 ZIP deflate 解压。
4. 浏览器支持用户主动选择并授权本地目录。
5. 目录句柄支持在已复制到恢复区后移走旧托管路径。

五项全部通过才开放目录同步。任一能力缺失时只提供校验后下载，不尝试探测或写入本地目录。

桌面客户端发布信息通过登录保护接口
`/v1/web/skills-manager/native-release` 提供。页面只使用门户返回的版本、资产名、
SHA-256 与稳定下载地址，不直接拼接外部下载链接。

## 安装与更新边界

- TRAE 中国版与 Kimi Code：用户选择官方 Skills 目录后同步。
- 通义灵码、Qoder与Cherry Studio：下载已校验通用包，再走平台官方导入界面。
- WorkBuddy：macOS 与 Windows 下载同一个跨平台发布者签名插件市场包。包内 Ed25519 用于验证内容来源和完整性，不等于 Gatekeeper 或 Authenticode 代码签名；操作系统阻断时停止安装，不提供绕过步骤。要消除未知开发者或未知发布者提示，仍需改为相应平台正式签名、公证的原生安装载体。
- 同名但未由管理器登记的内容会阻断写入。
- 已托管内容更新前复制到 `.jiaotang-skills-manager/backups`。
- 回滚时被替换的当前版本进入 `.jiaotang-skills-manager/displaced`，不永久删除。

## 未签名桌面客户端

候选资产固定为：

| 平台 | 资产名 | 门户稳定地址 |
|---|---|---|
| macOS Apple Silicon | `Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-arm64.dmg` | `/skills-manager/download/macos/arm64` |
| macOS Intel | `Jiaotang-Skills-Manager-0.2.0-unsigned-local-mac-x64.dmg` | `/skills-manager/download/macos/x64` |
| Windows x64 | `Jiaotang-Skills-Manager-0.2.0-unsigned-local-win-x64.exe` | `/skills-manager/download/windows/x64` |

Release 同时包含
`Jiaotang-Skills-Manager-0.2.0-User-Manual.docx`、`release-audit.json`、
`native-release.published.json` 和 `SHA256SUMS.txt`。Word 手册的文件名、大小和
SHA-256 必须进入发行审计，门户回填清单也必须进入总校验和。门户回填后可通过
`/skills-manager/download/user-manual` 下载 Word 手册。

三个稳定地址均要求门户登录。未发布时返回 404；发布后由服务端校验清单，再以
307 重定向到固定 GitHub Release 资产。接口和重定向均设置 `Cache-Control:
no-store`，避免旧版本地址被客户端缓存。

本机授权的边界：

- macOS：用户下载后在“系统设置 → 隐私与安全性”中确认运行。没有 Developer ID
  时不会获得 Gatekeeper 的发布者身份、公证或 staple 保障。
- Windows：用户下载后通过 SmartScreen 的本机确认继续运行。没有 Authenticode
  时不会显示受信发布者，Smart App Control、杀毒软件或组织策略仍可能直接阻断。
- 管理员权限只能授予本机文件和目录权限，不能替代代码签名，也不能绕过企业安全策略。
- 正式开放下载前必须先发布实际 SHA-256。页面展示的哈希用于用户核对下载完整性，
  但不等于操作系统的发布者信任。
- 桌面客户端 Release 不捆绑或审计 Skills 内容。通用 Skills 与 WorkBuddy 内容仍
  由门户各自的独立发布通道提供。

## 会话与缓存

- 发布通道和下载接口使用现有门户会话。
- 用户名所在的 `/skills-manager` HTML 只走网络，不写入 Service Worker 静态缓存。
- API、桌面发布元数据与下载重定向不离线缓存。
- PWA 不读取钥匙串、DPAPI、设备私钥或个人访问凭据。

## 验收

本地检查：

```bash
node --check services/knowledge-portal/static/skills-manager/app.js
node --check services/knowledge-portal/static/skills-manager/zip-reader.js
node --check services/knowledge-portal/static/skills-manager/sw.js
node services/knowledge-portal/scripts/check_skills_manager_pwa.mjs
cd services/knowledge-portal
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_portal.py \
  -k 'legacy_client_artifacts_do_not_feed_unified_workbuddy_channel or skills_manager_native'
```

CI 使用 `.github/workflows/skills-manager-release-gates.yml` 重复执行路由、静态
文件、能力清单、会话缓存和客户端发布清单检查。门禁同时接受自洽的 `pending` 与
`published` 清单，不接受部分产物提前开放、空 SHA-256 的 published 清单或已有
SHA-256 的 pending 清单。

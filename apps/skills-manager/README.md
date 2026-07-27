# 焦糖 Skills 管理器

本目录保存未来的原生 macOS 与 Windows 客户端。当前可正式交付的双端管理器是知识门户中的 HTTPS PWA，入口为 `/skills-manager`；它不分发未签名原生程序，因此不要求用户绕过 Gatekeeper、SmartScreen 或“未知发布者”警告。

原生客户端当前仅为工程验证版。取得 Apple Developer ID、公证能力与 Windows Authenticode 证书，并通过双端实机门禁前，不得作为正式下载提供。

## PWA 正式路线

- 使用现有门户登录态，不向网页脚本暴露设备私钥、个人访问凭据或一次性安装码。
- 在桌面版 Chrome 或 Edge 中由用户明确选择目标目录后同步；Safari、Firefox 或缺少必要 API 的环境自动降级为校验后下载。
- 运行时读取平台能力清单，先检查安全上下文、WebCrypto、ZIP 解压和目录授权，再决定是否开放写入。
- 只写入发布清单列出的 49 项技能与共享路径，未托管同名内容会阻断安装。
- 覆盖前保留目录内备份，回滚时当前版本先进入 displaced 恢复区，不永久删除用户文件。
- WorkBuddy 只下载对应平台的既有签名包，仍由用户审查并运行包内固定 `.command` 或 `.cmd`。

实现位于 `services/knowledge-portal/static/skills-manager`，发布说明见 `docs/skills-manager-pwa.md`。

## 原生工程验证版已实现

- 自动识别 WorkBuddy、TRAE、Kimi Code、通义灵码、Qoder 与 Cherry Studio，并按“完整同步、适配导入、引导导入”分级。
- 通用 Skills、WorkBuddy macOS、WorkBuddy Windows 三条独立更新通道。
- 普通成员复用本机钥匙串或DPAPI中的既有设备凭据并逐请求签名，不重新绑定设备；管理员令牌只保存在当前进程内。
- SHA-256、固定 Ed25519 公钥、OpenSSH 签名及逐文件哈希验证。
- 对稳定目录采用“计划预览 → 冲突阻断 → 同盘备份 → 原子替换 → 可恢复回滚”。
- WorkBuddy 仅启动签名包内固定 `.command` 或 `.cmd`，且要求先完全退出 WorkBuddy。
- 49 项技能与各平台的兼容性账本。
- 应用自身的 Gatekeeper 或 Authenticode 状态展示与正式发布门禁。

通义灵码、Qoder 与 Cherry Studio 当前采用适配导入或引导导入，不写入尚未由官方公开稳定的内部目录。所谓“同步”是同一签名版本的分发与状态管理，不同步各 Agent 的聊天记录、模型记忆、账号状态或平台私有配置。

## 开发

```bash
npm install
npm run catalog
npm test
npm run check
npm start
```

原生正式发行要求见 `docs/SECURITY_SIGNING.md`。未通过 Apple 公证或 Windows Authenticode 门禁的构建只能用于开发测试，不能用“右键打开”“仍要运行”或关闭系统防护作为发布说明。

## 数据边界

- 托管内容：49 项由焦糖发布的 Skills 与共享资源。
- 用户内容：项目资料、个人规则、偏好和第三方 Skills。管理器遇到同名但未登记为托管的目录会停止并要求处理，不会静默覆盖。
- 本地状态：版本登记、备份索引和下载缓存位于应用用户数据目录。
- 远端状态：门户只提供认证后的发布通道与签名包。本版本不包含短信登录功能。

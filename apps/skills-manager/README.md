# 焦糖 Skills 管理器

本目录保存 macOS 与 Windows 原生客户端。管理器版本与 Skills 内容版本相互独立：当前管理器为 `0.2.0`，管理的正式内容仍为 49 项 Skills。

当前支持两种明确区分的发行模式：

- `signed`：未来取得 Developer ID、Apple 公证和 Windows Authenticode 后使用的平台签名发行。
- `unsigned-local-authorization`：文件名带 `unsigned-local`，不声明操作系统发布者身份，由用户在自己的机器上明确授权运行。该模式不保证在启用 Smart App Control 或组织强制策略的 Windows 设备上可安装。

原生客户端与 HTTPS PWA 已停止正式分发，旧入口统一跳转到知识门户“Skills → 版本与下载”。

## PWA 路线

- 使用现有门户登录态，不向网页脚本暴露设备私钥、个人访问凭据或一次性安装码。
- 在桌面版 Chrome 或 Edge 中由用户明确选择目标目录后同步；Safari、Firefox 或缺少必要 API 的环境自动降级为校验后下载。
- 运行时读取平台能力清单，先检查安全上下文、WebCrypto、ZIP 解压和目录授权，再决定是否开放写入。
- 只写入发布清单列出的 49 项技能与共享路径，未托管同名内容会阻断安装。
- 覆盖前保留目录内备份，回滚时当前版本先进入 displaced 恢复区，不永久删除用户文件。
- WorkBuddy 下载跨平台签名插件市场包；用户解压后在 WorkBuddy 内添加本地市场并安装插件，不执行 `.command`、`.cmd` 或外部 CLI。

实现位于 `services/knowledge-portal/static/skills-manager`，发布说明见 `docs/skills-manager-pwa.md`。

## 历史客户端能力

- 用户点击“扫描本机 Agent”后，只在 macOS 与 Windows 的已知应用位置识别 WorkBuddy；不递归读取用户文档。
- WorkBuddy 下载已验签本地插件市场包，并在 WorkBuddy 内通过 `/plugin` 添加、安装和启用。
- 通用 Skills 与跨平台 WorkBuddy 插件市场包两条更新通道。
- 普通成员复用本机钥匙串或DPAPI中的既有设备凭据并逐请求签名，不重新绑定设备；管理员令牌只保存在当前进程内。
- SHA-256、固定 Ed25519 公钥、OpenSSH 签名及逐文件哈希验证。
- 对稳定目录采用“计划预览 → 冲突阻断 → 同盘备份 → 原子替换 → 可恢复回滚”。
- WorkBuddy 不启动外部安装器；安装动作由正在运行的 WorkBuddy 自己完成，因此没有端口冲突和退出运行锁。
- 49 项技能与 WorkBuddy 的兼容性账本。
- 平台适配器通过门户独立验签更新；失败时回退内置版本，不接受远程命令或脚本。
- 扫描、验签、导入、回滚和适配器更新写入本机追加式审计日志，敏感字段自动脱敏。
- 应用显示自身的平台信任状态；本地授权版明确显示“未建立系统发布者身份”，不伪装成 Gatekeeper 或 Authenticode 已验证。

正式分发不再维护其他宿主的专用适配器、安装计划或兼容性声明。

## 开发

```bash
npm install
npm run catalog
npm test
npm run check
npm start
```

构建本地授权发行物：

```bash
npm run package:mac:unsigned-local
npm run package:win:unsigned-local
npm run release:verify:unsigned-local -- \
  --artifact dist/对应产物 \
  --audit-output dist/release-trust.json
```

本地授权模式只有在显式传入 `--mode unsigned-local-authorization` 时才能通过发行门禁。门禁会生成机器可读的 `release-trust.json`，记录版本、SHA-256、大小和平台信任级别，并明确声明该客户端 Release 不捆绑、不验证 Skills 内容。Word 用户手册、published 门户回填清单及其 SHA-256 由跨平台发布流水线统一审计。

完整发行要求见 `docs/SECURITY_SIGNING.md`。不要通过命令删除 macOS 隔离属性，不要关闭 Gatekeeper、Defender 或 SmartScreen。用户级 Skills 安装本身不需要管理员权限，管理器不会为了写入用户目录而索要提权。

本地授权不等于代码签名。macOS 的“仍要打开”和 Windows 的“仍要运行”只能在本机策略允许时建立例外，不能证明应用发布者身份，也不能替代 Gatekeeper、Smart App Control 或 SmartScreen。应用下载的 Skills 仍必须通过 HTTPS 来源、发布包 SHA-256、固定 Ed25519 公钥和逐文件清单验证。

## 数据边界

- 托管内容：49 项由焦糖发布的 Skills 与共享资源。
- 用户内容：项目资料、个人规则、偏好和第三方 Skills。管理器遇到同名但未登记为托管的目录会停止并要求处理，不会静默覆盖。
- 本地状态：版本登记、备份索引和下载缓存位于应用用户数据目录。
- 远端状态：门户只提供认证后的发布通道与签名包。本版本不包含短信登录功能。

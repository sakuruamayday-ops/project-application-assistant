# 焦糖 Skills 管理器

面向 macOS 与 Windows 的 Skills 交付控制台。它把同一份签名 Skills 发布到不同 Agent 的稳定导入入口，并保留平台差异、冲突确认、备份和回滚。

当前为 MVP 开发版，尚未作为正式桌面安装包发布。

## 已实现

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

正式发行要求见 `docs/SECURITY_SIGNING.md`。未通过 Apple 公证或 Windows Authenticode 门禁的构建只能用于开发测试。

## 数据边界

- 托管内容：49 项由焦糖发布的 Skills 与共享资源。
- 用户内容：项目资料、个人规则、偏好和第三方 Skills。管理器遇到同名但未登记为托管的目录会停止并要求处理，不会静默覆盖。
- 本地状态：版本登记、备份索引和下载缓存位于应用用户数据目录。
- 远端状态：门户只提供认证后的发布通道与签名包。本版本不包含短信登录功能。

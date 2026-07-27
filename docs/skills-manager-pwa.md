# 焦糖 Skills 管理器 PWA

## 发布结论

当前正式双端方案是知识门户中的 `/skills-manager`。它通过现有 HTTPS 站点和门户会话交付，不需要分发未签名的 macOS 或 Windows 管理器应用。

原生 Electron 客户端不是本阶段正式产物。macOS 必须先取得 Developer ID、完成 Hardened Runtime、公证与 staple；Windows 必须先取得 Authenticode 证书、完成时间戳签名和 SmartScreen 实机验证。

## 能力协商

页面启动时读取 `platform-capabilities.json`，并逐项确认：

1. 当前是安全上下文。
2. WebCrypto 可计算下载包 SHA-256。
3. 浏览器支持 ZIP deflate 解压。
4. 浏览器支持用户主动选择并授权本地目录。
5. 目录句柄支持在已复制到恢复区后移走旧托管路径。

五项全部通过才开放目录同步。任一能力缺失时只提供校验后下载，不尝试探测或写入本地目录。

## 安装与更新边界

- TRAE 中国版与 Kimi Code：用户选择官方 Skills 目录后同步。
- 通义灵码、Qoder与Cherry Studio：下载已校验通用包，再走平台官方导入界面。
- WorkBuddy：只下载当前系统独立发布通道的发布者签名包。包内 Ed25519 用于验证内容来源和完整性，不等于 Gatekeeper 或 Authenticode 代码签名；操作系统阻断时停止安装，不提供绕过步骤。要消除未知开发者或未知发布者提示，仍需改为相应平台正式签名、公证的原生安装载体。
- 同名但未由管理器登记的内容会阻断写入。
- 已托管内容更新前复制到 `.jiaotang-skills-manager/backups`。
- 回滚时被替换的当前版本进入 `.jiaotang-skills-manager/displaced`，不永久删除。

## 会话与缓存

- 发布通道和下载接口使用现有门户会话。
- 用户名所在的 `/skills-manager` HTML 只走网络，不写入 Service Worker 静态缓存。
- API与下载请求不离线缓存。
- PWA 不读取钥匙串、DPAPI、设备私钥或个人访问凭据。

## 验收

本地检查：

```bash
node --check services/knowledge-portal/static/skills-manager/app.js
node --check services/knowledge-portal/static/skills-manager/zip-reader.js
node --check services/knowledge-portal/static/skills-manager/sw.js
node services/knowledge-portal/scripts/check_skills_manager_pwa.mjs
cd services/knowledge-portal
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_portal.py -k client_channels_keep_independent_latest_versions
```

CI使用 `.github/workflows/skills-manager-release-gates.yml` 重复执行路由、静态文件、能力清单、会话缓存和原生证书阻断检查。

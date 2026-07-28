# 焦糖 Skills 管理器退役说明

状态：已于 2026 年 7 月 28 日退役。

## 当前入口

- `/skills-manager` 不再呈现 PWA 或原生客户端下载，登录后统一跳转到
  `/skills#skills-downloads`。
- macOS、Windows 原生客户端下载地址与 Word 客户端手册地址同样跳转到网站安装包下载中心。
- 原 v0.2.0 GitHub Release、SHA-256 和审计材料保持不可变，只作为历史证据保留。
- 旧 Service Worker 激活后清除 `jiaotang-skills-manager` 缓存并自行注销，避免继续显示离线客户端页面。

## 当前分发方式

网站只维护两类正式下载：

1. 通用 Skills 包。适用于支持标准 Agent Skills 的平台。
2. 平台增强包。包含同一套 Skills，并附该宿主官方支持的 Hooks、插件或 MCP 配置。

平台增强包必须通过官方文档核对、结构校验和真实宿主验收后才能开放下载。
当前正式可下载的平台增强包只有 WorkBuddy 跨平台插件市场包。

完整策略见
[`docs/product/website-package-distribution.md`](product/website-package-distribution.md)。

## 验收

```bash
node --check services/knowledge-portal/static/skills-manager/sw.js
node services/knowledge-portal/scripts/check_website_package_center.mjs
cd services/knowledge-portal
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_portal.py \
  -k 'legacy_client_artifacts_do_not_feed_unified_workbuddy_channel or skills_manager_retirement'
```

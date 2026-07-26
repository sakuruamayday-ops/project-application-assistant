# Runner 流程归档

该目录保存 2026-07-26 停用的 GitHub 自托管 Runner、双宿主自动门禁和 OIDC 宿主证据实现，仅用于历史审计。

停用原因：主人决定不维护专用 macOS、Windows 测试电脑，也不再维护平台确认或人工兼容反馈状态。用户遇到需要适配的问题时按具体环境单独处理。目录内的 `.yml.disabled` 不会被 GitHub Actions 加载，归档脚本也不参与当前发布流程。

当前有效流程以以下文件为准：

- `scripts/controlled_release.py`
- `services/knowledge-portal/scripts/publish_skill_release.py`

恢复任何 Runner 或遥测回传前，必须取得主人新的明确授权并重新审查隐私、凭据和长期运维成本。

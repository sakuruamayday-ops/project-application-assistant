---
name: project-deliverable-archive
description: 自动整理政府项目、企业分析、知识产权分析和正式报告的已核验成果。用于复杂任务完成、生成正式交付物或用户要求归档时，在Agent可写工作区建立项目目录、版本和来源清单；不依赖特定笔记软件。
---

# 项目成果自动归档


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-deliverable-archive" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

任务形成可复用成果后，自动整理到当前工作区 `企业全生命周期助手归档/`。归档只复制或生成文件，不改动原始资料，不保存账号、密码、Cookie、Token或无关客户信息。

## 目录

```text
企业全生命周期助手归档/
└── <地区>/<企业>/<项目或任务>/<YYYY-MM-DD>/
    ├── 01_企业资料
    ├── 02_政策原文
    ├── 03_分析过程
    ├── 04_正式成果
    ├── 05_证据与来源
    └── archive-manifest.json
```

## 规则

1. 只归档本次实际使用、生成并完成核验的文件。
2. 同名文件增加日期和版本号，不覆盖既有成果。
3. `archive-manifest.json` 记录企业、地区、项目、文件名、来源、政策版本、哈希和归档时间。
4. 政策原文与分析结论分目录保存，历史政策标注 `historical`、`superseded` 或 `withdrawn`。
5. 宿主无文件写入能力时生成归档清单和待下载文件列表，明确说明尚未落盘。
6. 不自动上传云端；用户明确要求共享时再按照当前授权执行。

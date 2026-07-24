---
name: project-deliverable-archive
description: 自动整理政府项目、企业分析、知识产权分析和正式报告的已核验成果。用于复杂任务完成、生成正式交付物或用户要求归档时，在Agent可写工作区建立项目目录、版本和来源清单；不依赖特定笔记软件。
---

# 项目成果自动归档


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-deliverable-archive" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
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

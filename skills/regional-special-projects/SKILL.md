---
name: regional-special-projects
description: 将未纳入固定领域的市、区县、园区临时通知和新申报项目转换为带原文位置的候选规则，经核验后交project-feasibility；不为每个短期通知新建技能；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 区域特色项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

宿主若只暴露 `run_code`，`skill`、`read`、`web_search`、校验器等工具均须在其中以 `await tools.<name>(...)` 调用，不得根级调用隐藏工具。先按 `SKILL.md` 或参考文档执行命令；不得为理解用法预读脚本、模板、示例或测试，只有真实命令报错且契约不明确时才读取直接相关源码。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

把尚未形成固定领域模型的市、区县、园区临时通知转换为可审计候选规则，不为每个短期项目创建新技能。

## 流程

1. 调用 `policy-retrieval` 取得正式通知、附件、更正和延期文件。
2. 提取地区层级、主管部门、申报主体、适用行业、硬门槛、排除项、评分项、材料、流程、截止时间和奖补方式。
3. 每条规则保留原文位置和证据等级；无法确认的字段标记待核验。
4. 运行 `scripts/validate_candidate_rule.py` 检查规则结构。
5. 经人工核验后交给 `project-feasibility`，不得将候选规则直接写成正式政策事实。

## 数据不足处理

只有新闻稿、转载或摘要时，候选规则保持未核验，不输出明确截止日期和资格结论。附件缺失时列出缺失文件名和可能影响的判断字段。

## 输出

结构见 `references/regional-rule-schema.md`。同名项目跨地区不得复用规则，下一年度不得无核验沿用。

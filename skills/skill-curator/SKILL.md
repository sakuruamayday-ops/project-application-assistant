---
name: skill-curator
description: 安装企业全生命周期助手后自动启用。根据任务使用记录、用户纠正和四问复盘检查技能重复、触发冲突、过期规则、使用情况和质量问题，提出合并、拆分、归档或保留建议。
---

# 技能策展


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设存在 `CODEBUDDY_SKILL_DIR`、`SKILL_DIR` 或其他特定宿主变量，也不得猜测路径。

`fail`表示签名、发布者身份或安装完整性失败，必须停止使用受影响副本；`limited`表示已验签副本的运行依赖或辅助偏好读写受限，仅在当前任务所需能力仍满足时继续，并准确说明未应用或未持久化的部分。只应用返回的`active_preferences`；普通纠正和临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

默认只生成报告。任何合并、删除、归档和覆盖操作必须先创建快照并取得用户批准。核心规则不得因使用频率低而删除。

首次配置后无需用户再次开启其分析能力；这不授予常驻调度、周期巡检或日志写入权限。进入已授权的技能审计任务时读取 `experience-recorder` 已有脱敏记录；只有发现可复现问题时才提出调整，避免为追求变化而变化。

以下阈值只约束自主发现与自动聚合。用户明确要求修复已经复现或已核验的问题时，不等待累计阈值，直接把该问题作为有界候选交给 `skill-authoring` 与 `evolution-governance`；仍须遵守快照、影响范围、测试、签名和正式发布授权。

## 高频纠正聚合

自主进化不要因单次纠正立即启动。先运行：

```bash
python3 scripts/aggregate_corrections.py \
  --input ~/.config/project-assistant/evolution/corrections.jsonl
```

默认只有同一技能、同一规则键累计至少3条已核验纠正，且来自至少2个不同任务时，才进入批量候选。每批最多选择2个技能，同一技能进入候选后冷却7天。缺少字段、未经核验、含敏感信息或处于冷却期的信号不参与计数。阈值从 `config/common.yaml` 读取。

输出 `correction-summary.json` 和 `evolution-batch.json`。只有批次清单的 `ready=true` 时才交给 `skill-evolution`；这一步仍不运行GEPA、不修改正式Skill。

主人批准开始处理该批次后，使用同一输入追加 `--mark-planned` 写入冷却状态，防止下次巡检重复生成同一批候选。未批准或仅查看报告时不要写状态。

## 技能变更影响图

修改任何规则、技能、模板、脚本或交付门禁前运行：

```bash
python3 scripts/build_impact_graph.py --changed <变更文件>
python3 scripts/build_impact_graph.py --query <规则关键词>
```

脚本输出可查询的 `skill-impact-graph.json` 和人类可审查的 `skill-impact-report.md`，按下游关系列出受影响技能、模板、脚本和门禁。关系方向、节点类型和发布要求见 [impact-graph-schema.md](references/impact-graph-schema.md)。影响图没有覆盖到的隐式业务关系必须在报告中人工补充，不得把关键词共现当成确定依赖。

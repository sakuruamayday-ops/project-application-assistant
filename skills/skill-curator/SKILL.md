---
name: skill-curator
description: 审阅技能体系和已核问题，分析重复、冲突与影响，提出合并、拆分、保留及候选改进建议。
---

# 技能策展

按用户审阅或维护范围执行，变更保留快照及差异。用实际问题、已有脱敏记录和任务结果评价规则价值，候选修改可直接进入相称验证；签名、安装与发布由对应流程处理。

## 纠正聚合

```bash
python3 scripts/aggregate_corrections.py --input ~/.config/project-assistant/evolution/corrections.jsonl
```

脚本按技能、稳定规则键和任务聚合已核脱敏记录，配置取 `config/common.yaml`，输出 `correction-summary.json`、`evolution-batch.json` 及 `ready` 状态。用户指定修复可直接形成对应候选，自动聚合参数用于整理已有信号。计划状态按本轮维护要求使用 `--mark-planned` 记录。

## 影响分析

```bash
python3 scripts/build_impact_graph.py --changed <变更文件>
python3 scripts/build_impact_graph.py --query <规则关键词>
```

输出 `skill-impact-graph.json`、`skill-impact-report.md`，列技能、模板、脚本及共享资产的关联，标明需要修改、需要回归及已知无影响对象。隐式业务关系结合实际方法补充，关键词共现作为待核线索。

定义见 [impact-graph-schema.md](references/impact-graph-schema.md)。报告给问题、依据、影响、最小候选和验证状态；日志、自动调度及长期记录按用户要求办理。

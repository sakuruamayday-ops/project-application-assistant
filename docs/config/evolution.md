# 自主进化配置

自主进化默认关闭。启用后仍以只读评估和候选版本为主，不允许静默替换稳定技能。

## 配置

```yaml
evolution:
  enabled: true
  mode: dry_run
  require_human_approval: true
  snapshot_before_change: true
  impact_graph:
    enabled: true
    output_dir: .project-assistant/evolution
    max_depth: 4
    require_before_candidate: true
  correction_batch:
    min_signal_count: 3
    min_distinct_tasks: 2
    max_batch_skills: 2
    cooldown_days: 7
    require_verified: true
```

模型默认复用宿主Agent。需要外部评判模型时，可接入任意兼容API，由用户自行选择供应商、模型地址和模型名称，不设置固定供应商前置条件。

## 能力

- 记录成功经验和失败原因。
- 检查重复、冲突和过期技能。
- 生成技能修改提案。
- 使用测试案例评估候选版本。
- 经批准后发布并保留回滚快照。

## 高频纠正批次

经验记录器只追加脱敏、已核验的纠正信号，不直接调用GEPA。策展器按“技能加稳定规则键”去重聚合；同一规则达到3条且覆盖2个不同任务后才进入候选，每批最多处理2个技能，处理后冷却7天。未达阈值的信号继续累计，不降低门槛。

```bash
python3 skills/skill-curator/scripts/aggregate_corrections.py \
  --input ~/.config/project-assistant/evolution/corrections.jsonl
```

`evolution-batch.json` 的 `ready=false` 表示本期不进化。`ready=true` 也只授权生成候选；调用GEPA或外部模型仍需确认成本，修改和发布仍需人工批准。

批准开始处理批次后，用同一命令追加 `--mark-planned`，将所选技能及时间写入 `evolution-state.json` 并启动冷却期。只读巡检不得使用该参数。

## 技能变更影响图

影响图从技能目录、显式文件引用和技能调用关系中生成，方向为“依赖项指向使用方”。修改规则时可按路径或关键词查询：

```bash
python3 skills/skill-curator/scripts/build_impact_graph.py --changed config/common.yaml
python3 skills/skill-curator/scripts/build_impact_graph.py --query 来源验证
```

输出的JSON供自动遍历，Markdown报告供审批。候选发布前必须逐项处置图中受影响的技能、模板、脚本和交付门禁。图谱只证明显式关系，隐式业务关系仍需人工补充。

## 保护规则

身份、权限、凭据处理、来源核验和正式材料质量门禁不得自动修改。客户敏感内容不得进入公共技能和评测集。

## 验证

用脱敏案例执行一次dry-run，确认只产生影响报告、纠正汇总、批次清单、差异报告和候选版本，没有修改稳定技能。

## 停用与回滚

将 `enabled` 改为 `false`。使用最近快照恢复，并保留审计日志，不静默删除失败记录。

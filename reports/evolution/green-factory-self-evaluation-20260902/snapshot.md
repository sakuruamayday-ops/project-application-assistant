# 绿色工厂自评价技能候选稳定快照

- 批次：`green-factory-self-evaluation-20260902`
- 基线提交：`e52a82f56222a27d8bdf88bab6300a0963562f27`
- 基线分支：`main`
- 候选分支：`codex/green-factory-skill-20260902`
- 快照性质：Git 不可变提交，可从基线提交恢复；候选位于独立 worktree，未改动主工作树。

## 变更前目标哈希

| 文件 | SHA-256 |
|---|---|
| `skills/green-development-projects/SKILL.md` | `49b41d12adb34b81788531f6d1a9ad1d326aed83478493ea1f471975ac6eddab` |
| `skills/green-development-projects/references/green-metrics-boundaries.md` | `368b1ba1e73509d82cee6fae4d319650a9ef733efd8dd34aeddff6258a55c8b5` |
| `tests/skill_content_cases.json` | `ea61dff96f58526b5f29ca5d109ba0e681f2e610efe3ebefbf7b878e2de72210` |

新增参考文件、校验脚本和定向测试在基线中不存在，变更前哈希记为 `null`。

## 恢复边界

恢复时只需丢弃本候选 worktree 或将目标文件恢复至基线提交。正式安装目录、签名清单、发布密钥、客户文件、知识索引和外置个人偏好均未被本候选修改。

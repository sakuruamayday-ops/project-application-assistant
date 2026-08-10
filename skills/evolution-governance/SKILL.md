---
name: evolution-governance
description: 安装企业全生命周期助手后自动启用，管理技能自主进化的审批、快照、测试、发布、审计和回滚。任何技能自动创建、修改、合并或归档前必须使用。
---

# 进化治理


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "evolution-governance" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 治理状态机

默认进入“observed”，依次经过“candidate、dry-run、impact-reviewed、tested、approved、signed、installed、stable”。任一门禁失败进入“blocked”；安装或运行回归失败进入“rollback-required”。详细进入和退出条件见 `references/governance-state-machine.md`。

允许自动记录问题、诊断、评分、生成候选差异和运行测试；不得自动跨过审批、签名或安装回归。正式文件变更前必须创建可恢复快照，不得以覆盖原目录代替快照。

## 风险与审批

读取 `references/change-risk-classification.md` 对变更分级：

- 低风险：示例、非规范性说明和不改变行为的文字修正，可批量审批。
- 中风险：领域流程、输出字段、引用和非安全脚本，需要技能级审批和回归。
- 高风险：共享运行时、路由、模板、跨技能依赖和发布器，需要影响图、全套回归和逐批审批。
- 受保护：身份、权限、凭据、来源验证、验签、真实性和正式材料质量门禁，只允许主人逐项批准后的人工修改。

禁止从客户敏感材料生成公共技能。个人习惯只写外部覆盖层，不写入官方签名核心。

## 审批材料

审批前必须同时具备：`evolution-batch.json`、影响报告、稳定快照、候选差异、回归结果和目标文件哈希。按 `references/approval-contract.md` 绑定审批对象与差异哈希；审批后源码变化即使测试仍通过，也必须重新审批。

影响图中的每个技能、模板、脚本、共享资产和门禁必须标记为“需要修改、仅需回归、不受影响”。缺少任一材料或存在未解析影响时保持“dry-run”。

运行 `python3 scripts/validate_evolution_batch.py <evolution-batch.json>`。结果非 `pass` 时禁止签名和发布。

## 发布、继承与回滚

发布采用“官方核心＋个人覆盖层＋跨设备同步”。检测到用户直接修改 `SKILL.md`、`scripts/`、`references/` 或 `assets/` 时，备份旧目录并生成继承报告，不自动合并回官方核心。

签名、安装自检、强制测试、政策时效或宿主回归任一失败时停止发布。安装后回归失败按 `references/rollback-protocol.md` 恢复最近稳定快照；保留失败候选和证据，不静默覆盖。

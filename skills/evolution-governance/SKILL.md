---
name: evolution-governance
description: 安装企业全生命周期助手后自动启用，管理技能自主进化的审批、快照、测试、发布、审计和回滚。任何技能自动创建、修改、合并或归档前必须使用。
---

# 进化治理


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "evolution-governance" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
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

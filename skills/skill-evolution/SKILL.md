---
name: skill-evolution
description: 安装企业全生命周期助手后自动启用。持续使用脱敏测试案例、执行轨迹、四问复盘和质量评分发现技能问题并生成候选优化；用户明确要求优化时也使用。不得未经审批直接修改或发布正式Skill。
---

# 技能进化


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "skill-evolution" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

稳定版本保持不变，优化只生成候选版本。比较准确性、来源完整性、边界遵守和上下文成本。候选通过测试并经人工批准后才能发布，保留完整差异和回滚点。

个人输出习惯、默认地域、术语和单个用户的工作流选择不进入正式Skill进化，统一写入个人偏好覆盖层。只有跨任务、跨用户复现并经核验的通用质量问题，才进入进化批次。

## 自动运行边界

- 首次配置完成后自动进入启用状态，不要求用户再次下达开启指令。
- 每次适用任务结束后只由 `experience-recorder` 记录脱敏信号，不因单条纠正立即运行进化。
- 先由 `skill-curator` 去重并按技能、规则键和任务聚合；只有 `evolution-batch.json` 的 `ready=true` 时才生成批量候选。默认阈值为同一规则至少3条已核验纠正、覆盖至少2个不同任务，每批最多2个技能，候选后冷却7天。
- 自动运行仅限记录、评分、诊断和候选差异；修改正式Skill、合并、归档和发布必须交给 `evolution-governance` 审批。
- GEPA或外部评判模型只在批次已就绪且主人明确批准成本后运行。批次未达阈值时保留信号，不为了凑批次放宽标准。

## 批量进化输入

读取批次清单后，先为每个候选规则运行 `skill-curator/scripts/build_impact_graph.py`。候选包必须包含信号数量、不同任务数量、适用技能、规则键、影响图、预期改动、测试案例、保护规则检查和回滚点。影响范围不清或命中受保护规则时停止，不生成可发布版本。

## 模型选择

- 默认使用当前宿主Agent已经提供的模型，不要求额外申请API。
- 用户需要单独的评判模型或批量优化时，可使用任意兼容模型API，不绑定DeepSeek、OpenAI、Anthropic或其他固定供应商。
- 配置时记录模型地址、模型名称和宿主要求的认证参数；能力检测只判断是否可调用。
- 模型不可用时保留人工评审和规则测试流程，不阻塞技能审计、候选差异生成及回滚。

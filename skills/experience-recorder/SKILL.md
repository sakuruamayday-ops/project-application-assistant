---
name: experience-recorder
description: 在客户项目分析、正式申报材料、复杂分析、重要规则变更、基础设施迁移或用户纠正完成后自动使用。从任务中提取可复用经验、失败原因和质量规则，执行四问复盘并形成候选经验记录。
---

# 经验记录


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "experience-recorder" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

只记录可泛化方法、验证依据和适用边界，不直接修改技能。禁止写入凭据、客户身份、敏感原文和未经验证的政策结论。

先区分“个人习惯”和“通用纠正”：个人习惯交给 `first-run-configuration` 写入结构化偏好，不进入纠正JSONL；通用纠正才进入后续聚合与进化。不得通过直接修改 `SKILL.md` 保存用户习惯。

## 强制四问

对适用任务，在最终对话中结合当前成果实际回答：

1. 眼下最没有把握的事情是什么？
2. 最大的遗漏是什么，还有什么没有意识到？
3. 最有价值的创新改进是什么？客户产品任务改为最值得增加的行业领先功能或创新点。
4. 哪些不同做法可以提高本次任务效率？

不得只把问题抛给用户。某项确实不适用时写明“不适用”及原因。四问不得进入正式申报书、企业报告和其他客户交付正文。

将复盘中的可泛化内容交给 `skill-curator` 检查重复与冲突；需要优化时交给 `skill-evolution` 生成候选版本，并由 `evolution-governance` 控制审批、发布和回滚。

## 纠正信号

用户纠正、回归失败或经复核确认的质量问题，使用 `scripts/record_correction.py` 写入本地JSONL。每条记录必须包含技能、稳定规则键、任务标识、脱敏摘要和核验状态；相同任务、技能、规则和摘要自动去重。规则键用于聚合同一问题，不得写客户名称、原文、凭据或专利及财务敏感数据。

```bash
python3 scripts/record_correction.py \
  --skill <技能名> --rule-key <稳定规则键> --task-id <脱敏任务标识> \
  --summary <脱敏问题摘要> --verified
```

单条记录只作为证据，不触发GEPA。由 `skill-curator` 达到跨任务阈值后统一形成批量候选。

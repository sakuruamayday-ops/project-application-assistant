---
name: experience-recorder
description: 在客户项目分析、正式申报材料、复杂分析、重要规则变更、基础设施迁移或用户纠正完成后自动使用。从任务中提取可复用经验、失败原因和质量规则，执行四问复盘并形成候选经验记录。
---

# 经验记录


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "experience-recorder" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
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

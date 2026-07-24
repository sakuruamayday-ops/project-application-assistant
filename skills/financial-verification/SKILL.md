---
name: financial-verification
description: 核验政府项目申报中的营收、利润、研发投入、资产、负债、增长率和专项财务指标。用户提供可靠财务资料后使用。
---

# 财务核验


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "financial-verification" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

只使用用户提供或明确授权的可靠数据。读取 `references/source-and-normalization-rules.md`，先确认主体、年度、币种、单位、合并范围和审计口径，再登记原始值。无可靠数据时不推算企业财务，不用第三方过期数据补造。

## 固定流程

1. 建立来源台账，区分审计报告、财务报表、纳税申报表、专项审计、企业台账和外部线索；外部线索不得覆盖企业原始资料。
2. 统一年度、币种、单位和合并范围。无法无损转换或来源口径冲突时保留并列版本，不静默选值。
3. 按 `references/reconciliation-and-formulas.md` 执行表内、表间和跨年度勾稽；研发费用必须区分财务核算、加计扣除和项目申报口径。
4. 每个计算展示公式、原始值、单位、结果和复核状态。缺少分母、期间不连续或口径不同，不计算比例或增长率。
5. 将结果标为“verified、computed、missing、conflicting、not-applicable”；只有前两类可以传递给资格判断。
6. 输出可复用事实、计算指标、证据、质量状态、冲突和缺口；不输出税务违法或申报资格结论。

## 共享财务事实

读取 `references/financial-facts-contract.md`。发现 `enterprise-financial-facts/v1` 文件时：

1. 运行 `python3 scripts/validate_financial_facts.py <文件> --company <企业名称>`。
2. 校验企业名称或统一社会信用代码、期间、币种、单位、合并范围和来源证据。
3. 只向其他 Skill 传递 `facts`、`metrics`、`evidence` 和 `quality`；不传递税务违法或申报资格结论。
4. 新财务文件与旧事实冲突时，保留两版来源并停止自动覆盖，直至用户确认正确口径。

形成结构化核验结果后运行：

`python3 scripts/validate_financial_assessment.py <结果.json>`

企业不一致、单位缺失、计算无公式、冲突被静默覆盖或指标缺乏来源时，验证必须失败。

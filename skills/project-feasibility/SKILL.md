---
name: project-feasibility
description: 对单个政府项目执行完整可行性分析，覆盖项目与版本确认、硬门槛、评分映射、证据状态、财务计算复核、不确定性、材料差距和结论生成。用户询问某企业能否申报、申报成功条件、差距、预评分或需要补什么材料时使用。
---

# 可行性分析


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-feasibility" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 强制执行顺序

1. 确认企业主体、项目全称、地区、申报年度、批次以及新申报或复核类型。任一信息可能改变适用规则时，先调用 `policy-retrieval` 取得管理办法、工作指引和当期通知。
2. 读取 `references/feasibility-decision-model.md`，建立规则台账。每条规则标明规则类型、原文、来源、适用范围、时间状态和是否一票否决；不得把历史政策或同类项目规则拼入当期规则。
3. 读取 `references/evidence-state-model.md`，将企业事实逐项映射为“verified、computed、claimed、missing、conflicting、not-applicable”。只有 verified 和复算通过的 computed 可以直接支撑硬门槛。
4. 先判断排除项和硬门槛，再处理评分项。硬门槛出现 `failed` 时结论为不可申报；出现 `missing`、`conflicting` 或关键 `claimed` 时不得给出确定达标结论。
5. 财务门槛先查找 `artifacts/enterprise-financial-facts.v1.json` 或同契约文件，调用 `financial-verification` 核验企业、期间、单位、币种、合并范围和证据。按 `references/calculation-review-rules.md` 展示公式、原始值、单位、结果和复核状态。
6. 将评分细则逐项映射到事实，不以企业入选案例反推评分，不把同一证据重复计入互斥评分项，不将可能得分计入确定得分。政策未公布评分细则时只分析条件和竞争力，不虚构分值。
7. 按 `references/conclusion-contract.md` 生成结论、依据、风险和行动。先给三档结论，再给逐项依据；不承诺获批。

## 结论规则

- `可申报`：所有硬门槛均为 `passed`，不存在一票否决，关键证据已核验；评分项如有，只将确定分计入。
- `有条件申报`：未发现明确硬门槛失败，但存在可在申报前补齐的关键证据、口径冲突或待确认规则。
- `不可申报`：任一适用硬门槛明确失败，或命中当期政策的一票否决项。
- `暂无法判断`：项目版本、政策原文、企业主体或关键数据不足，无法安全落入前三档。此状态不是“有条件申报”。

## 停止与降级

- 同时命中多个政策版本、缺少当期官方通知或政策时效清单标为 `stale` 时，停止形成正式资格结论，先补政策。
- 财务事实属于其他主体、期间不足、口径不一致或质量为 `unverified` 时，停止复用并列出补证要求。
- 只获得企业自述、媒体报道或历史入选名单时，将其作为线索，不升级为硬门槛事实。
- 税务、司法或舆情风险只有在当期政策明确规定为排除项时才转化为资格判断。

## 交付与自检

输出固定包含：项目版本、总体结论、硬门槛矩阵、评分映射、计算复核、证据缺口、不确定性、风险和按截止时间倒排的行动清单。形成结构化结果时运行：

`python3 scripts/validate_feasibility_assessment.py <结果.json>`

校验失败时不得交付确定性结论。

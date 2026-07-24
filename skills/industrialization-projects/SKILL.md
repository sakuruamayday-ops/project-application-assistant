---
name: industrialization-projects
description: 分析首台套、首批次新材料、首版次软件、工业新产品及产业化示范项目。用户提及新装备、新材料、工业软件、样机、检测或示范应用时使用。
---

# 产业化项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "industrialization-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 分类

1. 先确认产品边界、项目地区、申报年度和批次。用户不知道项目名称时先调用 `project-matching`，不得依据产品名称中的“首台套”“首版次”等字样直接定类。
2. 读取 `references/project-type-decision-tree.md`：装备及关键部件优先核验首台套，新材料优先核验首批次，独立工业软件优先核验首版次，已完成鉴定、验收或备案的成果再核验工业新产品；普通扩产、成熟产品复购和纯研发任务按排除规则处理。
3. 产品同时包含装备、材料和软件时，按申报对象、收入合同、核心创新载体和政策定义确定主项目；其他类别只列备选，不重复使用同一合同制造多项目“首次应用”。
4. 读取 `references/maturity-evidence-matrix.md`，分别核验技术成熟度、创新性、知识产权、检测鉴定、用户应用、合同发票和产业化能力。样机、送检、试用、首单、销售和批量应用不得互相替代。
5. 当期政策原文、产品分类或关键成熟度证据缺失时，只输出候选项目和补证清单，不给“符合申报”结论。
6. 输出主项目、备选项目、分类依据、成熟度阶段、七类证据状态、排除风险和下一步。结构化结果运行 `python3 scripts/validate_industrialization_assessment.py <结果.json>`。

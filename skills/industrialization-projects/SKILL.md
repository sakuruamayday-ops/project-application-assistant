---
name: industrialization-projects
description: 分析首台套、首批次新材料、首版次软件、工业新产品及产业化示范项目。用户提及新装备、新材料、工业软件、样机、检测或示范应用时使用。
---

# 产业化项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "industrialization-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 分类

1. 先确认产品边界、项目地区、申报年度和批次。用户不知道项目名称时先调用 `project-matching`，不得依据产品名称中的“首台套”“首版次”等字样直接定类。
2. 读取 `references/project-type-decision-tree.md`：装备及关键部件优先核验首台套，新材料优先核验首批次，独立工业软件优先核验首版次，已完成鉴定、验收或备案的成果再核验工业新产品；普通扩产、成熟产品复购和纯研发任务按排除规则处理。
3. 产品同时包含装备、材料和软件时，按申报对象、收入合同、核心创新载体和政策定义确定主项目；其他类别只列备选，不重复使用同一合同制造多项目“首次应用”。
4. 读取 `references/maturity-evidence-matrix.md`，分别核验技术成熟度、创新性、知识产权、检测鉴定、用户应用、合同发票和产业化能力。样机、送检、试用、首单、销售和批量应用不得互相替代。
5. 分析浙江省首批次新材料时，必须同时读取当期申报通知与当期现行《浙江省重点新材料首批次应用示范指导目录》。指导目录只用于核验材料范围、性能要求和应用领域，不得把目录条目当作企业公示、认定或奖励记录；历史项目复盘使用对应年度目录。
6. 当期政策原文、产品分类或关键成熟度证据缺失时，只输出候选项目和补证清单，不给“符合申报”结论。
7. 输出主项目、备选项目、分类依据、成熟度阶段、七类证据状态、排除风险和下一步。结构化结果运行 `python3 scripts/validate_industrialization_assessment.py <结果.json>`。

用户要求首台套、首批次新材料或首版次软件的前期评估报告或可行性分析报告时，同时读取 `project-feasibility/references/two-report-contract.md`。不得要求用户预先选择国际、国内、省内或市级档次；先按申报对象、目录、创新性、成熟度、检测查新、首次应用、知识产权和产业化能力给出首选与备选层级。首台套当前检索层未命中研发机构时写明证据未闭合并建议补强，不直接断言企业没有研发机构。

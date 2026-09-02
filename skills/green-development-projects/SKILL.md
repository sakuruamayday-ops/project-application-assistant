---
name: green-development-projects
description: 分析绿色工厂、绿色供应链、节能节水、降碳、资源综合利用、清洁生产和环保改造项目，并编制或核验绿色工厂自评价报告、评分表与证明材料索引；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 绿色发展项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "green-development-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与边界

处理绿色工厂、绿色供应链、节能节水、清洁生产、资源综合利用和降碳改造。环保合规不等于绿色绩效，建设计划不等于已实现成效；自评价总分达到阈值也不能替代基本要求和必选项逐项通过。

国家绿色工厂、省级绿色低碳工厂、市级或区县绿色工厂、零碳或近零碳工厂不是同一项目。先固定企业主体、申报地区与层级、目标年度、申报或复核类型、评价导则及当期模板。任一项会改变基本要求、评分表或材料结构而当前无法确认时，暂停评分和正式成稿，由 `policy-retrieval` 补齐政策链。

## 核验流程

1. 建立版本卡，记录项目全称、层级、年度、导则标题与版本、发文机关、核验日期、年度通知和模板状态；历史导则只能用于预研。
2. 固定组织边界、生产边界、基准期、报告期、合格产品产量及允许使用的分母口径。
3. 先用 `evidence-ledger` 登记来源和计算血缘，再核验能源、水、原材料、废弃物、排放、碳、管理体系和绿色绩效。
4. 基本要求逐项判定。缺证、冲突或失效均不得标为通过；任一基本要求或当期规则规定的必选项不通过时，不得形成推荐结论。
5. 将每条评价要求绑定到正文小节、原始分、一级权重、确认得分、证据记录和附件编号。确认得分只使用已核验证据，未核项另列条件得分或待核，不得先计分后补材料。
6. 对总量、单位指标、三年趋势、改造前后数据和评分公式复算，并回查基本信息表、正文、评分表、附件目录和总分的一致性。

指标边界和比较规则见 `references/green-metrics-boundaries.md`。绿色工厂自评价报告、评分证据矩阵和附件索引见 `references/green-factory-self-evaluation.md`。结构化指标运行 `scripts/validate_green_metrics.py`，完整自评价台账再运行 `scripts/validate_green_factory_ledger.py`；两个脚本通过都不替代政策效力、证据内容和现场真实性的专业判断。

用户要求绿色工厂前期评估报告或可行性分析报告时，同时读取 `project-feasibility/references/two-report-contract.md`，按基础设施、能源资源、产品、排放、碳、管理体系和绿色绩效切换核心评估对象。前期报告只列政策明确要求且已有企业数据、已确认差距或会改变结论的条件，不机械铺陈“无处罚”等空泛合规表述；可行性报告再按当期评价表完整拆解。

用户要求编制或核稿完整自评价报告时，输出至少包括版本卡、基本要求结论、确认分与条件分、逐项评分证据矩阵、计算底稿、附件索引、冲突和补证清单。核稿时定位到表格行、正文小节或附件编号，说明错误对基本要求、必选项、得分或可追溯性的影响；不得把示例企业的数据、附件编号或结论复用于另一企业。

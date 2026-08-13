---
name: technology-innovation-projects
description: 分析研发机构、企业研究院、科技计划、创新平台、科技奖励和成果类项目，核验研发条件、任务、预算、里程碑和验收指标；量产建设为主的任务转工业化或投资项目；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 科技创新项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "technology-innovation-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与分型

处理研发机构、科技计划、创新平台、科技奖励和成果类项目。产品认定或示范应用转 `industrialization-projects`；设备、产线和固定资产投资转 `investment-subsidy-projects`。无法判断主要任务时先补充项目目标和支出结构，不同时散弹调用两个领域技能。

## 核验流程

1. 识别项目类型、主管部门、任务周期和验收方式。
2. 核验研发场地、设备、人员、投入、制度、项目和成果。
3. 项目制申报建立技术问题、研究任务、里程碑、预算和验收指标对应关系。
4. 区分研发条件、研发活动、研发成果和产业化结果，不以单一专利代替研发能力。
5. 产学研合作核验协议、分工、投入、成果归属和实施记录。
6. 预算、里程碑、验收指标或支撑材料缺失时标为待核验，禁止按行业常见值补造。缺失项影响任务闭环或可行性判断的，暂停完整性或可行性结论，输出待补材料、责任主体和验证标准；仅对已核验部分形成限定结论。

项目分类和边界见 `references/technology-project-taxonomy.md`。

涉及“杭州研发中心”“杭州市研发中心”“市高企研发中心”“浙江省研发中心”或企业研发机构时，先读取 `references/current-rd-platform-baseline-2026.md`。杭州三个旧简称统一转入“杭州市企业研究院”；正式文件发布前按2026年征求意见稿预评估并明确尚未生效，不得直接采用旧培训PPT条件，也不得把征求意见稿写成正式办法。

调用技术中心或企业研究院历史案例时，先区分杭州、浙江省及其他市级层级。按 `project_id` 取三至五套案例，先看申报书和建设方案，再按章节展开附件；案例指标不得替代当期政策门槛。

用户要求研发中心或科技计划类项目的前期评估报告或可行性分析报告时，同时读取 `project-feasibility/references/two-report-contract.md`。研发中心可行性报告必须按现行正式评分表逐项拆解；正式评分表尚未发布时只列现行条件和竞争力，不虚构分值。科技计划类项目仅复用报告呈现、补强清单、国内与国际技术水平评价建议及红色水印要求，既有技术任务、团队、预算、里程碑和验收分析逻辑保持不变。

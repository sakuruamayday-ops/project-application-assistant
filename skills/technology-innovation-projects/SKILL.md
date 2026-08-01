---
name: technology-innovation-projects
description: 分析研发机构、企业研究院、科技计划、创新平台、科技奖励和成果类项目，核验研发条件、任务、预算、里程碑和验收指标；量产建设为主的任务转工业化或投资项目；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 科技创新项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "technology-innovation-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
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

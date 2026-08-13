---
name: digitalization-projects
description: 分析数字化车间、智能工厂、未来工厂、工业互联网、5G工厂和制造数字化改造项目，核验设备联网、系统运行、数据集成、闭环绩效和安全；纯软件研发或普通办公软件采购不适用；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 数字化项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "digitalization-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与边界

处理数字化车间、智能工厂、5G工厂、工业互联网和企业数字化改造。纯软件产品研发转科技创新或工业化项目；只采购办公软件不构成制造数字化能力。

## 七维核验

1. 设备与自动化基础。
2. 网络连接和设备数据采集。
3. 业务系统实际运行。
4. 系统与数据集成。
5. 数据驱动的计划、质量、设备或能源闭环。
6. 改造前后可复核绩效。
7. 网络与数据安全。

每项区分已运行、试运行、在建、计划和供应商方案。自主技术、集成实施和外购产品分别描述，不把采购系统写成企业自主知识产权。

成熟度和证据要求见 `references/digital-maturity-model.md`。输出当前等级、证据、短板和适用项目方向。

用户要求数字化项目的前期评估报告或可行性分析报告时，同时读取 `project-feasibility/references/two-report-contract.md`，围绕设备联网、系统运行、数据集成、业务闭环、绩效和安全形成项目专属条件表。前期报告突出已运行能力和关键缺口；可行性报告逐项给出证据、改造任务、验收标准和申报节点，不用采购清单替代实际运行证据。

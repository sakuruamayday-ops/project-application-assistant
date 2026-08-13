---
name: quality-brand-projects
description: 分析产品认定、制造精品、政府质量奖、标准品牌、市场地位、单项冠军和隐形冠军项目，先识别项目类型再核验对应质量、标准、认证、管理和市场证据；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 质量品牌项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "quality-brand-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与项目分型

处理产品认定、组织质量奖、标准品牌、市场地位和冠军类项目。开始分析前必须先确定项目类型，不得将浙江制造精品、质量奖和单项冠军混用一套条件。

## 核验维度

- 产品认定：产品、标准、检测、认证、质量稳定性和市场应用。
- 组织质量奖：质量管理模式、持续改进、经营绩效和组织治理。
- 标准品牌：标准先进性、认证、品牌建设和示范应用。
- 市场地位：细分市场定义、销售口径、市场容量、排名来源和期间。
- 冠军类项目：长期专注、单项产品、市场地位、创新和产业链作用。

市场占有率和排名必须调用 `evidence-ledger` 的市场份额合同，分别登记企业分子、上位市场、全部拆分系数、六同状态、申报值、复算值和来源。仅在工作簿中登记但未取得的底层文件、报告链接和企业陈述必须标记 `reference_only`，不得写成已取得的用户文件或已访问网页。企业自述或经验系数可作为明确标识的企业陈述来源，不自动视为第三方证明，也不因缺少第三方证明自动判D；完全无来源、边界冲突或公式不可复算时必须判D。涉及细分市场排名或冠军类项目时还必须调用 `industry-positioning`；排名另需独立证据，不得由占有率数值自动推出。项目分类和证据等级见 `references/quality-brand-taxonomy.md`。

单项冠军、隐形冠军和专精特新“小巨人”的排名门槛、分类层级和第三方材料规则各不相同；先锁定项目与版本，不得将“全球前三或国内第一”复制为通用门槛。

输出项目分型、硬门槛待核验项、评分证据、市场占有率A至D等级、不可证明项和下一步。分析报告正文只放轻量编号，完整来源列在文末；知识库来源对外只显示文件名。

用户要求制造精品或单项冠军的前期评估报告或可行性分析报告时，同时读取 `project-feasibility/references/two-report-contract.md`。制造精品切换到产品质量、标准、检测、技术先进性、市场应用、品牌和生产基础；单项冠军切换到单项产品边界、长期专注、市场地位、创新、质量和产业链作用。项目层级不明确且会改变条件时先最小确认，不得套用其他层级门槛。

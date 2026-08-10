---
name: consistency-check
description: 在政府项目材料提交前执行括号、数据、事实、四关联、路径、时间线和术语一致性闸门，定位跨章节冲突并给出保留、替换或补证后保留结论；不替代前期可行性分析。
---

# 一致性检查


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "consistency-check" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

作为正式交付前的最终质量闸门，定位跨章节冲突和不可追溯结论，不替代政策检索、财务核验或专业分析。

## 强制检查

1. **括号清零**：正式正文扫描中英文括号，表单固定字段和法规原文引用另行标注。
2. **数据溯源**：每个数字对应来源、期间和口径；总量与分项、比例与基数能够复算。
3. **事实验证**：政策、企业、知识产权和客户事实均有证据，推断不得写成事实。
4. **四关联**：主导产品分别与知识产权、补短板、填空白和国产替代形成同产品、同环节、同技术证据链。
5. **路径合规**：输出文件、归档和后续动作符合当前授权，不擅自提交或发送。
6. **横向一致**：企业名称、产品名称、项目年度、单位、时间线和专利状态在所有章节一致。
7. **来源配置**：按 `report-skill-registry.json` 核验来源位置。分析报告完整来源在文末；Excel和PPT分别在最后工作表和最后一页；标准正文不得出现报告式“数据来源”，但必须存在独立来源说明，且不得移动“规范性引用文件”。

## 判定

问题分为阻断、重大、一般和提示四级。主导产品、补短板、填空白和国产替代分别给出“保留、替换、补证后保留”，不得为保持原文而牵强解释。

## 输出与脚本

按位置列出原文、问题、证据、影响和建议修改。规则见
`references/consistency-gates.md`；纯文本初筛运行
`scripts/scan_formal_material.py`，脚本通过不等于专业检查通过。

增加案例串用检查：正文中的企业名称、数字、客户、专利和技术指标必须能回溯到当前企业事实台账；仅出现在 `case_reference` 或其他案例包中的内容一律阻断终稿。

---
name: application-version-diff
description: 对比政府项目申报材料的两个或多个版本，识别章节移动、新增删除、数字与来源、知识产权状态、政策依据和合规风险变化；单份材料质量检查使用consistency-check。
---

# 材料版本对比


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "application-version-diff" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

比较两版申报材料的结构、数据、表述和合规风险。单份材料检查使用 `consistency-check`。

## 流程

1. 确认旧版、新版、文件日期和比较范围，提取标题、段落、表格和附件清单。
2. 先按章节标题和字段键对齐，再做内容相似度匹配，避免把位置移动误判为删除和新增。
3. 将变化分为新增、删除、修改、移动和仅格式变化。
4. 数字变化同时显示前值、后值、单位、期间、差额和来源变化；不得只报告差额。
5. 单独检查企业名称、主导产品、知识产权法律状态、政策依据、申报年度和结论等级。
6. 将每项变化评为阻断、重大、一般或编辑性，并说明是否需要联动修改其他章节。
7. PDF、扫描件或复杂表格无法可靠解析时，先调用宿主 OCR 或文档解析能力；仍无法提取的，按页建立人工核对清单，标出“未解析区域”、页码和对象类型。输出比较完整度和未覆盖范围，禁止把解析失败写成“无变化”。

## 输出

先给变更概览，再给结构、数字、表述、合规风险和联动修改表。结构化差异格式见
`references/version-diff-rules.md`；已有结构化文本时可运行
`scripts/compare_material_json.py`，文件解析仍使用宿主的文档能力。存在未解析区域时，
结论必须限定为“已解析范围内的比较结果”，并附待人工核对清单。

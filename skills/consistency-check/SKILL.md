---
name: consistency-check
description: 在政府项目材料提交前执行括号、数据、事实、四关联、路径、时间线和术语一致性闸门，定位跨章节冲突并给出保留、替换或补证后保留结论；不替代前期可行性分析。
---

# 一致性检查


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "consistency-check" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
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

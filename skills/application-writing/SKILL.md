---
name: application-writing
description: 在项目版本、政策和企业事实核验完成后撰写政府项目正式材料，包括企业简介、主导产品、核心技术、补短板、填空白和产业链作用；不用于政策检索或资格判断。
---

# 申报材料撰写


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "application-writing" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

把已核验的政策要求和企业事实组织成正式申报文本。不得用写作替代政策检索、可行性判断或证据补齐。

## 前置门禁

1. 确认项目类型、申报年度、申请书版本、目标章节、字数和评审关注点。
2. 取得已核验政策、企业事实、证据台账及待补项。缺少关键事实时先列缺口。
3. 专精特新和小巨人材料必须确认申请书版本，并对主导产品、补短板、填空白和国产替代保留独立判断。

## 写作流程

1. 形成章节任务单：本段要回答的问题、必须出现的事实、禁止越界的结论和字数。
2. 按“结论→行业问题→企业做法或核心技术→量化指标→客户或产业化验证→项目价值”组织证据链。
3. 数字逐字复用来源，不缩位、不补造；缺失信息使用明确的待核验标记。
4. 正式正文不用中文或英文括号，不写无法核验的“国内领先”“填补空白”等绝对表述。
5. 企业简介和主导产品按 `references/application-section-patterns.md` 选择结构；当期表单有强制结构时以表单为准。
6. 完成后调用 `consistency-check`，未通过不得标记为终稿。

## 输出

同时给出正文、采用的事实编号和待补证据。咨询说明与正式正文分离，不把内部风险标签写入客户交付正文。

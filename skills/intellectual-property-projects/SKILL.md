---
name: intellectual-property-projects
description: 分析知识产权示范、管理体系、专利产业化、高价值专利组合、保护运用和商标品牌类政府项目，调用ip-assessment核验权利事实；FTO、侵权和无效分析转专利专业技能。
---

# 知识产权项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "intellectual-property-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与边界

处理知识产权示范、管理体系、专利产业化、保护运用、商标品牌等政府项目。专利侵权、FTO和无效稳定性分析转入专利专业链。

## 流程

1. 识别项目属于管理能力、权利质量、产业化运用、保护服务或品牌建设。
2. 调用 `ip-assessment` 形成权利状态和产品关联底稿。
3. 核验制度、人员、预算、检索预警、许可转让、质押融资、维权和转化收益。
4. 有效授权、审中、失效和转让取得分别统计，不把申请量冒充授权量。
5. 只采用当期政策认可的权利类型、取得时间和主体范围。

## 数据不足处理

只提供数量汇总、没有权利清单时，不形成权利质量结论。无法取得完整公开状态时，列出已核验和待核验权利，不将第三方平台数量视为最终口径。

## 输出

项目分类与证据见 `references/ip-project-taxonomy.md`。输出项目适配、事实、风险和材料缺口。

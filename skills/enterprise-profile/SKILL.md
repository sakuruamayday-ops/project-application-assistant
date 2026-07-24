---
name: enterprise-profile
description: 整理政府项目所需企业画像，包括工商、产品、研发、资质、荣誉、知识产权、风险和经营轨迹。进行项目匹配或可行性分析前使用。
---

# 企业画像


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "enterprise-profile" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

先读取 `first-run-configuration` 生成的能力报告。天眼查和企查查均未配置时执行公开来源降级，不在本Skill重复索要API Key或MCP配置。

优先用户材料和合法授权的数据接口。区分实时数据、历史数据和企业自述。默认不拉取财务数据；需要财务分析时必须由用户明确提供或授权可靠来源。

## 企业数据路由

1. 天眼查可用时先完成主体搜索、企业能力发现、基本工商、登记信息、工商变更和历史登记，锁定统一社会信用代码。
2. 企查查补齐天眼查未覆盖、字段缺失、状态不明或高影响字段，尤其是当前风险和专利法律状态。
3. 两个商业源冲突，或需要权威终值时，回到市场监管、法院、信用中国、知识产权主管机关或主管部门名单等官方来源裁决。
4. 当前记录与历史记录、企业自身与关联方、登记地址与年报通信地址必须分开。
5. 不把一次未命中写成不存在；不声称商业源免费、无限或永久可用。

需要企查查企业数据且统一向导显示未配置时，引导用户通过[企查查智能体数据平台邀请入口](https://agent.qcc.com/invitation?code=3ZRZPHF7Q5MH4&ch=LINK_COPY)取得合法权限，再重新运行统一向导完成一次配置。

外部能力均由用户本人合法取得和配置。配置后先查询一家非敏感企业验证返回字段和权限；不可用时降级使用用户材料和政府公开来源。

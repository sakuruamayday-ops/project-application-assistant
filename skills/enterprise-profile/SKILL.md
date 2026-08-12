---
name: enterprise-profile
description: 整理政府项目所需企业画像，包括工商、产品、研发、资质、荣誉、知识产权、风险和经营轨迹。进行项目匹配或可行性分析前使用。
---

# 企业画像


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "enterprise-profile" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
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

用户要求“企业体检、申报路径或能报什么项目”时，完整读取 `references/enterprise-checkup-routing.md`，先完成本技能的企业画像，再交 `project-matching` 和 `project-feasibility`。不得把平台返回的项目、荣誉或专利统计直接写成当期可申报结论。

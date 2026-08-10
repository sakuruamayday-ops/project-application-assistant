---
name: intellectual-property-projects
description: 分析知识产权示范、管理体系、专利产业化、高价值专利组合、保护运用和商标品牌类政府项目，调用ip-assessment核验权利事实；FTO、侵权和无效分析转专利专业技能；若只核验旧通知、政策版本、效力或完整文件链，本技能不适用，必须以policy-retrieval为主技能。
---

# 知识产权项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "intellectual-property-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
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

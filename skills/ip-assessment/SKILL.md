---
name: ip-assessment
description: 建立企业专利、商标和软著等知识产权事实底稿，核验权利状态、取得方式、主体变更、产品技术关联和政府项目证据价值；权利要求、FTO、侵权或授权前景分析转专利专业技能。
---

# 知识产权评估


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "ip-assessment" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与边界

建立企业知识产权事实底稿并判断其申报证据价值。FTO、侵权风险、权利要求技术范围、申请方向、挖掘交底和地方预审统一调用 `patent-router`；只检查中国专利申请 Word 时调用 `checking-patdocx-cn-single-agent`。

## 流程

1. 锚定权利人主体和统计截止日期。
2. 专利事实由本技能统一申请号、公开号、授权号、类型和法律状态；进入专利工程分析时交给 `patent-router`，并沿用相同法域、基准日和证据来源。
3. 区分有效授权、审中、失效、转让取得、许可、质押和争议状态；商标、软著等使用各自公开状态。
4. 核验申请人或权利人变更、取得时间、共同权利人和项目政策认可范围。
5. 逐项映射主导产品、核心技术、生产工艺和项目任务，关系不明时不得仅凭名称判定相关。
6. 输出可直接使用、仅作技术分析、待补证和不建议用于申报四类。

权利状态和关联规则见 `references/ip-assessment-rules.md`。结构化清单可运行
`scripts/validate_ip_inventory.py`。

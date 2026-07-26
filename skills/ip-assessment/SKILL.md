---
name: ip-assessment
description: 建立企业专利、商标和软著等知识产权事实底稿，核验权利状态、取得方式、主体变更、产品技术关联和政府项目证据价值；权利要求、FTO、侵权或授权前景分析转专利专业技能。
---

# 知识产权评估


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "ip-assessment" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与边界

建立企业知识产权事实底稿并判断其申报证据价值。FTO、侵权风险、权利要求技术范围、申请方向、挖掘交底和地方预审统一调用 `jiaotang-patent-router`；只检查中国专利申请 Word 时调用 `checking-patdocx-cn-single-agent`。

## 流程

1. 锚定权利人主体和统计截止日期。
2. 专利事实由本技能统一申请号、公开号、授权号、类型和法律状态；进入专利工程分析时交给 `jiaotang-patent-router`，并沿用相同法域、基准日和证据来源。
3. 区分有效授权、审中、失效、转让取得、许可、质押和争议状态；商标、软著等使用各自公开状态。
4. 核验申请人或权利人变更、取得时间、共同权利人和项目政策认可范围。
5. 逐项映射主导产品、核心技术、生产工艺和项目任务，关系不明时不得仅凭名称判定相关。
6. 输出可直接使用、仅作技术分析、待补证和不建议用于申报四类。

权利状态和关联规则见 `references/ip-assessment-rules.md`。结构化清单可运行
`scripts/validate_ip_inventory.py`。

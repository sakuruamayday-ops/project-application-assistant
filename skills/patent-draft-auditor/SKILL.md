---
name: patent-draft-auditor
description: 对发明、实用新型或外观设计申请文件开展提交前全量风险检查，覆盖形式、保护客体、新颖性、创造性、实用性、充分公开、权利要求支持与清楚性、必要技术特征、单一性、修改超范围、同日双申、申请权、公开、保密审查、遗传资源、非正常申请及程序风险。用户要求检查完成的专利文案、专利法风险、26.3、创造性或形式问题时使用。
---

# 专利申请质检


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-draft-auditor" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

先使用 `patent-data-foundation` 建立版本和状态口径；涉及授权性或稳定性时使用 `patent-search-core` 先生成检索式及IPC/CPC计划。

## 双层检查

1. 文本内可检查风险：读取 [legal-risk-matrix.md](references/legal-risk-matrix.md) 逐项检查。
2. 外部事实风险：申请权、发明人、申请前公开、合作开发、外国申请保密审查、遗传资源、优先权和同日双申必须向用户索取证据；资料不足标为“无法检查”。

## 强制动作

- 自动生成权利要求依附关系表和Mermaid图。
- 已存在公开版与授权版时强制执行A/B差异对比。
- 检查摘要特征是否进入权利要求。
- 对每项风险给出法条或指南依据、证据位置、等级、修改建议和需补资料。
- 输出红色必须处理、黄色建议处理、绿色当前未发现明显问题。

不得声称仅凭一份申请文件已经排除全部法律风险。交付物标明供专利代理师或律师复核。

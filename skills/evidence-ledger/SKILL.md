---
name: evidence-ledger
description: 建立事实、计算、推断和待核验四类证据台账，记录来源、原文位置、期间、冲突和结论引用关系，为项目匹配、可行性、写作和检查提供统一可追溯底稿。
---

# 证据链台账


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "evidence-ledger" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

为项目匹配、可行性分析、写作和检查提供统一证据底稿。不得把证据台账当成结论生成器。

## 证据类型

- `fact`：来源直接陈述的事实。
- `calculation`：基于已列事实形成的计算结果，必须记录公式和输入项。
- `inference`：基于事实形成的专业判断，必须说明推理边界。
- `pending`：缺少可靠材料或存在冲突，尚不能确认。

## 强制流程

1. 为企业、政策、知识产权和项目建立稳定主体标识。
2. 每条记录填写证据编号、主张、类型、来源、获取日期、原文位置、适用期间和核验状态。
3. 计算记录必须引用输入证据编号；推断记录必须引用支撑事实并列出反证或限制。
4. 同一字段来源冲突时建立冲突组，不覆盖、不平均、不静默选择。
5. 正式结论只能引用状态为已核验的事实或可复算计算；待核验项不得写成确定事实。
6. 交付时同时输出证据台账和未闭合证据缺口。

## 输出与校验

台账字段、来源等级和冲突规则见 `references/evidence-ledger-schema.md`。
形成JSON台账时运行 `scripts/validate_evidence_ledger.py`；校验失败不得进入正式写作。

历史案例证据单独标记为 `case_reference`，记录 `case_pack_id` 和文档编号；它只能证明参考结构或证据类型，不能证明当前企业事实，也不能提升政策来源等级。

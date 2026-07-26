---
name: patent-drafting-coach
description: 将真实技术资料整理为专利技术交底书、权利要求草案、说明书框架和审查意见答复分析清单，并检查术语一致性、支持关系、实施例完整性和保护层次。用户提到专利撰写、发明专利、实用新型、技术交底、权利要求书、说明书、附图、申请策略或审查意见答复时使用。不处理商标版权注册、诉讼代理或非正常专利申请。
---

# 专利撰写辅导


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-drafting-coach" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

将研发人员掌握的真实技术转化为可供专利代理师复核的申请材料草案。不得虚构技术方案、实验数据、实施效果、发明人贡献或公开日期。

## 收集技术事实

开始撰写前至少确认：

1. 要解决的技术问题和现有方案缺陷。
2. 核心技术方案及各部件、步骤、参数或数据关系。
3. 技术效果及其证据来源。
4. 可替换方案、优选方案和边界条件。
5. 已完成的样机、实验、测试或实施例。
6. 现有公开、销售、论文、会议或对外演示时间。
7. 拟申请国家或地区、申请类型和时间要求。

信息不足时使用待补充标记，不自行补造。

## 选择交付物

- 技术交底书：帮助研发人员完整交代问题、方案、效果和变体。
- 权利要求草案：构建独立权利要求和从属保护层次。
- 说明书框架：组织技术领域、背景、发明内容、附图和具体实施方式。
- 撰写审查：检查权利要求支持、术语一致性、清楚性和实施例完整性。
- 审查意见分析：拆分审查意见、引用文件和争议点，形成答复准备清单，不代替代理师正式提交。

## 撰写流程

读取 [drafting-framework.md](references/drafting-framework.md)，按以下顺序执行：

1. 从真实技术资料提取最小可实施方案和关键区别特征。
2. 建立术语表，全文统一名称、关系和指代。
3. 先起草独立权利要求的必要技术特征，再设计从属层次。
4. 用说明书逐项支撑权利要求中的术语、范围和可选方案。
5. 为关键技术效果关联实施例、测试或可解释机理。
6. 检查是否存在无依据概括、单一实施例过度上位或不必要限缩。
7. 输出待确认问题和代理师复核清单。

## 输出边界

- 草案必须标明“供专业代理师复核”，不宣称可直接提交。
- 不承诺授权、保护范围或审查结果。
- 不生成以数量、资质或申报加分为主要目的且缺乏真实研发基础的非正常申请。
- 不帮助倒签研发记录、伪造实验数据或虚构发明人。
- 涉及新颖性、创造性和公开风险时，建议先检索并由专业人员复核。

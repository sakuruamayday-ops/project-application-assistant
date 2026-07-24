---
name: patent-layout-planning
description: 根据企业产品路线、核心技术、现有专利、检索结果、竞争壁垒和政府项目节点规划未来专利组合，输出候选方向、证据准备、优先级和申请节奏；申请文件、预审方向和FTO分别转对应专利技能。
---

# 专利布局规划


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-layout-planning" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责与依赖

根据产品路线、核心技术、竞争壁垒和项目要求规划未来专利组合。按
`patent-data-foundation` → `patent-search-core` → 本技能 → `patent-drafting-coach`
执行，不跳过现有专利和现有技术检索。

## 流程

1. 明确商业目标、项目节点、目标产品、技术路线和已有证据。
2. 建立产品模块、材料、结构、工艺、控制、检测和应用场景技术树。
3. 将有效授权、审中申请和现有技术映射到技术树，识别重复、空白和薄弱环节。
4. 对候选方向按商业关联、技术成熟度、差异空间、可取证性、规避难度和时间紧迫度评分。
5. 设计核心、改进、防御和外围组合，区分发明与实用新型适用对象。
6. 输出布局主题、拟保护对象、关联产品、证据准备、申请优先级和节奏。

评分与输出规则见 `references/patent-layout-scoring.md`；结构化候选可运行
`scripts/score_patent_layout.py`。不得承诺授权或政府项目认可。

---
name: patent-benchmark-landscape
description: 根据客户行业和地域选择国内或本地可比龙头，清洗集团关联申请人和专利族，分析其专利年度趋势、IPC/CPC、技术主题、核心权利要求、法律状态和技术演进，形成客户差距、布局方向并生成可追溯PPT。用户要求分析龙头专利布局、竞品技术路线、专利地图或生成专利布局PPT时使用。
---

# 专利对标布局


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-benchmark-landscape" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

依次使用 `patent-data-foundation` 和 `patent-search-core`。

## 工作流

1. 明确客户产品、技术链、地域和对标目的。
2. 按市场地位、产品重合、技术可比性和数据可得性选择国内龙头与本地龙头。
3. 建立集团申请人、曾用名、子公司和转让关系清单。
4. 以简单同族去重并按有效状态、申请趋势、分类号和技术主题分析。
5. 回看各主题代表性独立权利要求，避免仅凭摘要聚类。
6. 对比客户现有专利，识别拥挤区、空白区和可验证的技术方向。
7. 按 [ppt-outline.md](references/ppt-outline.md) 生成PPT，并在每页保留数据口径与来源。

不得把专利数量直接等同于技术实力，不得把集团参股企业全部专利自动计入龙头布局。

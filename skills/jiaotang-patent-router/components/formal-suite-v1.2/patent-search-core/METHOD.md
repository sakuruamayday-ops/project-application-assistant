---
name: patent-search-core
description: 为专利方向规划、相似专利检索、创造性稳定性分析、FTO和行业布局生成统一检索计划，覆盖技术特征拆解、关键词与同义词、IPC/CPC、申请人、日期边界、引证扩展和结果分层。需要查找相似专利、在先技术、竞争对手专利或开展稳定性分析时使用，并先调用 patent-data-foundation。
---

# 专利检索核心


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-search-core" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

先使用 `patent-data-foundation` 建立数据口径。检索前必须形成书面计划，不直接用专利标题搜索后下结论。

## 检索计划

1. 明确法域、基准日、目标任务和文本版本。
2. 拆分独立权利要求或技术方案的必要技术特征。
3. 为每项特征生成关键词、同义词、上位词、下位词和中英文表达。
4. 生成IPC/CPC候选分类及分类定义核验计划。
5. 组合标题摘要、权利要求、分类号、申请人和日期检索式。
6. 先宽检索，再按区别特征收窄，并扩展引证、被引证和同族。
7. 记录每轮查询式、数据源、日期、命中数和筛选原因。
8. 将结果分为核心对比、强相关、背景相关和排除。

读取 [search-protocol.md](references/search-protocol.md) 执行不同任务的停止条件。可使用 `scripts/build_search_plan.py` 生成检索计划骨架。

## 强制边界

- 相似度只用于排序，不直接等同于不新颖、无创造性或侵权。
- 稳定性检索与FTO检索分开执行；FTO使用独立技能 `patent-fto-analysis`。
- 没有核验分类定义时不得仅凭分类号名称判断匹配。
- 检索未命中只说明当前检索层未命中。

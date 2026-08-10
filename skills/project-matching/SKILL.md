---
name: project-matching
description: 从政府项目库中匹配企业可申报方向。适用于用户询问能报哪些项目、需要多项目矩阵、申报优先级或年度路线图。
---

# 项目匹配


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-matching" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

根据地区、行业、规模、产品、研发、资质、知识产权和投资计划筛选项目。输出候选项目、匹配依据、明显缺口、时效状态和优先级。候选结果不替代单项目可行性分析。

## 强制判断链

1. 读取 `references/canonical-project-index.jsonl` 和 `references/project-matching-rules.md`，先判断“理论上应关注哪些项目类型”。再按标准项目名称检索 `references/high-frequency-project-rules.jsonl`，优先使用已有高频项目条件缩小候选范围。
2. 用企业地区、行业、产品、规模、资质、研发、知识产权和投资计划对候选项目进行召回和排序。
3. 用户已明确启用实验性 `third-party-data-indexing` 时，检查SQLite索引的最后成功日期；索引不是当日时标记陈旧并在用户授权后更新或补采。未启用或更新失败时直接降级检索官方来源，不阻断项目匹配。
4. 对所有拟推荐项目调用政策检索能力，核验政府官方管理办法、当期通知、截止时间和附件。
5. 只有完成官方核验的项目才能进入“当期可申报”；其余项目标记为“培育方向”、“索引命中待核验”或“历史项目”。
6. 项目检索或成长路径中存在当前仍在申报期的项目时，读取企业申报截止时间，按北京时间计算并提醒“距离截止还有多少天”。企业申报截止与主管部门报送截止并存时优先企业截止；截止对象不明确时只提示核验时间，不输出精确倒计时。

## 高频简称门禁

- 读取 `references/high-frequency-project-retrieval-rules.json`，按其中的正式项目、允许标题和排除标题执行检索，禁止只凭正文中出现同一关键词混入其他项目。
- 只问“科小”时，必须先让用户选择“浙江省科技型中小企业”或“国家科技型中小企业”。
- 只问“绿色工厂”时，必须先确认区级、市级、浙江省级或国家级，并补充地区。
- 只问“未来工厂”时，明确地域后分别映射“杭州市AI工厂”或“浙江省未来工厂”；地域未说明时先让用户二选一，不得把杭州项目和省级项目混成同一条推荐。
- 只问“单项冠军”时，必须先确认浙江省制造业单项冠军企业或国家制造业单项冠军企业。
- “重点小巨人”只指重点小巨人企业高质量发展奖补项目；“重点省专”“重专”才映射浙江省重点专精特新中小企业，两者不得互换。
- “杭州研发中心”“杭州市研发中心”“市高企研发中心”统一转为“杭州市企业研究院”。正式办法发布前，使用2026年征求意见稿开展预评估，并明确其尚未正式生效。

## 项目地图边界

- 项目地图只用于回答“知道要找什么”，不表示项目当前开放。
- 动态索引用于回答“现在有没有”，第三方数据只作发现线索。
- 官方原文用于回答“最终能不能报”，并且必须结合企业可靠数据逐项核验。
- 管理办法、认定条件、材料模板和历史案例保留在规则层；企策顾问的通知、公示和名单保留在动态层。两层不做物理合并，只按查询意图排序。
- “条件、门槛、标准、材料、模板”后台先查规则层；“最新、通知、公示、名单、截止、具体年度”后台先查动态层；只有项目简称时先确认意图。内部层级不得在网站答复或交付文件中显示。
- 地图中的项目名称、级别和主管部门是分类线索，不得据此承诺企业一定符合或一定获批。
- 倒计时只依据当前有效的申报通知或指南动态生成，不写入项目地图，也不把历史截止时间当作当前开放状态。

## 地区过滤

- 默认读取企业全生命周期助手已记忆的地区范围，只召回 `primary_region` 属于该范围的项目，不得因共享同一市级或省级父节点而加载兄弟区县政策。
- 区县用户默认范围为该区县、所属市、所属省和全国。
- `regions=["待确认"]` 的项目不进入默认结果，只在用户点名项目或扩大检索范围时召回。
- 临时检索其他地区时使用临时范围，不覆盖用户默认地区。
- 当日索引更新因登录或浏览器人工接管而未完成时，标记“动态索引待更新”并降级检索官方来源，不得把旧索引当作当日完整数据。

## 资源

- `references/project-map.jsonl`：已删除供应商标识和内部编号的默认项目地图；数量较大时按关键词检索，不要整份加载。
- `references/canonical-project-index.jsonl`：原项目地图与高频项目的统一标准名称、别名和关系索引。无可靠原地图匹配的项目作为高频扩展项保留，不强行合并。
- `references/high-frequency-project-rules.jsonl`：高频申报项目的条件线索。表格条件只作历史召回依据；专精特新与研发机构必须使用其中的新版规则卡。
- `references/project-matching-rules.md`：企业画像召回、排除、排序、时效和证据规则。
- `references/high-frequency-project-retrieval-rules.json`：高频简称、正式项目、选择提示、允许项目和串项排除规则。
- `scripts/build_project_map.py`：从本地 Markdown 项目目录重建脱敏地图，默认不输出来源字段、内部编号和第三方内容。
- `scripts/build_high_frequency_rules.py`：从用户维护的政策更新表与新版 Markdown 规则重建高频条件卡。
- `scripts/filter_project_map.py`：按用户默认地区范围和企业关键词过滤统一地图，避免将其他地区项目加载进上下文。

匹配结果应返回稳定 `project_id`，供政策、模板、案例包和附件关系共用。市级与省级同名项目必须先完成地区层级澄清，再允许调用 `knowledge_case_pack`，不得把不同层级案例混成一组。

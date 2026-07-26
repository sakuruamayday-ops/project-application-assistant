# 原十个专利技能归属清单

基准日：2026-07-26。十个原始技能已归并为一个主入口、三个内部专业组件和一个独立核稿技能。六个重复入口已完成 103 个文件的逐项审计；保留资产已经合并，原目录按工作区安全规则移入系统废纸篓，可恢复但不再参与触发。

## 当前数量口径

- 核心专利体系：5 个技能单元，即 1 个总路由、3 个内部组件、1 个独立核稿技能。
- 核心顶层入口：2 个，即 `jiaotang-patent-router` 与 `checking-patdocx-cn-single-agent`。
- 外围按需能力：`bigquery-patent-search`、`patent-layout-planner`、`qcc-ip-infringement-alert`。前两项属于专利专项辅助，后一项属于包含专利在内的知识产权侵权初筛，不计入五个核心单元。

## 已合并进焦糖专利综合审查

| 原技能 | 当前归属 | 状态 |
|---|---|---|
| patent-lawyer-agent | `components/patent-lawyer-agent/`，作为 P1 | 内部组件，不再独立触发 |
| patent-mining-disclosure-skill | `components/patent-mining-disclosure-skill/`，作为 P2 | 内部组件，不再独立触发 |
| patent-preliminary-examination-check | `components/patent-preliminary-examination-check/`，作为 P3 | 内部组件，不再独立触发 |

## 保持独立

| 原技能 | 当前归属 | 状态 |
|---|---|---|
| checking-patdocx-cn-single-agent | 套件顶层 `checking-patdocx-cn-single-agent/` | 独立活动技能，只做申请文件核稿 |

## 已完成文件级审计的旧入口

逐文件结果：`references/legacy-skill-file-audit-20260726.csv`。

原目录已于 2026-07-26 移入系统废纸篓：
主人本机系统废纸篓中的审计归档目录。

| 原技能 | 最终处理 |
|---|---|
| patent-review | 三阶段核查方法合并进独立核稿技能；重复入口和元数据淘汰 |
| hongzhua-zhuanli | 权利要求引用链与审查意见方法合并进 P1/核稿；宽泛全流程入口淘汰 |
| cn-patent-examination-guide-2023 | 四份参考资料保留为 2023 历史基线，并强制叠加 2026 现行国家规则；旧入口淘汰 |
| patent-disclosure-skill | 专利通俗解读、Obsidian 图谱、转换工具和资产合并进 P1 工具包；重复交底流程淘汰 |
| global-biblio-base | 需外部邮箱、配额且无本地不可替代资产，全部淘汰；需要非专利文献时按任务显式检索 |
| patent-mining-expert | TRIZ 与创新点方法合并进 P2；可能诱导补造实验数据的模板和重复入口淘汰 |

处置原则是“保留不可替代资产、关闭重复入口”。废纸篓中的原目录仅用于短期恢复，不应重新注册为活动技能。

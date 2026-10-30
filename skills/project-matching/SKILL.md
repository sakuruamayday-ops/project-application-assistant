---
name: project-matching
description: 按企业地区、产品、研发、资质、知识产权和投资计划匹配政府项目，形成候选、优先级、多项目矩阵及年度路径。
---

# 项目匹配

围绕用户目标输出项目方向、依据、差距、时效和优先级；单项目详细判断按需衔接 `project-feasibility`。任务组织参考[共享任务说明](../_runtime/task-execution.md)。

## 匹配方法

1. 参考 `references/policy-application-path-contract.md`、`canonical-project-index.jsonl`、`project-matching-rules.md`，按企业条件召回相关类型，再用 `high-frequency-project-rules.jsonl` 的标准名称及条件线索缩小范围。
2. 用地区、行业、产品、规模、研发、资质、IP 和投资排序，调用当前可用知识及官方来源核验办法、通知、截止和附件。
3. 使用 `third-party-data-indexing` 时记录最后成功日期和覆盖范围；待更新索引作发现线索，官方来源与现有资料继续分析。
4. 分列当期可申报、培育方向、索引命中待核验和历史项目。企业截止与部门截止分别列示，明确企业截止后按北京时间算剩余天数。

## 完整路径

正文保留与企业相关的主目标梯度、研发平台、绿色、数字化、IP、质量品牌和产业化方向，按当期、建设后、条件触发或长期梯度排序。每项采用路径合同的十二字段，列起点、任务、依赖、建议年度、流程、证据、关键条件和责任动作。无业务关联的类型简述排除依据。未来政策待发布时标规划参考并设重检节点。

## 简称与地区

按 `references/high-frequency-project-retrieval-rules.json` 映射正式名称。含混简称可结合地域和上下文给候选并继续已确定部分：

- 科小分浙江省科技型中小企业、国家科技型中小企业；绿色工厂分区县、市、省、国家。
- 未来工厂按地区对应杭州市 AI 工厂或浙江省未来工厂；单项冠军分浙江省和国家。
- 重点小巨人为重点小巨人企业高质量发展奖补，重点省专、重专对应浙江省重点专精特新中小企业。
- 杭州研发中心、市高企研发中心等对应杭州市企业研究院，参考 `technology-innovation-projects/references/current-rd-platform-baseline-2026.md`，年度通知、征求意见和长期办法分别标状态。

地区采用本轮范围或已确认默认值。区县通常覆盖该区县、所属市、省和全国，其他区县在用户指定比较时加入。`regions=["待确认"]` 保留待核，临时地区范围与长期偏好分别管理。

## 来源与资源

项目地图提供分类，动态索引提供通知线索，官方原文与企业数据支持实际判断。条件、模板侧重规则资料，通知、名单、截止侧重动态资料，结合原文核验；输出呈现核验结果、文件和链接。

资源在 `references/`：`project-map.jsonl` 为脱敏地图；`canonical-project-index.jsonl` 统一名称别名；`high-frequency-project-rules.jsonl` 为条件卡；`project-matching-rules.md`、`high-frequency-project-retrieval-rules.json`、`policy-application-path-contract.md` 为方法及路径字段。

`scripts/build_project_map.py`、`build_high_frequency_rules.py` 重建地图和卡片，`filter_project_map.py` 按地区与关键词筛选。输出稳定 `project_id` 供政策、模板、案例和附件共用；案例按地域层级及标准项目取用。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

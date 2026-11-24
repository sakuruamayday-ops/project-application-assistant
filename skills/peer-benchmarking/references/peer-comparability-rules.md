# 同行可比性规则

可比性依次核验：同一项目、同一政策版本、同一认定层级、同一地区口径、同一细分产品、相近商业模式、相近规模。

对标按具体行业、产品和当期规则核对，不同年度先统一评价口径。

公开名单只证明入选结果。未公开的申请数据、评分和专家意见一律标记未知。

输出高、中、低可比性，说明成立依据及差异项。

用 `scripts/classify_peers.py <输入.json>` 核对直接对标组。填 `target.project`、`target.batch` 及 `candidates`。每个候选按原件登记 `product_relation`、`product_source`、`project`、`batch` 和 `recognition_source`。产品关系取 `same`、`broader`、`different` 或 `unknown`。覆盖较宽的市场数据及跨项目、跨批次记录保留为背景。交付形态不同则排除。同产品、同项目、同批次且认定原件齐全时，`decision=include`。在 `recognition_stage` 填原件状态，正式认定进入直接组，公示拟认定等同认定进入主要对标范围，列在拟认定/公示组。`group` 用于分组，`group_label` 在主要对标范围内显示原始阶段。未标注原件阶段的既有输入单列。结合地区、商业模式和规模判断可比程度。

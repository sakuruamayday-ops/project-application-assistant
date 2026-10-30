# 共创研究院业务语义叠加规则

将本文件附加在官方 Graphify extraction spec 之后。官方 JSON 结构、ID、路径、安全与置信度规则继续生效。

## 实体属性

在节点上增加以下可选属性；缺少来源的字段保持 `null`：

- `entity_kind`: `enterprise|project|policy|policy_clause|criterion|application_field|product|technology|patent|software_copyright|trademark|financial_metric|business_metric|customer|evidence|source_document|risk|judgment|timeline_event|version`
- `fact_status`: `KNOWN|COMPUTED|INFERRED|FRAME`
- `source_tier`: `official_core|official_department|enterprise_provided|aggregator|derived`
- `data_period`: 原文期间
- `unit`: 原文单位
- `original_value`: 原文数值字符串，保留全部小数位
- `jurisdiction`: 国家、省、市或区县
- `document_number`: 政策文号
- `effective_date`: 生效日期
- `expiry_date`: 失效日期
- `legal_status`: 材料或权威来源明确列示的知识产权状态
- `review_status`: `pending|keep|replace|keep_after_evidence`

节点的 `file_type` 使用官方定义的六种值；业务类型写入 `entity_kind`。

## 业务关系

除官方关系外，可使用：

`requires|supports|evidences|derived_from|applies_to|issued_by|supersedes|interprets|conflicts_with|consistent_with|owns|owned_by|controls|protects|used_by|uses|contributes_to|measured_by|corresponds_to|lacks_evidence_for|transferred_from|supplies_to`

关系方向遵循“来源实体作用于目标实体”：

- `evidence --evidences--> claim`
- `policy_clause --requires--> criterion`
- `patent --protects--> technology`
- `technology --supports--> product`
- 指标测量用 `claim --measured_by--> metric`，来源另连对应证据关系。
- 新版本 `--supersedes-->` 旧版本
- 原值节点 `--conflicts_with-->` 冲突原值节点

显式原文关系用 `EXTRACTED/1.0`，跨材料一致但缺直接表述用 `INFERRED`；名称相似、共现和行业常识登记为线索，置信度随证据强度标记。

## 事实与版本

1. 每个政策节点尽量记录标题、文号、发布机关、地域、发布日期、施行和失效日期。
2. 同名政策的不同年度或地域建立独立节点，用 `supersedes` 或 `conflicts_with` 连接，不静默合并。
3. 财务、比例、金额和指标逐字保留 `original_value`、`data_period`、`unit`；计算值另存，官方终值保留原值。
4. 申请材料提供的经营、财务、技术、客户、产能和专利状态作为 `enterprise_provided` 的工作事实。发现内部矛盾时保留两边并连接 `conflicts_with`。
5. 政策现行性、企业登记和司法状态由外部权威来源复核；图谱共现不是核验。

## 四项待审判断

主导产品、补短板、填空白、国产替代建立 `entity_kind=judgment`、`review_status=pending` 节点。专项判断核对产品边界、技术因果、同类同环节、数据口径和跨章节一致性后，可据企业自述标为 `keep`。

专项判断完成后，`review_status` 使用：

- `keep`
- `replace`
- `keep_after_evidence`

判断节点连接企业自述及逻辑依据，内部冲突另连冲突节点。`keep_after_evidence` 的补充材料按具体缺口确定，优先使用自述、计算和项目目录已有资料。

## 输出纪律

- 所有关键节点有 `source_file`。
- 事实冲突保留各来源节点，用来源等级、冲突关系和采用理由表达。
- 现实来源未命中时只表达“当前检索层未命中”。
- 图谱提供事实关系和判断依据，获批、法律和业务结论据实际任务证据说明。

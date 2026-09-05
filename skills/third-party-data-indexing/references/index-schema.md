# SQLite索引数据规范

## 核心记录

| 字段 | 含义 |
|---|---|
| `source_record_id` | 原始记录 ID，接受 `id`；与 SQLite 内部主键分开 |
| `year` | 记录适用年度；不补造成发布日期 |
| `source_version` | 来源标示的版本，接受 `version`；与本地递增版本分开 |
| `article_source` | 逐条文章来源，接受 `source`；`--source` 单独标记采集来源命名空间 |
| `title` | 政策、项目或公示标题 |
| `region` | 页面显示的适用地区 |
| `record_type` | 申报通知、管理办法、公示等 |
| `publish_date` | 发布日期 |
| `issuer` | 发布或发文机构 |
| `application_status` | 保留来源状态，接受 `status`，包括申报中、已截止、active、inactive 等 |
| `active` | 索引可用状态；显式 inactive、false、0 为失效，保留记录和版本，通过 `--include-inactive` 查询；申报已截止本身不使政策失效 |
| `application_period` | 页面显示的申报时间 |
| `detail_url` | 第三方详情页 |
| `official_url` | 政府官方原文链接 |
| `verification_status` | 未核验、已核验、官方原文未命中 |
| `authorization_scope` | 用户授权的本地使用范围 |
| `first_seen_at` / `last_seen_at` | 首次和最后采集时间 |
| `eligibility_conditions` | 申报条件原文；附件未解析时明确标记 |
| `beneficiary_companies` | 通过、获批或公示企业名称数组 |
| `beneficiary_count` | 页面明确标示的名单数量，不推算 |
| `query` / `page_number` | 检索条件及来源页码 |

## 采集质量

- `collection_metrics` 记录尝试页数、成功页数、详情请求、最小和最大间隔、限频、验证码及登录失效次数。
- `official_link_checks` 保存官方链接检查时间、HTTP状态、最终链接和有效性。
- 名单数量存在但企业名称未取得时，保留数量并标记“名单待解析”，不得生成虚构名单。

## 去重顺序

1. 采集来源命名空间内的 `source_record_id`，标题、年度或源版本变化仍更新同一记录。
2. `detail_url` 中的 `id` 和 `indexId` 组合。
3. 官方原文URL。
4. 规范化标题、发文机构和发布日期组合哈希。

不同采集来源或不同显式记录 ID 不因同名合并。`query --year 2026` 优先匹配明确年度；无年度的旧记录按发布日期年份查询，不将推导年份写入原始数据。

同一去重键的内容哈希变化时新建版本，不静默覆盖历史记录。

## 采集批次

每次执行记录范围、采集日期、状态、新增、变更、重复、失败、官方链接缺失和错误摘要。失败日期不更新成功检查点，下次自动补采。

## 安全

- 数据库不设置密码、Cookie、Token、Authorization或浏览器存储字段。
- 默认不保存第三方原始响应，只保存标准化业务记录和内容哈希。
- GitHub只发布工具和假数据测试，不发布真实索引库。

# 结构化交付信封

`hightech_delivery_gate.py finalize` 在核验回执中加入 `delivery`。通过 `--report` 指定的 JSON 文件与标准输出均包含该信封。

| 字段 | 取值 |
| --- | --- |
| `status` | `success` 对应成品可读且核验通过，`partial` 对应已交付可用成品并有核验缺项或差异，`fail` 对应成品不可读取或指定回执路径占用输入文件。 |
| `resource_id` | `hightech-application-delivery`，标识高企申请书交付类型。 |
| `content` | 已交付申请书与随附回执的 Markdown 文件索引，逐份列路径和文件 SHA-256。失败时返回实际错误的 Markdown 正文。 |
| `sha256` | 对 `content` 的完整 UTF-8 字节计算 SHA-256，使用小写十六进制。 |
| `delivered_at` | 本次生成交付回执的 ISO 8601 时间，使用 UTC 时区。 |

原核验状态和模板、粒度和视觉回执继续用于核验。交付内容与核验回执各自的摘要按对应字段读取。

字段回填回执分列 `batch_check.status` 与 `financial_reconciliation.status`。项目合计、年度汇总或委外费用冲突时保留重开的 Word 和原值，整体状态为 `partial`，沿缺陷项、差距、补强动作、优先级处理。改正财务口径后用新的输出路径重新生成，再做定稿验收。

# 证据台账结构

## 顶层对象

新台账使用 `grounded-evidence/v1`：

```json
{
  "schema_version": "grounded-evidence/v1",
  "sources": [],
  "records": [],
  "document": {"blocks": []},
  "market_share": {}
}
```

`sources` 和 `records` 是核心；`document` 仅在需要确定性渲染时使用；`market_share` 仅在市场占有率任务中使用。旧版记录数组和 JSONL 继续支持基础校验，但不能通过严格溯源校验。

## 来源登记 `sources`

通用字段：`id`、`kind`、`access_status`。来源编号建议使用 `S1`、`S2` 并在同一任务内保持稳定。

- `access_status = obtained`：已取得并实际读取原文，必填 `retrieved_at`。
- `access_status = reference_only`：只在另一份已取得材料中看到文件名、报告名或链接，原文未取得。必填 `registered_at` 和 `registered_via`；`registered_via` 指向已取得的登记载体。该状态不得填 `retrieved_at`，不得支撑 `verified` 记录。

`kind` 允许：`official_web`、`public_web`、`research_report`、`knowledge_base`、`user_file`、`enterprise_statement`、`database`、`other`。

- 网页或研究报告必填 `title`、`publisher`、`url`；可填 `published_at`。只登记、未访问的链接对外必须显示“未访问，原文未取得”，不得渲染为“检索日期”。
- 知识库或用户文件必填不含路径的 `file_name`。内部路径、页码、摘录哈希和版本放入 `internal`，不得用于对外渲染。
- 企业陈述必填 `title` 或 `file_name`。它证明“企业作出该陈述”，不自动证明第三方独立验证。
- 相同规范化 URL 不得重复登记；追踪参数和片段不构成新来源。

## 证据记录 `records`

必填字段：`id`、`subject`、`claim`、`type`、`source`、`retrieved_at`、`location`、`status`。

可选字段：`period`、`unit`、`value`、`formula`、`inputs`、`supports`、`limits`、`conflict_group`、`notes`、`evidence_excerpt`、`basis_type`。

- `type`：`fact`、`calculation`、`inference`、`pending`。
- `status`：`verified`、`unverified`、`conflicted`、`expired`。
- `source`：一个来源编号或来源编号数组。计算和推断可以为空数组，由 `inputs` 或 `supports` 递归取得来源。
- 已核验事实的 `evidence_excerpt` 保存最小充分原文片段；中文不依赖空格分词。
- 计算项的 `inputs` 引用已核验台账记录，并填写 `formula`；推断项的 `supports` 至少引用一条已核验事实或计算，并在 `limits` 中记录边界。
- 冲突记录使用相同 `conflict_group`，保留各自来源和值，不平均、不静默覆盖。

## 文档映射 `document`

`document.blocks` 中每项包含 `text`、`claim_ids`，可选 `heading`。一个正文块可以引用多条台账记录；来源编号由脚本沿计算和推断依赖递归汇总。

严格模式下正文块不得直接包含裸 URL。报告渲染使用 `[1]` 标记并把完整来源放在文末；对话模式使用内联链接或前置来源范围。

## 校验边界

脚本能够确认编号、字段、引用、计算血缘、来源显示和部分词面覆盖，不能自动证明整句主张与原文在法律或专业意义上完全等价。词面重合不足进入人工复核提示，而不是由算法替代专业判断。

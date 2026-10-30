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

`sources` 和 `records` 是核心；确定性渲染使用 `document`，份额任务使用 `market_share`。旧数组及 JSONL 支持基础校验，严格溯源使用完整信封。

## 来源登记 `sources`

通用字段：`id`、`kind`、`access_status`。来源编号建议使用 `S1`、`S2` 并在同一任务内保持稳定。

- `access_status = obtained`：已取得并实际读取原文，必填 `retrieved_at`。
- `access_status = reference_only`：原文待取得，已在另一材料看到名称或链接。填 `registered_at`、`registered_via` 及登记载体，记录保持待核；实际取得后补 `retrieved_at` 与核验状态。

`kind` 允许：`official_web`、`public_web`、`research_report`、`knowledge_base`、`user_file`、`enterprise_statement`、`database`、`other`。

- 网页或研究报告填 `title`、`publisher`、`url`，可补 `published_at`；仅登记的链接对外显示“未访问，原文未取得”。
- 知识库和用户文件对外显示 `file_name`；内部路径、页码、摘录哈希和版本保存在 `internal`。
- 企业陈述填 `title` 或 `file_name`，注明自述范围，独立核验另记状态。
- 相同规范化 URL 合并登记，统一处理追踪参数和片段。

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

严格模式下正文块使用来源映射。报告用 `[1]` 并在文末列完整来源；对话用内联链接或前置来源范围。

## 校验边界

脚本核对编号、字段、引用、计算血缘、来源显示和词面覆盖；主张与原文的专业含义由当前模型结合原文复核，词面覆盖不足列为复核提示。

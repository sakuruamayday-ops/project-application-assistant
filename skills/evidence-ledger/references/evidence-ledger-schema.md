# 证据台账结构

必填字段：`id`、`subject`、`claim`、`type`、`source`、`retrieved_at`、`location`、`status`。

可选字段：`period`、`unit`、`formula`、`inputs`、`supports`、`limits`、`conflict_group`、`notes`。

`type` 仅允许 `fact`、`calculation`、`inference`、`pending`；`status` 仅允许 `verified`、`unverified`、`conflicted`、`expired`。

计算项的 `inputs` 必须引用台账内证据编号。推断项的 `supports` 至少引用一条已核验事实，并在 `limits` 中记录判断边界。

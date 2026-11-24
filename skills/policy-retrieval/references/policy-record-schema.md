# 管理办法记录

每份记录标管理办法、实施细则或工作指引，登记标题、官方文号、发文机关、属地、官方原文链接、本地文件、条款或页码、施行日期、效力和替代关系。长期适用的附件按原名称关联。

用 `python3 scripts/validate_policy_chain.py 记录.json` 回读原文。顶层填 `project`、`region` 和 `documents.management`，评估年度 `year` 选填。管理办法记录填 `title`、`issuer`、`region`、`status`、`number`、`official_url` 和 `body`。正文和附件路径相对记录文件。附件逐项填 `title` 和 `path`，合计与 `attachments_expected` 对应。

正文原件有文号时在正文回读；正文单列且文号在发文原件中时，登记 `number_source` 指向发文原件。正文和附件可用 `key_clauses` 登记应在对应原件中读回的关键条款短句。附件仅印编号时，登记 `marker` 及对应关键条款；同时核对正文列示的名称和附件内容。

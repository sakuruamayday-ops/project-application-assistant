# 项目索引筛选

在项目匹配技能目录筛选管理办法中的项目。用结果的 `management_rule` 打开原文，按 `condition_sections` 和 `match_by` 核对企业条件。原文路径相对于索引文件所在目录。

```bash
python3 scripts/filter_project_map.py references/high-frequency-project-rules.jsonl --scope 全国 --keyword 绿色工厂
```

`canonical-project-index.jsonl` 和 `project-map.jsonl` 用于查项目名称。脚本按 `canonical_project_name` → `title` → `name` 选用第一个非空文本。三项均缺有效值时，命令报出索引文件和行号。

`--scope` 仅匹配 `primary_region`，可重复指定，命中任一值即保留。默认 `--scope-match exact` 要求全等，例如 `--scope 杭州市`。添加 `--scope-match contains --scope 杭州` 即可匹配包含「杭州」的主要地区。

筛选器在输出 JSONL 时生成 `project_id`。它由规范化后的项目名称、`primary_region`、`year` 依次组成，统一全半角、大小写和连续空白，字符串采用 `project:` 加 JSON 数组的格式。年度可填数字或带「年」「年度」的文本。索引缺 `year` 时用空字符串表示未注明年度。

把筛选输出的 `project_id` 原样用于可行性报告事实 JSON，并填入 `enterprise` 及报告事实。报告生成器按 ID 中的项目名称选择已有模板，成稿回执沿用同一个 `project_id`。

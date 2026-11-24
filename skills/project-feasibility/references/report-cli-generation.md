# 其他宿主的报告命令行生成

未提供 `project-feasibility.generate-report` 的宿主用本流程，客户端沿该签名操作生成。

高新、专精和小巨人的前期 HTML 入口使用固定母版。申请书走原生 Word 回填。

可行性缺陷报告与其他项目的原生命令行流程使用 Word 母版。先运行 `python3 scripts/select_report_template.py --project-type <项目> --report-type <preassessment|feasibility> --output-dir <工作临时目录> --enterprise <企业>`，再运行 `python3 scripts/fill_report_template.py --template <已复制母版> --output <成稿.docx> --fixture <私有事实.json> --report-type <preassessment|feasibility> --release-tag <版本> --public-root <公共源码根目录>`。

可行性报告也可运行 `python3 scripts/generate_report.py --input <事实.json> --report-type feasibility --output <成稿.docx>`，一次完成 Word 母版校验和回填。

三类项目的客户端 HTML 与原生 Word 可行性报告使用相同事实 JSON。`table_content` 可提供以下两张表，列名和顺序与母版一致：

- 条件表用 `要求`、`企业现状`、`证据来源`、`证据状态`、`差距`、`补强动作`、`优先级`。逐项填适用硬门槛，保留已满足和缺证据的状态。
- 缺陷表用 `优先级`、`缺陷项`、`要求`、`企业现状`、`差距`、`证据`、`补强动作`。按处理先后排序，差距写实际单位或具体缺件。缺陷表也可从 `items` 读取，字段见可行性输出契约。

`policies` 中有原件定位的政策全部写入政策表，母版未预设的类型列在「其他政策依据」。`conditions.match` 用实际条件名称，母版无对应项时新增条件行，显式填入的 0 照录。同一短词指向多项时在补充行保留原条件，避免贴到多个门槛。提供与母版同表头的完整 `table_content` 时，按该表的最终各行回填。

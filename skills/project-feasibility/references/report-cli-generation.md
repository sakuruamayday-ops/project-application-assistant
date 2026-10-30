# 其他宿主的报告命令行生成

未提供 `project-feasibility.generate-report` 的宿主用本流程，共创客户端沿该签名操作生成。

高新、专精和小巨人分析报告用固定 HTML 生成器与真实事实 JSON，再由可用宿主导出 PDF；申请书走原生 Word 回填。

其他项目保留原命令行流程：先运行 `python3 scripts/select_report_template.py --project-type <项目> --report-type <preassessment|feasibility> --output-dir <工作临时目录> --enterprise <企业>`，再运行 `python3 scripts/fill_report_template.py --template <已复制母版> --output <成稿.docx> --fixture <私有事实.json> --report-type <preassessment|feasibility> --release-tag <版本> --public-root <公共源码根目录>`。母版副本不是交付成品。

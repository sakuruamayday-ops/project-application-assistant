# 其他宿主的报告命令行生成

仅适用于未提供 `project-feasibility.generate-report` 签名操作的宿主。共创客户端不使用以下流程。

先运行 `python3 scripts/select_report_template.py --project-type <项目> --report-type <preassessment|feasibility> --output-dir <工作临时目录> --enterprise <企业>`，再运行 `python3 scripts/fill_report_template.py --template <已复制母版> --output <成稿.docx> --fixture <私有事实.json> --report-type <preassessment|feasibility> --release-tag <版本> --public-root <公共源码根目录>`。母版副本只是工作材料，未回填和检查完成前不能作为成品交付。

# 其他宿主的报告命令行生成

仅适用于未提供 `project-feasibility.generate-report` 签名操作的宿主。共创客户端不使用以下流程。

高新、专精及小巨人的分析与行动体检报告运行 `python3 scripts/generate_report.py --input <事实.json> --output <新报告.html> --report-type <preassessment|feasibility>`。程序直接使用固定HTML模板，不复制或读取Word报告母版；最终由宿主HTML渲染器交付PDF。申请书使用对应技能的Word回填入口，不附加PDF。

其他项目保留原命令行流程：先运行 `python3 scripts/select_report_template.py --project-type <项目> --report-type <preassessment|feasibility> --output-dir <工作临时目录> --enterprise <企业>`，再运行 `python3 scripts/fill_report_template.py --template <已复制母版> --output <成稿.docx> --fixture <私有事实.json> --report-type <preassessment|feasibility> --release-tag <版本> --public-root <公共源码根目录>`。母版副本不是交付成品。

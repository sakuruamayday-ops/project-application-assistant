# 标准销售版视觉资产

视觉来源文件为主人提供的 `浙江巨能电力建设有限公司_企业全景调研报告_标准销售版_20261008.pdf`，日期为2026年10月8日。原件仅保存在本机作视觉核对，不进入签名套件。本目录 `sales-master-reference.pdf` 由主代理在最终视觉验收后生成，内容为该样式的中性母版预览，不含来源客户的企业、人员、财务或经营事实。

`sales-master-template.html` 为固定 DOM 占位源；`sales-style.css` 保存 A4、原橙色封面、章节标题、表格、摘要、关注提示、竞争双卡及评级卡的版式参数。模板企业数据不得继承到实际报告。当前候选需要真实成品视觉验收，源码参数或生成器测试通过不能声称已完成 1:1 对照。

`sales-preview-cover.png`、`sales-preview-basic-info.png`、`sales-preview-assessment.png` 来自最终中性母版PDF第1、2、7页的实际渲染，供当前有图像能力的模型通过 `read_image` 读取，不含原客户事实。文本模型使用已人工核验的固定模板源，不把PDF传入图片工具，也不声称已目视PDF。

`icons/section-01.png` 至 `section-13.png` 和 `callout-warning.png`、`callout-success.png`、`callout-danger.png`、`callout-info.png`、`callout-negative.png` 来自原件图形像素，保留各自比例，不统一拉伸为方形，不使用模型另绘或系统 emoji 字体。

中文使用完整 Noto Sans CJK SC 2.004 Regular/Bold，许可证见 `fonts/OFL-NotoSansCJK.txt`；英文使用 DejaVu Sans 2.37 Regular/Bold，许可证见 `fonts/LICENSE-DejaVu.txt`。字体只按随包精确文件读取；生成器动态写入这些签名资产的 file URI，不内嵌几十 MB 字体，也不以系统字替换。字体和许可证均随候选保留。

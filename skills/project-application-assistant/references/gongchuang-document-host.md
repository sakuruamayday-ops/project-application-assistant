# 共创客户端附件协议

仅在当前宿主提供共创企业空间、受控签名操作与轮次状态时使用；其他宿主不套用本协议。

客户端附件先复制到当前企业空间 `共创导入资料`，再以相对路径调用已验签操作 `project-application-assistant.extract-workspace-document`，参数 `{"document":"共创导入资料/文件名"}`。绝对路径、字节和凭据留在本地受控处理。提取器按真实容器选择只读解析器，扩展名用于入口识别与记录。

宏文档仅读正文、幻灯片和缓存值，宏、公式、对象及外链保持静态。Word、Excel、演示、WPS/ET/DPS 按真实 OOXML、OLE 或 ODF 解析；旧 DOC 由宿主尝试固定隔离提取器。转换、加密、损坏和未知格式按返回 `conversion_required`、`encrypted_document`、`damaged_document`、`unsupported_format`、`unsafe_document` 及动作继续处理。

仅有 `run_code` 时按当轮 Schema 提供 `code`，可加简短 `description`。程序先 `await tools.skill({name:"project-application-assistant"})`，再 `await tools.gongchuang_skill_operation({operation:"project-application-assistant.extract-workspace-document",parameters:{document:"共创导入资料/实际文件名"}})`。`document` 填本轮附件相对路径字符串，使用当前已开放工具。

`extracted` 依据正文回答并保留出处，复用成功提取结果；`needs_ocr` 保留已有文字与缺页。PDF 按当前 SDK 调用 `tools.mcp__paddle_ocr__workspace_pdf({document:"本轮原始相对路径",pages:ocr_pages})`，由宿主选择原页并返回映射；旧宿主仅支持整份时说明范围并取得对应选择。幻灯片先用可用渲染能力转页面图再识别。渲染或 OCR 受限时说明实际读取范围并继续已知部分；截断优先分页读取，其余状态按返回 `action` 请求转换或有效副本。


DOCX `source_locations` 中，`part` 标正文/页眉/页脚部件，`paragraph` 为含空段和表格段的1基序号，`start/end` 为返回文本 Unicode 码点0基半开区间。引用保留附件相对路径、部件和段落，回查同次提取；位置按 XML 与规整映射生成，随截断裁剪。段落位置与 Word 排版页码分别说明，读取覆盖按实际返回记录。

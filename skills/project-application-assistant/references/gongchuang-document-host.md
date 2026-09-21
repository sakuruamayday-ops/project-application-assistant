# 共创客户端附件协议

仅在当前宿主提供共创企业空间、受控签名操作与轮次状态时使用；其他宿主不套用本协议。

用户从客户端输入框添加 Word、Excel、演示文稿、WPS 兼容文件、ODF、RTF、CSV／TSV、PDF 或 TXT 后，资料必须先复制到当前具体企业空间的 `共创导入资料` 目录，再读取副本；不得把源文件绝对路径、文件字节或账户凭据送入对话。激活本技能后，优先调用已验签操作 `project-application-assistant.extract-workspace-document`，参数为 `{"document":"共创导入资料/文件名"}`，只使用当前企业空间内的相对路径，无需查找安装目录、运行清单或解释器。提取器先按文件真实内容识别 OOXML、OLE、ODF、RTF、PDF 或文本结构，再选择只读解析器；扩展名只用于记录和受控入口白名单，不得据此猜测内容。

DOCM、XLSM、PPTM 等宏文档只读取正文、幻灯片或已缓存单元格值，不执行宏、公式、对象或外链。现代 Word、Excel、演示文稿及其模板格式使用对应只读解析器。扩展名为 WPS、ET 或 DPS 但真实内容属于受支持的 OOXML、XLS 或 ODF 时按真实格式读取；旧式 DOC 由客户端在同一次操作中尝试固定的隔离提取器，宿主不支持或提取失败时明确返回需转换状态。专有 WPS／ET／DPS、旧 PPT、加密、损坏或未知容器返回 `conversion_required`、`encrypted_document`、`damaged_document`、`unsupported_format` 或 `unsafe_document` 等结构化状态，同一文件不得换解析器循环试错。

仅开放 `run_code` 的客户端，按当轮 Schema 提供 `code`；`description` 是可选的简短执行说明。在程序内先 `await tools.skill({name:"project-application-assistant"})`，成功后再 `await tools.gongchuang_skill_operation({operation:"project-application-assistant.extract-workspace-document",parameters:{document:"共创导入资料/实际文件名"}})`。文件名使用本轮附件路径；`document` 是字符串，不是 `{type, path, extensions}` 参数定义对象。不要把 `skill`、`write` 当成未开放的根工具，不探测安装目录或重复安装解析器。

解析结果为 `extracted` 时，依据返回正文回答并保留文件名、页码或工作表等出处；同一文件成功提取后不要再调用提取器。解析结果为 `needs_ocr` 时，保留已提取文字，不能把少量标题当成完整正文。PDF 直接调用 `tools.mcp__paddle_ocr__workspace_pdf({document:"本轮原始相对路径",pages:ocr_pages})`，宿主在内存中选择所需原页后提交至已配置的 PaddleOCR，返回原页码映射；不要手写拆页脚本、创建临时 PDF 或重复提取同一文件。参数始终以当轮工具 SDK 为准，旧宿主未公开 `pages` 时一次性说明只支持整份 OCR，由用户决定是否整份识别，不猜测参数。幻灯片须先用可用的受控渲染能力转成页面图像再识别。渲染或 OCR 不可用、失败时一次性说明缺失页与下一步，不能声称已读完或猜测图片内容。输出截断时按共享任务边界优先使用接口支持的分段读取；确实不支持时才请求分段副本；其他结构化状态按返回的 `action` 一次性请求转换、无密码副本或有效副本，不得把导入成功写成读取成功。


DOCX 正文提取同时返回 `source_locations`：`part` 区分正文、页眉和页脚的 XML 部件，`paragraph` 是该部件中从 1 开始的段落序号，包含空段落和表格内段落；`start`、`end` 是返回 `text` 中按 Unicode 码点计数、从 0 开始的半开区间。引用或改写时保留原附件相对路径、部件和段落号，回查同一次提取结果，不把抽取文本另命名成原文件。定位按 XML 实际字符位置生成，并随空白规整映射到返回正文，不通过相同文字猜测段落。仅返回能够完整映射到当前正文的段落；输出截断时同步裁剪位置表，不能用缺失位置推断原件已完整读取。该位置表不宣称 Word 排版页码，也不建立未执行的旧格式转换链。

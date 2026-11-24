# 客户端附件协议

## 宿主注册与签名

宿主必须提供当前企业工作区、轮次上下文、附件导入和已开放的签名操作工具。技能提供只读提取脚本 `scripts/extract_workspace_document.py`。操作注册表、验签、受控解释器与 OCR 接口由宿主提供。

宿主从绑定的技能包根目录读取 `client-runtime-operations.json`，注册表版本为 `gongchuang-signed-skill-operations/v1`。宿主按 `operations[].id` 找到 `project-application-assistant.extract-workspace-document`，根据验签后的索引校验注册表和相关技能文件，核对受控 Python 解释器的摘要，再按登记的脚本和参数执行。该注册项声明 `sandbox_mode: read-only` 和 `network: none`。

## 附件目录与调用

宿主将本轮附件复制到当前企业工作区内的 `共创导入资料`。`parameters.document` 是唯一必填参数，类型为 `workspace-input-file`。传入相对路径字符串 `共创导入资料/实际文件名`，扩展名按注册表的 `parameters.document.extensions` 校验。绝对路径、字节和凭据留在本地受控处理。

当前轮次开放 `gongchuang_skill_operation` 时传入以下参数。

```json
{
  "operation": "project-application-assistant.extract-workspace-document",
  "parameters": { "document": "共创导入资料/实际文件名" }
}
```

仅开放 `run_code` 时，按当轮工具 Schema 提供 `code` 和 `description`。当 `description` 是可选参数时可以省略。程序调用当轮开放的工具并输出结果。

```js
await tools.skill({ name: "project-application-assistant" })
const result = await tools.gongchuang_skill_operation({
  operation: "project-application-assistant.extract-workspace-document",
  parameters: { document: "共创导入资料/实际文件名" },
})
console.log(result)
```

## 返回结果与错误

读取宿主返回的 `status`、`exitCode` 和 `stdout`。本操作的 `stdout_json_schema_version` 为 `gongchuang-document-extraction/v1`。`stdout` 须是一个 JSON 对象，`schema_version` 与注册项一致。`exitCode: 0` 对应宿主 `passed`，正文可用性按 JSON 内的 `status` 判断。`exitCode: 2` 对应宿主 `rejected`，例如提取器收到非普通文件时。

注册表缺项、验签或摘要不符、参数或路径无效时，宿主抛出 `Error`。标准输出为空或无法解析为单个 JSON 时，宿主错误包含 `GC-SKILL-OUTPUT-PROTOCOL`。`schema_version` 不匹配时，宿主也抛出 `Error`。`run_code` 中的 SDK 调用失败时会收到 `ToolCallError`，可读取 `toolName` 和 `message`。

| 提取结果 `status` | 下一步 |
|---|---|
| `extracted` | 依据正文回答并保留出处，复用已提取结果。 |
| `needs_ocr` | 保留已提取文字和缺页，按页补读。 |
| `conversion_required` | 使用另存为支持格式的副本。 |
| `encrypted_document` | 使用无密码副本。 |
| `damaged_document` | 使用有效副本。 |
| `unsupported_format` | 使用受支持格式。 |
| `unsafe_document` | 按 `action` 拆分或另存副本。 |
| `unavailable` | 检查文件的读取权限。 |
| `component_unavailable` | 按 `action` 处理客户端组件。 |

提取器按真实容器选择只读解析器，扩展名用于入口识别与记录。宏文档仅读正文、幻灯片和缓存值，宏、公式、对象及外链保持静态。Word、Excel、演示、WPS/ET/DPS 按真实 OOXML、OLE 或 ODF 解析。旧 DOC 由宿主尝试固定隔离提取器。

## 补读与引用

按当轮授权和宿主开放的工具处理 OCR。PDF 按当前 SDK 调用 `tools.mcp__paddle_ocr__workspace_pdf({document:"本轮原始相对路径",pages:ocr_pages})`，由宿主选择原页并返回映射。旧宿主仅支持整份时说明范围并取得对应选择。幻灯片先用可用渲染能力转页面图再识别。渲染或 OCR 受限时说明实际读取范围并继续已知部分。截断优先分页读取，其余状态按返回 `action` 处理。

DOCX `source_locations` 中，`part` 标正文、页眉或页脚部件，`paragraph` 为含空段和表格段的 1 基序号，`start/end` 为返回文本 Unicode 码点 0 基半开区间。引用保留附件相对路径、部件和段落，回查同次提取。位置按 XML 与规整映射生成，随截断裁剪。段落位置与 Word 排版页码分别说明，读取覆盖按实际返回记录。

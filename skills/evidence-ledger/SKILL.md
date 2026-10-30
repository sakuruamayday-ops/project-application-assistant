---
name: evidence-ledger
description: 建立事实、计算、推断和待核验四类证据台账与统一来源登记，追溯主张、计算输入和市场占有率测算，按回答、报告、表格、演示、申报表及标准配置来源。
---

# 证据链台账

统一来源登记、稳定编号、主张映射、计算血缘、披露与校验。业务技能负责检索、来源等级、冲突裁决和专业判断；结构检查与专业支持程度分别记录。

## 记录方法

- `fact`：来源直接陈述；`calculation`：公式、输入与结果；`inference`：支撑事实、推理及适用条件；`pending`：待取材料或冲突事项。
- 为企业、政策、知识产权和项目建立主体标识，记录证据编号、主张、类型、来源、取得日期、原文位置、适用期间和核验状态。
- 计算引用输入证据，推断引用事实、反证及限制；冲突分组保留各来源原值。确定结论对应已核事实或可复算计算，缺少依据的部分写明状态并继续形成可用稿。
- 市场占有率参考 `references/market-share-grounding-contract.md`，登记企业分子、上位市场、逐层拆分系数、六同状态、申报值和复算值。企业自述、第三方证明分别标识；缺来源或六同冲突时记 D，受限复现值连同公式及局限披露，排名结论保持待核验。

## 来源呈现

配置读取共享 `report-skill-registry.json`，源配置为 `config/grounded-citations.json`，由生成器同步：

- 对话采用贴近结论的链接，必要时说明来源范围。
- 分析报告正文轻量编号，完整来源在文末；Excel 在最后“数据来源”工作表，PPT 在最后“数据来源”页。
- 标准保留“规范性引用文件”原位，起草依据另交《标准数据来源说明》；原生申请书采用现有来源字段或独立说明，沿用原章节。
- 实际访问的网页列标题、机构、发布日期、链接、检索日期。登记载体中的未取原文链接标 `access_status = reference_only`，说明“原文未取得”并指向登记载体；知识库来源对外显示文件名，内部保存路径、页码、摘录及哈希。
- 发布机关、取得渠道分列。第三方转载注明转载渠道与地址；“官方直接取得”对应实际取得的官方页面。案例标 `case_reference`、`case_pack_id` 和文档编号，用于参考结构或证据类型。

字段与规则见 `references/evidence-ledger-schema.md`、`references/grounded-output-policy.md`。

## 校验接口

```bash
python3 scripts/validate_evidence_ledger.py <台账.json> --strict-grounded
python3 scripts/grounded_evidence.py market-share <市场占有率台账.json>
python3 scripts/grounded_evidence.py xlsx-dump <输入.xlsx> --output <内容.json>
python3 scripts/grounded_evidence.py render-profile <台账.json> --profile analysis-report --artifact pdf
python3 scripts/grounded_evidence.py render-profile <台账.json> --profile standard-native --artifact docx
python3 scripts/grounded_evidence.py validate-delivery <台账.json> <交付文件.docx> --profile analysis-report --state-root <本轮状态目录>
python3 scripts/grounded_evidence.py validate-delivery <标准台账.json> <标准正文.docx> --profile standard-native --source-memo <标准数据来源说明.docx> --state-root <本轮状态目录>
```

`--receipt-export-dir <交付目录/validator-receipts>` 可复制可见收据，正式回执仍由运行层消费。数组或 JSONL 台账兼容基础校验，新台账及市场占有率使用 `grounded-evidence/v1`。

## 文件生成与复用

- 分析与体检默认 PDF，申报书、表单、标准和可编辑数据沿主技能格式。共创客户端以同一静态 HTML 调用 `gongchuang_deliver_pdf`，复核真实成品，已有文件及有效证据按任务复用，失败时修复对应步骤。
- DOCX 优先采用主技能专用模板或生成器；通用正文可调用 `evidence-ledger.create-docx-from-file`，参数 `{"input":"正文文件路径","output":"新的.docx路径"}`，短正文可用 `evidence-ledger.create-docx`。
- 完整正文保持同一 UTF-8 `.md`、`.txt` 或 `.html` 文件，按路径读取并完整写入 Word。HTML 文字与原生表格按正文顺序复制，修订使用新输出路径并保留旧文件，后续检查绑定成功返回的文件路径。
- 来源说明与各份报告分别保留正文、台账和交付结果；需要 Word 来源表时单独生成、检查。修订理由、执行步骤和校验过程留在对话，文档修订历史按用户要求或文件规定处理。
- 文件生成与事实核验分别记录。首次 artifact 核验按接口需要传入 `evidence`、`calculations` 及实际取得片段；已有同任务、同来源的有效证据可复用。跨轮采用宿主确认有效的检查点，待复核原件按已知精确路径读取，缺项保留在稿件中。
- 计算输入对应证据 `values` 真实片段或已复算中间值。合计用 `sum`，比例用两个输入的 `ratio` 并输出百分数。例如先记 `{"id":"c1","operator":"sum","inputs":[105,126,140],"result":371,"evidenceIds":["E1"]}`，E1 包含三个原始值，再用 371 计算比例。派生计算继续引用原始证据 ID。政策文号、年份取原文，建议年度明确标注建议。

## DOCX 与品牌

生成器依赖 `python-docx`、`markdown-it-py`。加粗、斜体和表格使用原生格式，代码字面量原样，链接保留目标。`6.4.1` 等条款编号使用正文样式，数字标题用显式 Markdown 标记；跨页重复表头，普通行尽量整行换页。

A4、固定列宽和嵌入中文字体用于稳定布局，仍结合真实渲染检查长网址、跨页、长行和字体。`gongchuang-document-header`、`gongchuang-cover-signature`、税务 `footer.page-footer` 分别进入真实页眉、首页页脚和常规页脚，其余 header/footer 沿正文保留；`header.page-header` 转为跟随下一段的标题。正文比对排除已明确搬移的节点，署名单独读回。

共创客户端 DOCX、XLSX、XLSM 可用 `evidence-ledger.apply-office-branding`，参数 `{"artifact":"最终文件路径"}`。税务 Word 使用 `evidence-ledger.apply-office-branding-gold`，沿用 `manufacturing-tax-risk-report` 画像。PPTX 采用对应生成技能品牌流程。品牌应用后提供文件入口，正文变更后同步品牌；文件校验按任务需要执行。

## 按需检查与宿主职责

内容与文件生成后直接交付，深度检查按用户任务执行，结果注明实际覆盖范围。按实际格式可检查：PDF 逐页渲染、空白页和缺字；Excel 用原生引擎逐表渲染并检查公式；PPT 逐页检查；Word 使用当前可用渲染器。渲染条件待满足时标记 `pending-device-acceptance`，区分文本、结构与视觉检查结果。

宿主提供本轮状态目录时，`validate-delivery` 将台账哈希、文件哈希、结构结果和真实 `turn_id` 绑定为 `grounded-delivery/v1` 回执；状态目录采用宿主实际提供的位置及 `current-turn.json`。其他宿主记录原生验收结果，回执类型按实际能力填写。最终说明采用实际生成成品的工具与尚待完成部分。

云渲染、在线转换、上传及凭据使用由用户指令和宿主权限处理，安全凭据通过专用接口传递，交付物使用脱敏信息。自动化未定位到渲染器时准确描述当前通道状态，继续完成可用稿。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

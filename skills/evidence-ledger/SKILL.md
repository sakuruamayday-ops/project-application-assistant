---
name: evidence-ledger
description: 建立事实、计算、推断和待核验四类证据台账及统一来源登记，校验主张到来源、计算输入和市场占有率测算链，并按对话、分析报告、表格、演示文稿、申报表单或标准文件配置输出可追溯来源。
---

# 证据链台账


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

宿主若只暴露 `run_code`，`skill`、`read`、`web_search`、校验器等工具均须在其中以 `await tools.<name>(...)` 调用，不得根级调用隐藏工具。先按 `SKILL.md` 或参考文档执行命令。脚本名或命令表示执行入口，不是预读源码许可；首次执行前不得读取 `scripts/**`、`examples/**`、`tests/**`、`*.example.*`、`package.json`，也不得列出技能目录。只有文档命令已经真实失败，且错误仍不足以确定调用契约时，才可定向读取与该失败直接相关的一个源码文件。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 职责

为项目匹配、可行性分析、市场占有率、写作和检查提供统一证据底稿。算法层只统一来源登记、稳定编号、主张映射、计算血缘、最小披露和校验；业务技能继续负责检索策略、来源等级、冲突裁决和专业判断。不得把证据台账当成结论生成器，也不得因结构校验通过就声称来源在专业意义上必然支持结论。

## 证据类型

- `fact`：来源直接陈述的事实。
- `calculation`：基于已列事实形成的计算结果，必须记录公式和输入项。
- `inference`：基于事实形成的专业判断，必须说明推理边界。
- `pending`：缺少可靠材料或存在冲突，尚不能确认。

## 强制流程

1. 为企业、政策、知识产权和项目建立稳定主体标识。
2. 每条记录填写证据编号、主张、类型、来源、获取日期、原文位置、适用期间和核验状态。
3. 计算记录必须引用输入证据编号；推断记录必须引用支撑事实并列出反证或限制。
4. 同一字段来源冲突时建立冲突组，不覆盖、不平均、不静默选择。
5. 正式结论只能引用状态为已核验的事实或可复算计算；待核验项不得写成确定事实。
6. 交付时同时输出证据台账和未闭合证据缺口。
7. 市场占有率额外读取 `references/market-share-grounding-contract.md`，登记企业分子、上位市场、每一级拆分系数、六同状态、申报值与复算值；企业陈述可以作为明确标识的来源，但不得伪装成第三方证明。

## 文档配置

运行时读取套件共享的 `report-skill-registry.json` 选择配置，不得把一种页面结构强加给所有文档。源码中的 `config/grounded-citations.json` 是唯一正式配置源，由生成器写入注册表；安装包不依赖仓库根目录配置文件，也不得手工维护第二份配置：

- 直接回答：网页来源跟随结论内联；市场占有率、政策门槛等高风险回答可先给“数据来源范围”。
- 分析报告 Word、PDF、Markdown：正文保留轻量编号，完整来源放在文末。
- Excel：事实单元格保留轻量编号，完整来源放在最后的“数据来源”工作表。
- PowerPoint：关键结论保留轻量编号，完整来源放在最后的“数据来源”页。
- 标准：标准正文不得新增“数据来源”或“参考资料”章节，不在正文插入证据编号；保留标准自身的“规范性引用文件”，并另生成《标准数据来源说明》。
- 原生申请书或法定结构：优先使用表单允许的来源字段；结构不允许时生成独立来源说明，不移动法定章节。

已实际访问的网页来源对外列标题、机构、发布日期、链接和检索日期。只在工作簿或其他材料中登记、但未取得的链接与文件必须标记 `access_status = reference_only` 并指向登记载体；对外写“未访问，原文未取得”或“原件未取得”，不得写成“用户文件”或“检索日期”。已取得的知识库来源对外只显示文件名；内部路径、页码、摘录和哈希仍保存在台账。

## 输出与校验

台账字段、来源等级和冲突规则见 `references/evidence-ledger-schema.md`，输出边界见 `references/grounded-output-policy.md`。

```bash
python3 scripts/validate_evidence_ledger.py <台账.json> --strict-grounded
python3 scripts/grounded_evidence.py market-share <市场占有率台账.json>
python3 scripts/grounded_evidence.py xlsx-dump <输入.xlsx> --output <只读内容.json>
python3 scripts/grounded_evidence.py render-profile <台账.json> --profile analysis-report --artifact pdf
python3 scripts/grounded_evidence.py render-profile <台账.json> --profile standard-native --artifact docx
python3 scripts/grounded_evidence.py validate-delivery <台账.json> <交付文件.docx> --profile analysis-report --state-root <当前轮次行为状态目录>
python3 scripts/grounded_evidence.py validate-delivery <台账.json> <交付文件.docx> --profile analysis-report --state-root <当前轮次行为状态目录> --receipt-export-dir <交付目录/validator-receipts>
python3 scripts/grounded_evidence.py validate-delivery <标准台账.json> <标准正文.docx> --profile standard-native --source-memo <标准数据来源说明.docx> --state-root <当前轮次行为状态目录>
```

共创客户端生成正式 DOCX 时，主技能声明的专用模板或生成器始终优先。主技能
没有专用模板或生成器时，chat 专业预校验通过后，调用已验签操作
`evidence-ledger.create-docx`，把已通过预校验的完整正文作为 `content`，并把工作区
内一个尚不存在的 `.docx` 路径作为 `output`。不得改用临时 Node/Python 生成脚本、
pandoc 或 OOXML 解压回读来绕开该操作，也不得用该通用操作替代主技能的专用模板。

共创客户端生成正式 DOCX、XLSX 或 XLSM 时，正文与版式完成后、首次
artifact 校验前，调用已验签操作 `evidence-ledger.apply-office-branding`，
参数为 `{"artifact":"工作区内最终文件路径"}`。该操作在原文件上写入签名
技能包的统一页眉与居中水印；执行后不得再修改文件。PPTX 继续使用对应生成
技能声明的签名品牌流程，不把本 Office 操作错误套用于演示文稿。

旧版数组或 JSONL 台账继续支持基础校验；新交付和市场占有率使用 `grounded-evidence/v1` 严格模式。校验失败不得进入正式写作。

生成 Word、PDF、Excel 或 PowerPoint 后，按 `config/grounded-citations.json` 的 `artifact_validation` 分格式验收。PDF 必须逐页渲染并检查空白页和缺字；Excel 使用表格原生引擎逐表渲染；PowerPoint 逐页渲染；Word 在当前宿主存在可用渲染器时逐页渲染。缺少 Word 或中文字体时记录状态 pending-device-acceptance，禁止把文本提取成功写成视觉通过，也禁止用 PDF、Excel 或 PPT 的成功代替 Word 验收。

正式文件交付前必须运行 grounded_evidence.py 的 validate-delivery 子命令，使台账哈希、交付文件哈希、结构检查和当前 `turn_id` 形成 `grounded-delivery/v1` 回执；没有非空回执时不得宣称交付门禁通过。`--state-root`必须来自当前宿主或项目运行层实际维护的本轮状态目录，其中已有带`turn_id`的`current-turn.json`；不得猜测任何特定宿主路径。需要给用户保留一份可见收据时使用`--receipt-export-dir`，该参数只复制回执，不改变运行层消费的正式回执位置。报告生成器、读取器或渲染器发生降级时，最终答复必须写实际产生最终文件的工具，不得把早先尝试过但未生成终稿的通道写成最终来源。读取普通 XLSX 优先使用同一脚本的 xlsx-dump 子命令，不得为了只读用户文件临时联网安装 openpyxl 等依赖。

未经用户明确授权，不得把用户输入、台账或交付文件上传到 COS、云渲染、在线转换或其他外部服务。宿主找不到 WPS、Word 或 LibreOffice 自动化入口时，只能写“当前自动化通道未定位到可用渲染器”，不得据此断言用户设备未安装对应软件。

历史案例证据单独标记为 `case_reference`，记录 `case_pack_id` 和文档编号；它只能证明参考结构或证据类型，不能证明当前企业事实，也不能提升政策来源等级。

## 反例与拒绝

- 正常：网页和知识库文件共同支撑分析结论，报告正文用编号，文末只显示网页完整信息和知识库文件名。
- 边界：标准中的“规范性引用文件”保持原位，另生成来源说明，不得改写为报告式文末来源。
- 拒绝：市场占有率分子、分母或拆分系数无来源，或六同边界冲突时判 D；精确值只能作为明确标注的“受限复现值”随公式披露，并同时写明不得对外使用和不作排名结论，不能标成已核验值。

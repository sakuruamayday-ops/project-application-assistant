---
name: high-tech-enterprise-application-drafting
description: 按高企申请书模板撰写、回填和核稿，按用户要求扩缩 RD、PS 表；材料体检按专用报告结构逐项呈现，单栏目与名称候选按指定范围完成。
---

# 高新技术企业申请书撰写

## 任务与资料

申请书使用原 Word 母版回填可编辑 DOCX；材料体检采用 [材料体检报告模板](references/material-checkup-report-template.md) 的章节、表头和问题卡，默认 PDF，呈现具体问题与依据。申报前资格、评分及年度比较按需使用 `high-tech-enterprise-preassessment`。单栏目、PS 名称候选和完整申请书分别按用户目标处理。

资料优先使用本轮申请书、RD、PS、知识产权、成果转化、人员、财务和制度原件；政策与模板按当期版本核验；登记字段参考[企业数据源说明](../_runtime/enterprise-source-fallback.md)；专利公开信息用于技术与权利核验，同类产品用于方向及指标建议。

业务事实、公开核验、拟定技术目标和待补字段分列。人员、预算、支出、收入、验收和知识产权等取自实际资料，缺项使用空值或“待企业核定”。研发支出与预算、净利润与利润总额、营业收入与企业总收入分别取值；年度转化数量、项目映射、部门与岗位职责按输入粒度填写。实测指标记 `indicator_kind: measured`、`indicator_source`；拟定建议保持对应标签，用户要求依据现有指标时用 `null` 记录缺口。

## PS 名称候选

名称可按已有产品、专利和技术卡形成候选，高新收入取专项审计资料，缺项留空。结构化输出采用用户字段和一份缺项清单。

专利 ID 取 `patents[].id`，技术卡 ID 单列，关联采用输入中明确关系。同产品大类的资料分别呈现；组合方案及六问使用“若确认……可……”的条件表达。生产支撑设备列未覆盖或支撑用途，具有对外产品或服务依据的对象进入 `candidates` 并计数。

方向确认取本轮用户或已确认上游记录，新候选保持待确认并提出具体问题，`directionConfirmed` 随真实确认记录填写。

## 模板与回填接口

从 [高新技术企业认定申请书空白模板.docx](assets/高新技术企业认定申请书空白模板.docx) 或用户模板复制到任务目录的新路径。原样填充替换既有 `w:t`，保留字体、字号、颜色、红字、抬头、页眉页脚、网格、列宽、行高、合并、边框、节及页边距；过长正文优先精简。用 `skills/_runtime/template-fidelity/scripts/validate_docx_text_only.py` 和实际逐页渲染核对版式。

用户要求增减 RD、PS 时，`scripts/expand_rd_ps_tables.py` 深拷贝完整编号段与 OOXML 表格，保留版式，清空新增数据区，连续编为 `RD01`、`PS01`。知识产权与转化表复制同类完整表格，IP 按用户汇总顺序。扩缩表和原样文字填充分别记录。

```bash
python3 scripts/expand_rd_ps_tables.py 输入申请书.docx 输出申请书.docx --rd-count 18 --ps-count 3 --report 扩表审计.json
python3 scripts/expand_rd_ps_tables.py 输入申请书.docx 输出申请书.docx --rd-count 13 --ps-count 2 --trim-empty-tail --report 缩表审计.json
```

缩表按用户要求使用 `--trim-empty-tail`，脚本整体核对末尾完全空白表，已填名称、周期、正文、经费、收入、IP 或勾选等数据的表保留并报告。成功后连续编号，审计记录位置、原编号和原因；省略 `--report` 时输出同名 `.docx.audit.json`。新路径保留旧文件，指定替换时使用 `--overwrite`。

RD 批量回填用 `scripts/fill_rd_core_innovation.py`，格式见 [rd-core-innovation-format.md](references/rd-core-innovation-format.md)。`basic_fields` 一次写名称、起止、领域、来源、IP、预算、目的和实施方式；按物理 OOXML 单元格与语义标签定位，省略字段沿用原值，输出重新打开逐 RD 核对。

完整申请书按复制母版、所需扩缩、RD 正文、整表字段组织。客户端操作 `high-tech-enterprise-application-drafting.fill-application-fields` 使用 `input`、`spec`、`output`，格式见 [整表字段回填](references/application-fields-format.md)。具名 JSON 填登记、主要情况、RD 支出、PS 和创新能力，程序合计年度支出，缺值保留未知，三年费用结构分别生成。

## 资料读取与能力校准

`scripts/plan_hightech_inputs.py` 盘点本轮文件，复用 `project-application-assistant/scripts/document_format_detection.py`，按真实 OOXML、OLE、ODF、RTF、PDF 和文本容器使用可用提取器。旧 DOC 可尝试兼容提取；返回 `conversion_required` 时汇总需另存为 DOCX、ODT、RTF 的文件，其他文件继续读取。加密、损坏、专有及未知容器保留原件并列待转换项。

提取登记主体、RD 周期目的路线人员预算进度验收、IP 类型权属日期与映射、PS 收入场景指标及测试销售、转化、组织和场地设备资料。申请正文按表单重新组织，立项报告提供事实及技术背景。

规模、主营、生产方式、人员、设备及公开知识产权用于校准技术复杂度，记录主体、来源和检索日期。传统制造场景可围绕材料、结构、工装、工艺、参数、检测、联动和过程控制写作；AI、数字孪生等术语对应企业资料、人才、产品、专利或测试的具体依据。检索未命中说明本轮范围。

## 章节写法

1. **企业简介**：基本情况、主营及应用、研发体系、三年活动、IP 与转化、发展方向；登记与经营范围按实际核验结果，缺项留空。
2. **技术领域**：匹配当期目录的一级、二级、三级及最末级，与产品、RD 和 IP 对应。待核时填“待企业确认四级领域”，附近似候选及技术差异。
3. **RD**：按立项目的、实施方式、领域、核心技术、创新点、四项阶段性成果展开，参考 [section-writing-templates.md](references/section-writing-templates.md) 和 [writing-rules.md](references/writing-rules.md)。核心技术两条用“XXXX技术：”开头，写机理、路径、参数和适用条件；创新点写变化、性能因果和验证方式。
4. **RD 栏格式**：“所属领域—核心技术标题—两条技术—创新点标题—两条创新点”七行，领域与表头一致；技术与创新点合计 400 字以内，领域另计，阶段成果四条合计 400 字以内。实测值带来源、拟定值带标签，草稿缺指标时保留缺口。
5. **PS**：按 RD 共同技术载体划分，填写名称、四级领域、技术来源、收入、主要产品判断、IP、技术指标、竞争优势和权利支撑。建议指标标“拟定指标”或“待企业实测校准”，正式值引规格书、检测、合同或测试。
6. **创新能力**：依次为“知识产权对企业竞争力的作用、科技成果转化情况、研究开发与技术创新组织管理情况、管理与科技人员情况”，每栏 400 字以内，写企业逻辑、已核事实、对应作用及依据状态。制度名称取该企业原件，人员矛盾字段分别核对；申请、受理、审中与授权分列。证据格式见 [enterprise-innovation-capability-format.md](references/enterprise-innovation-capability-format.md)。

## 汇总表

按 [summary-table-contract.md](references/summary-table-contract.md) 保持原列，一项一行：IP 写编号、名称、类别、授权登记日期及号、取得方式；PS 写产品、短技术名、四级领域、RD/IP 编号、已核或拟定指标和材料名；转化写成果、来源、方式、产品、时间、技术、成效、RD/IP 和材料。收入、数量与映射待核时留空，转化表连续自然跨页；详细机理写入对应正文栏。

## 检查与交付

内容与文件生成后提供入口；核稿或用户要求深入检查时使用以下方法。字体沿用原模板；技能母版正文为宋体 12 磅。检查对象包括数字来源、领域、编号、四栏顺序、篇幅、法律状态、制度与人员、汇总字段、页眉页脚和品牌。

可用接口：`scripts/audit_application_docx.py --innovation-evidence <证据JSON>`；`scripts/hightech_delivery_gate.py template-copy`、`summary-lint`、`record-wps-review`、`finalize`。真实运行结果、候选 SHA-256 和实际视觉检查绑定同一文件。WPS 可用时逐页记录页码、结论及截图哈希；其他宿主采用实际文档渲染能力并说明验收状态，修改后重新检查受影响页。主申请书、待补清单和各类回执分别对应自身文件，当前可用草稿直接交付并列待完成项。

当前业务模板基线 V1.3.1，套件标签取发布清单。详情见 [v1.3.1-release-plan.md](references/v1.3.1-release-plan.md)。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

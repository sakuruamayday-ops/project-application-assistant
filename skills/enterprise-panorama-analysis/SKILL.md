---
name: enterprise-panorama-analysis
description: 企业合作前公开信息全景调研与 A、B、C 报告交付，覆盖工商股权、关联企业、战略经营、风控、知识产权、同行、项目政策及五年规划。默认 A 标准销售版，深度报告使用 B，双版本使用 C；每种模式默认 PDF，可按请求追加 Word。
---

# 企业全景调研

全景、合作前尽调和全景报告按本技能组织；单字段查询按具体问题使用专业能力。同行比较是全景章节，后续提供新企业时沿用本轮已选模式并重新核验主体。续问与辅助能力参考[共享任务说明](../_runtime/task-execution.md)。

## 模式与事实复用

| 模式 | 用途 | 规范 |
|---|---|---|
| A 第一版｜标准销售版 | 客户沟通，简洁直接 | [version-a-sales.md](references/version-a-sales.md) |
| B 第二版｜GCIP深度顾问版 | 深度研判与顾问服务 | [version-b-advisory.md](references/version-b-advisory.md) |
| C 全生成 | 共用事实底稿，分别生成 A、B | 同上 |

按用户选择继续，未指定时用 A。共用同一调研时点、事实和来源，资料缺口标入当前可用稿。A 版署名 `报告机构：共创知识产权`，采用免主水印、免角标水印画像；B 版采用完整品牌水印。成品生成后直接交付对应 PDF，深度检查按用户需要执行，Word 按请求从同一正文追加，HTML 作为生成源保留在任务目录。

## 共同事实底稿

1. 用企业全称或统一社会信用代码锚定主体。按 [enterprise-info-verification.md](references/enterprise-info-verification.md)、[企业数据源有限降级协议](../_runtime/enterprise-source-fallback.md)和 [public-source-map.md](references/public-source-map.md)，用当前可用工具核验工商股权、司法信用、经营合规、知识产权、战略布局、经营销售、同行竞争、项目政策八个维度。
2. 天眼查开展主体和全维度分诊，企查查补齐未覆盖、缺失、状态不明及高影响字段，冲突和权威终值回到官方来源。关键事实交叉验证，精确数字、日期、编号与名称绑定来源。
3. 区分公开事实、计算、判断、待核事项及动作。核心工商、执行失信、处罚异常和知识产权标记已验证、单源待核、冲突待裁决或当前未命中；缺少来源时使用其他可用来源继续。
4. 财务及内部经营数据取自用户提供的可靠资料；营收、利润、未分配利润、研发费、客户占比、毛利、负债、产能和市场份额按实际资料列示，缺项列所需资料。平台分数和自动风险等级作为平台信息，专业判断另列依据。
5. 业务状态与证据状态分开。称号、评价、核验记录待补时保留未知；内部研发部门与政府认定机构分别记录。各项目使用对应年度、收入分母和政策；预测与实际值分列，资格依赖引用明确条款。
6. 同行名单证明所列身份，产品可比性和其他荣誉单独核验；企业存续与产品从业年限分别计算。知识库摘要、检索摘要和政策全文分层记录，来源状态在摘要、表格、规划和结论保持一致。
7. 五年规划写准备、建设、申请和评估安排；成果数量、材料类别与逐项证据完整度分别评价。资料待补项保留在对应位置。

## 分析方法

- 风险按“事实或信号—影响—核验或处理动作—关联项目—时间”表达。融资租赁、抵押及诉讼数量结合实际事实判断；关联方风险结合控制、担保、资金、业务或人员传导路径评价。
- 项目标记“公开信息已支持、具备培育可能、请企业提供资料后判断”，正式申报时更新当期政策。风险整改与高企、技改、绿色制造、研发机构、专精特新等计划写入同一风险表、项目启动条件和年度行动。
- 专利区分有效授权、审中、终止、驳回、转入及转出。画像统计与专利性、权利要求、FTO、规避设计、壁垒、挖掘交底、预审分析分别处理，专项请求衔接 `patent-router`。
- 战略覆盖产品、区域、主体、资产投资、技术绿色及五年发展；产品、人员、质量和经营控制信息归入主营业务、风险、项目章节。客户、渠道、报价、账期和回款的专项分析按用户提供资料及目标展开。
- 同行选择参考 [peer-selection-rules.md](references/peer-selection-rules.md)，核验目标企业省级专精特新身份后，内部动态选择近身同行、短期可追对象和行业标杆。报告呈现有解释力的对象与差距，选择方法留在工作记录。
- 同行荣誉核验创新型中小企业、专精特新、小巨人、高企、研发平台、绿色制造、数字化智能制造、标准、知识产权、单项冠军和上市状态等，归入“已有荣誉资质及项目”。名单未命中注明本轮范围，大型企业通过高阶能力反推目标培育证据。
- 项目对标回到政府公示或原文，分别标记备案、公示、拟补助、认定和拨付。模式 A 状态采用红黄绿圆点加文字、风险程度用彩色标签；模式 B 按实际信号在战略风控中分析股权、关联交易、股东往来、未分配利润和税务一致性，基础股东信息保留。
- 结尾按优先级给出客户能理解的问题、影响、动作和对应服务。四问复盘、生成过程、工具回执、品牌审计及修订说明留在对话；正文保留事实、判断、来源和行动。

## 模式 A 生成

1. 采用模式 A 规范、[母版规则](references/sales-master-lock.md)、`assets/sales-master-template.html`、`assets/sales-style.css`。视觉参考为 `assets/sales-master-reference.pdf`，保留橙色封面、章节图标、工商两列表和表格类型；支持图像时查看 `sales-preview-cover.png`、`sales-preview-basic-info.png`、`sales-preview-assessment.png`，按实际查看方式记录验收。
2. 按[结构化输入说明](references/sales-html-input.md)准备本企业 JSON。第七章经营财务数据使用用户提供资料，缺项待补；程序复用母版的 HTML、CSS、图标和 DOM。
3. 共创客户端调用 `gongchuang_skill_operation`，operation 为 `enterprise-panorama-analysis.build-sales-html`，parameters 使用工作区 `input` JSON 和新 `output` HTML 路径。返回 HTML 使用 `deliveryProfileId="enterprise-panorama-standard"` 调用 `gongchuang_deliver_pdf`，交付免水印 PDF 并提供文件入口。
4. 其他宿主使用 `scripts/build_sales_html.py --input <JSON路径> --output <新HTML路径>`、`scripts/render_sales_pdf.py`。依实际完整度标记初稿或定稿，后续失败时复用文件并修复对应步骤。

## 模式 B 生成

1. 采用模式 B 规范、[report-spec.md](references/report-spec.md) 和 `assets/report-style.css`。
2. 项目政策与历史案例按需使用 `local-knowledge-retrieval`，原文或官方来源核验结果进入报告。股权及未分配利润服务机会按已知信号、待取资料和服务方向展开，财税结论对应真实资料。
3. 静态 HTML 在共创客户端使用 `deliveryProfileId="enterprise-panorama-professional"` 调用 `gongchuang_deliver_pdf`；其他宿主运行下列命令并核对实际版式。

```bash
python3 scripts/render_html_report.py --html <HTML路径> --out <PDF路径>
python3 scripts/validate_report_pdf.py <PDF路径> --require-watermark
```

文件名：`<企业全称>_企业全景调研报告_标准销售版_<YYYYMMDD>.pdf` 或 `<企业全称>_企业全景调研报告_GCIP深度顾问版_<YYYYMMDD>.pdf`。

## 能力衔接

财务复算使用 `financial-verification`，制造财税风险使用 `manufacturing-tax-risk-analysis`；项目资格使用 `project-matching`、`project-feasibility`；专利专项使用 `patent-router`，Word 文件核稿使用 `checking-patdocx-cn-single-agent`。网页看板使用当前前端能力与共同底稿，发布按用户指令和宿主权限执行。

外部数据和渲染使用宿主当前能力，缺项时参考 `first-run-configuration` 统一配置并继续可完成部分。团队知识服务通过安全凭据接口读取 `GONGCHUANG_KB_ENDPOINT`、`GONGCHUANG_KB_TOKEN`，日志与交付物使用脱敏信息。资源相对本技能目录解析，输出写当前任务目录。

报告表达采用[报告写作规则](../_runtime/report-writing.md)。

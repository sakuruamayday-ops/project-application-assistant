---
name: hightech-application-writer
description: 国家高新技术企业认定申请书撰写与严格审计工具。覆盖高企空白母版扩缩表（RD/PS 表）、RD 目的及组织实施方式/核心技术及创新点/阶段性成果撰写、PS 高新产品三栏、企业创新能力四栏、OOXML 精准回填与严格字数/密度/勾稽审计。
---

# 高新技术企业申报书撰写与审计（hightech-application-writer）

本技能负责高新技术企业申请书的完整正文撰写、母版扩缩表、OOXML 精准回填与严格门禁验收。

## 交付原则（直接输出可用最终版成稿）

1. **核心栏目写作与字数边界**：
   - 近三年 RD 安排 **15 个以上（每年 5 个以上）**，与科技成果转化形成年均 5 项以上的一一对应闭环；
   - 每个 RD 表的「目的及组织实施方式（限400字）」分 `立项目的：`（痛点/瓶颈/目标）与 `组织实施方式：`（研发模式/贴合企业规模的真实部门分工/阶段里程碑/核算验收），**推荐 280—395 字（代码下限 180 字）**，不超 400 字；
   - 每个 RD 表的「核心技术及创新点（限400字）」采用 7 行格式，具名技术 + 量化指标与单位，**整栏含领域行与标题行合计不超 400 字**；企业未提供第三方检测报告时，按企业规模写入贴合行业均值水平的务实技术指标，直接成最终版稿件（不在正文中写“设计控制目标为……”或占位词）；财务数据与专利号严守真实不编造；
   - 每个 RD 表的「取得的阶段性成果（限400字）」为 4 条带编号具体成果（严格模式 ≥120 字）；
   - 每个 PS 表的 3 个限400字栏目与「七、企业创新能力」4 栏，每栏 180—400 字，落地量化指标、竞品对比或专利映射；前期写稿不强索企业发票。
2. **空白母版先扩表再回填**：若使用 `assets/高新技术企业认定申请书空白模板.docx`，先执行 `scripts/expand_rd_ps_tables.py` 生成 `RD01..RDn` / `PS01..PSm` 编号表，再执行 `scripts/fill_rd_core_innovation.py` 与 `scripts/fill_application_fields.py`。
3. **硬门禁交给脚本**：整本终审交付前运行：
   ```bash
   python3 scripts/audit_application_docx.py <成品.docx> \
     --innovation-evidence <证据边界.json> \
     --include-domain-in-limit \
     --require-complete-form \
     --strict
   ```
   （分段写稿自检时可仅传 `--include-domain-in-limit --strict`。）退出码非 `0` 时按脚本定位精准修订。
4. **交付前评委视角自检**：写稿与核稿参照 `references/hightech-hong-skeleton-and-pitfalls.md` 里的实务骨架与黄金正反对照，确保技术机理连贯自然、企业名称零串户、成果载体界定准确。

## 资产与脚本清单

- `assets/高新技术企业认定申请书空白模板.docx`
- `references/hightech-hong-skeleton-and-pitfalls.md` — 洪老师 55 页高企实务骨架、财务/人员/RD/PS/成果转化/组织管理全套避坑铁律
- `references/section-writing-templates.md` — RD 与 PS 逐段标准句法模板
- `scripts/expand_rd_ps_tables.py` — 按 RD/PS 数量安全扩缩母版表并编号
- `scripts/fill_rd_core_innovation.py` — 批量回填 RD 基本字段、核心技术及创新点、阶段性成果（无匹配 RD 表时硬报错，不再静默 `rd_count=0`）
- `scripts/fill_application_fields.py` — 批量回填企业注册、财务摘要、PS 表、创新能力四栏
- `scripts/audit_application_docx.py` — 全量硬门禁审计（`--strict --include-domain-in-limit`）

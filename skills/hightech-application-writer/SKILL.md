---
name: hightech-application-writer
description: 国家高新技术企业认定申请书撰写与严格审计工具。覆盖高企空白母版扩缩表（RD/PS 表）、RD 目的及组织实施方式/核心技术及创新点/阶段性成果撰写、PS 高新产品三栏、企业创新能力四栏、OOXML 精准回填与严格字数/密度/勾稽审计。
---

# 高新技术企业申报书撰写与审计（hightech-application-writer）

本技能负责高新技术企业申请书的完整正文撰写、母版扩缩表、OOXML 精准回填与严格门禁验收。

## 强制交付铁律（V3 宪章）

1. **禁止偷工减料**：
   - 每个 RD 表的「目的及组织实施方式（限400字）」必须写透 `立项目的：`（行业痛点/技术瓶颈/立项目标）与 `组织实施方式：`（研发模式/团队分工/分阶段里程碑/经费与验收保障），**推荐 280—395 字（代码下限 180 字）**。
   - 每个 RD 表的「核心技术及创新点（限400字）」严格遵循 7 行格式，具名技术 + 量化指标与单位，**整栏含领域行与标题行合计不得超过 400 字**；无实测数据时使用 `设计控制目标为……` 并将估算项写入 `.facts/<主体>.facts.json`，**严禁出现「拟定指标」字样或免责尾注**。
   - 每个 RD 表的「取得的阶段性成果（限400字）」为 4 条带编号具体成果，**严格模式合计不少于 120 字**。
   - 每个 PS 表的 3 个限400字栏目（关键技术及主要技术指标、与同类产品竞争优势、知识产权支撑作用）与「七、企业创新能力」4 栏，**严格模式每栏不少于 180 字、不超过 400 字**，且须含对应量化指标、竞品对比维度或 IP 编号映射。
2. **空白母版先扩表再回填**：若使用 `assets/高新技术企业认定申请书空白模板.docx`，须先执行 `scripts/expand_rd_ps_tables.py` 生成 `RD01..RDn` / `PS01..PSm` 编号表，再执行 `scripts/fill_rd_core_innovation.py` 与 `scripts/fill_application_fields.py`。
3. **双层硬门禁验收**：整本终审交付前必须运行：
   ```bash
   python3 scripts/audit_application_docx.py <成品.docx> \
     --innovation-evidence <证据边界.json> \
     --include-domain-in-limit \
     --require-complete-form \
     --strict
   ```
   （分段写稿自检时可仅传 `--include-domain-in-limit --strict`。）任何退出码非 `0`（含占位符、超 400 字、低于 180 字、缺少双段结构、字体非宋体小四、跨年经费勾稽不一致）一律打回重写。
4. **交付前 Critic Pass 自检与洪老师实务红线**：
   - 写稿与核稿前先参照 `references/hightech-hong-skeleton-and-pitfalls.md` 核对全套实务骨架（RD ≤12 且年均 ≥5、IP 申请日晚于 RD 立项日、PS 名称与开票信息对齐、RD/PS/检测/发票/查新均不直接算“科技成果”、研发组织管理 4 项 20 分证据闭环）；
   - 输出前以高企评审专家视角复核：① 技术指标是否与测试报告/专利一致；② 企业名称是否零串户；③ 文本是否像资深工程师亲手撰写、无“XX方面，”机械套话与分号报菜名。

## 资产与脚本清单

- `assets/高新技术企业认定申请书空白模板.docx`
- `references/hightech-hong-skeleton-and-pitfalls.md` — 洪老师 55 页高企实务骨架、财务/人员/RD/PS/成果转化/组织管理全套避坑铁律
- `references/section-writing-templates.md` — RD 与 PS 逐段标准句法模板
- `scripts/expand_rd_ps_tables.py` — 按 RD/PS 数量安全扩缩母版表并编号
- `scripts/fill_rd_core_innovation.py` — 批量回填 RD 基本字段、核心技术及创新点、阶段性成果（无匹配 RD 表时硬报错，不再静默 `rd_count=0`）
- `scripts/fill_application_fields.py` — 批量回填企业注册、财务摘要、PS 表、创新能力四栏
- `scripts/audit_application_docx.py` — 全量硬门禁审计（`--strict --include-domain-in-limit`）

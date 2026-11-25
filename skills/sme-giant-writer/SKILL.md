---
name: sme-giant-writer
description: 专精特新中小企业、国家级专精特新“小巨人”、国家/省级制造业单项冠军及质量品牌项目（品字标/浙江制造精品/政府质量奖）全流程策划与撰写。覆盖前期培育方向卡、六大核心问题正文、补短板/填空白/进口替代四项判断、技术-产品-收入主矩阵与 A—D 级市占率底稿。
---

# 专精特新“小巨人”与制造业单项冠军撰写（sme-giant-writer）

本技能合并了旧版 `sme-development-projects`、`industry-positioning` 与 `quality-brand-projects`，专攻专精特新中小企业、国家级“小巨人”、制造业单项冠军（`工信部政法〔2023〕138号`、`浙经信大企〔2025〕179号`）与质量品牌项目的深度策划、矩阵生成与申报书正文撰写。

## 核心工作流

1. **读取事实黑板与产品双锁**：先从 `.facts/<主体>.facts.json` 读取经 `gov-project-checkup` 核验的企业档案、财务数据与三层专利分级，确认 `rawAnchor` 与 `formalDeclarationName`、`businessType`（防设备商/产品商倒置）。
2. **生成技术—产品—收入两链汇合主矩阵**：
   ```bash
   python3 scripts/technical_product_revenue_matrix.py <master.json> \
     --adapter small_giant   # 或 provincial_sme / single_champion / zhejiang_manufacturing_excellence
   ```
   验证 `performance_contributions` 完整对象结构，禁止内部转移收入，自动生成分项目视图。
3. **四项独立判断与市占率分级**：
   - 独立输出「主导产品 / 补短板 / 填空白 / 进口替代」四项判断，进口替代不设国外型号检测报告或客户盖章证明为成立前提。
   - 严格按 `references/market-share-grading.md`（A—D 级）构建细分市场占有率测算底稿。
4. **实战模板与多赛道高密度写作**：
   - **专精特新“小巨人”五大栏位**：按 `references/enterprise-introduction-method.md` 执行主导产品定名（+10 位代码）、细分市场占有率 1000 字三段式、产学研合作 300 字、补短板填空白 300 字双体例（**零企业名/简称**）及企业总体介绍 2000 字（**零企业名/简称**），全篇遵循自然工程因果叙事，杜绝“XX方面，”套话与分号报菜名；
   - **方向卡转六大核心问题**：按 `references/direction-card-six-questions-guide.md` 逐项撰稿（单题 ≥ 250 字、目标填充至字数上限的 75%—95%），配套 `assets/专精特新小巨人前期培育方向卡模板.docx`；
   - **隐形冠军 / 单项冠军培育 / 浙江制造精品 / 品字标 / 政府质量奖**：按 `references/hidden-champion-and-quality-brand-templates.md` 标准章节骨架与材料闭环撰写。
5. **真严格硬门禁验收**：
   ```bash
   python3 scripts/validate_sme_assessment.py <assessment.json> \
     --strict \
     --text-file <六大问题正文.md> \
     --company "<企业全称>" \
     --min-chars 250
   ```
   `--strict` 模式下，**任何错误或未闭合告警**（如 `direct_support` 为空、缺少 `rawAnchor`、正文不足字数、含占位符/跨企业串户）一律返回退出码 `2`。

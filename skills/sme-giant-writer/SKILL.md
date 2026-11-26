---
name: sme-giant-writer
description: 专精特新中小企业、国家级专精特新“小巨人”、国家/省级制造业单项冠军及质量品牌项目（品字标/浙江制造精品/政府质量奖）全流程策划与撰写。统一走“前期培育方向卡 → 唯一六问六答技术推演 → 五大申报栏位最终成稿”逻辑链，覆盖主导产品定名、四项独立判断、技术-产品-收入主矩阵与 A—D 级市占率底稿。
---

# 专精特新“小巨人”与制造业单项冠军撰写（sme-giant-writer）

本技能覆盖专精特新中小企业、国家级“小巨人”（`工信部企业〔2026〕2号`）、浙江省隐形冠军、制造业单项冠军（`工信部政法〔2023〕138号`、`浙经信大企〔2025〕179号`）及质量品牌项目的全流程技术推演与最终版申报正文撰写。

## 统一逻辑链（方向卡 → 唯一六问六答 → 五大申报栏位成稿）

1. **读取事实黑板与自主补齐公开事实**：先从 `.facts/<主体>.facts.json` 读取 `gov-project-checkup` 核验的企业档案、荣誉与专利；资料不全时自主联网补齐官网主营、曾用名/实控人关联方、早期技术来源、公开专利与行业大盘，浙江省内政策走本地库/MCP 管控，省外做「当年 + 上年」双年窗口检索。
2. **走唯一一套六问六答技术推演（纯技术导向、与发票无关）**：
   - 严格按 `references/direction-card-six-questions-guide.md`（唯一推演主线，各问细则在其中按需链接）依次完成 **Q1（专利归类与主导产品锁）→ Q2（核心技术簇）→ Q3（补短板/填空白/替代因果链四项独立判断）→ Q4（核心技术与成果应用）→ Q5（国际/同行对标与市占率边界）→ Q6（优势短板与培育规划回写方向卡）**，配套 `assets/专精特新小巨人前期培育方向卡模板.docx`。
   - 需要多项目视图矩阵时执行：
     ```bash
     python3 scripts/technical_product_revenue_matrix.py <master.json> \
       --adapter small_giant   # 或 provincial_sme / single_champion / zhejiang_manufacturing_excellence
     ```
3. **一键映射五大申报栏位最终版成稿**：
   - 将 Q1–Q6 推演结论按 `references/enterprise-introduction-method.md` 直接输出最终版成稿：**主导产品定名与 10 位代码**（Q1）、**1000 字细分市场占有率三段式**（Q5）、**300 字研究成果及应用（含产学研三档分支）**（Q4）、**300 字补短板填空白（严格匿名）**（Q3）、**2000 字企业总体情况简要介绍（三+五八段、严格匿名）**（Q1–Q6 汇总）。
   - 隐形冠军 / 单项冠军培育 / 浙江制造精品 / 品字标 / 政府质量奖按 `references/hidden-champion-and-quality-brand-templates.md` 骨架撰写。
4. **交付前确定性核验**：
   ```bash
   python3 scripts/validate_sme_assessment.py <assessment.json> \
     --strict \
     --text-file <六大问题正文.md> \
     --company "<企业全称>" \
     --min-chars 250
   ```
   缺第三方检测报告时按企业体量采用贴合行业均值水平的务实技术指标，财务数字、专利号与专家名严守真实不编造。

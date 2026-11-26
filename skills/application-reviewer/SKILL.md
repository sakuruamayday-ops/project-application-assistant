---
name: application-reviewer
description: 提交前文字层终审工具：两版 Word 申请书原生对比（改了哪里）、跨章节数字/名称/时间线一致性核对、证据台账算术复算、串户/占位符/免责套话/正文自言自语扫描，以及去 AI 味润色后防丢指标与防夸大审计。不负责判断能不能申报，也不出申请书六大章全景体检报告（这两类交给 gov-project-checkup）。
---

# 申报材料质检、版本对比与润色审计（application-reviewer）

本技能负责申报材料提交前的四道硬核质检关（若需对已填小巨人/专精申请书做六大章全景深度体检，协同 `gov-project-checkup` 的 `application-material-checkup-guide.md` 闭环执行）：

1. **一致性与反敷衍体检（`check-consistency`）**：支持直接读取 `.docx` / `.md` / `.txt`，硬拦截占位符、防御性兜底语、跨企业串户、疑似编辑批注括号、字数不达标或超限，同时智能豁免合法科学单位与文号括号（如 `cm³/(m²·24h)`、`（修订）`）；可选传入 `.facts/<主体>.facts.json` 自动核对外置待核估算项是否已在正文中消化。
2. **原生 DOCX 版本对比（`diff-versions`）**：直接解析两版 Word OOXML，通过 `SequenceMatcher` 精准识别章节重编号移动、表格行重排及关键数字变化，不再把移动的章节误判为“全删+全增”。
3. **证据台账算术与平衡复算（`verify-ledger`）**：对每条 `computed` 主张执行确定性公式复算（阻断 `99.99%` 等错算），同步核验来源完整性、18 位信用代码与资产负债平衡。
4. **中文去 AI 味润色保真审计（`audit-rewrite`）**：对照原文与润色稿，全量校验工程与财务数值单位（`ppm/ppb/Pa/MPa/℃/mm/kW/ms/dB(A)/万元/%`），**丢失数字、凭空编造数字或新增无依据夸大宣称（「国际领先」「世界第一」等）一律返回退出码 `2`**。

## 标准命令行用法

```bash
# 1. 材料一致性与反串户检查（违规退出码 2）
python3 scripts/review_application.py check-consistency <申请书.docx> --company "<企业全称>" --min-chars 200

# 2. 两版 DOCX 原生对比（识别章节/表格行移动与数值变更）
python3 scripts/review_application.py diff-versions <旧版.docx> <新版.docx>

# 3. 证据台账算术复算与来源核验（错算退出码 2）
python3 scripts/review_application.py verify-ledger <evidence_ledger.json>

# 4. 润色保真硬门禁（丢数/篡改/夸大退出码 2）
python3 scripts/review_application.py audit-rewrite <原文.txt> <润色稿.txt> --max-chars 400
```

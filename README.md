<h1 align="center">政府项目与知识产权全生命周期助手（V3.0）</h1>

<p align="center">
  面向政府项目申报工程师与知识产权顾问的专业 Agent 技能套件。<br>
  把政策、企业、财务、知识产权、标准与申报材料组织成可追溯、可复核的 10 个核心技能包。<br>
  顶层技能以 <code>skills/suite-manifest.json</code> 为唯一基线，统一采用纯白干净交付（无机构标识、无水印）。
</p>

<p align="center">
  <a href="skills/suite-manifest.json"><img src="https://img.shields.io/badge/Version-V3.0.0-17181A?style=for-the-badge" alt="Version V3.0.0"></a>
  <a href="docs/V3十个技能包使用速查卡.md"><img src="https://img.shields.io/badge/Skills-10%20Core%20Packs-2F6F4E?style=for-the-badge" alt="10 Core Skills"></a>
</p>

---

## 核心技能清单（10 个独立技能包）

完整使用场景与触发速查见 [`docs/V3十个技能包使用速查卡.md`](docs/V3十个技能包使用速查卡.md)。

| 序号 | 技能包 | 定位 | 核心覆盖范围 |
|---:|---|---|---|
| 1 | `gov-project-checkup` | 免费体检 | 政府项目全周期体检、材料六大章深度诊断、现行政策检索与多项目规划 |
| 2 | `application-reviewer` | 免费体检 | 两版 Word 原生对比、跨章节数字/名称一致性核对、台账复算与润色保真审计 |
| 3 | `hightech-application-writer` | 专项撰写 | 国家高新技术企业申请书空白母版扩缩表、RD/PS 正文撰写与严格审计 |
| 4 | `sme-giant-writer` | 专项撰写 | 专精特新中小企业、2026 版小巨人、制造业单项冠军及质量品牌全流程撰写 |
| 5 | `general-grant-writer` | 专项撰写 | 10 大专项赛道（169 号文省企研、尖兵领雁、三首、技改、智能/绿色工厂等） |
| 6 | `patent-docx-reviewer` | 知产专项 | 中国专利申请 Word 核稿、权利要求保护范围影响评估与精准批注 |
| 7 | `patent-strategy-assistant` | 知产专项 | 专利查新、挖掘、AI 算法发明、FTO 与浙江/杭州双中心预审推荐 |
| 8 | `standard-drafting` | 标准起草 | 按 GB/T 1.1 起草、修订与严格审查国标/行标/地标/团标/企标 |
| 9 | `enterprise-due-diligence` | 尽调合规 | 企业公开信息全景尽调（A/B/C 版）、GB 32100 信用代码校验与新《公司法》过渡期测算 |
| 10 | `manufacturing-tax-risk` | 财税风控 | 制造企业三表复算、现金流分析、智慧税务风险筛查与整改报告 |

## 快速安装与打包

- **独立 ZIP 安装包**：位于 `dist/workbuddy/zips/`，每个技能包独立自包含，可直接导入 WorkBuddy / Codex / Antigravity / DSH。
- **重新构建全部 10 个独立技能包**：

```bash
python3 scripts/build_workbuddy_single.py
```

## 运行验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_core_engines.py tests/test_v3_standalone_zip_acceptance.py tests/test_v3_specialist5_skills.py tests/test_codex_v3_final_fixes.py
```

## 使用边界

- 不承诺企业一定符合条件或项目一定获批，只基于真实资料补强与复核。
- 正式判断优先使用当期在行政策与可核验企业资料，所有交付保持纯白干净版式，不附带第三方机构名称、logo 或水印。
- 客户密钥、账号登录态与私有资料不进入仓库或发布包。

## 许可证

本项目采用[专有许可](LICENSE)：源码可见，未经著作权人事先书面许可，不得用于商业交付、咨询服务、SaaS 或其他商业用途。

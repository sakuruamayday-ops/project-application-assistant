---
name: gov-project-checkup
description: 政府项目全周期体检、材料深度诊断、政策查询与多项目智能匹配引擎。同时覆盖“填报前资格预检（企业画像/财务知产复算/按当年查同行/多项目规划/工业六基匹配）”与“上传已填申报书（Word/PDF）六大章深度体检（财务穿透验算/跨表单逻辑/知产关联/四大叙事板块诊断与改写建议）”，输出确定性复算并写入主体隔离事实黑板。不负责两版 Word 对比和润色保真审计（交给 application-reviewer）。
---

# 政府项目全周期体检与智能匹配（gov-project-checkup）

本技能是 V3 架构的统一体检与规划入口，把**“填报前资格预检”**和**“上传已填申报书深度材料体检”**打通为一套完整闭环。

## 两大核心场景（无缝切换）

### 场景 A · 填报前资格体检、政策核验与多项目规划
1. **本地知识库优先 + 省内外政策分流**：先调用 `scripts/run_checkup.py` 查本地企业画像与历史认定；浙江省内政策直接走本地库或已连接政策 MCP 统一管控，省外用户做一次「当年 + 上年」双年窗口联网检索即可；用户零附件时自主联网补齐官网主营、曾用名/关联方、早期技术来源、公开专利与行业大盘。
2. **确定性复算与红线核验**：18 位信用代码校验（GB 32100）、资产负债平衡、研发费率、2 年复合增长率、专利第 5 位/法定到期日/受让满 1 年均由脚本复算；按申报当年回溯查可比同行（见 `references/peer-point-in-time-rules.md`，严禁跨届/复核混算及事后资质倒灌）。
3. **目录匹配与事实黑板落盘**：通过 `catalog` 检索产业链与“工业六基”（若提示 `match_confidence: low` 则按工艺实质核定，不硬套低分条目），并将核验事实写入 `.facts/<企业简称>_<代码后6位>.facts.json` 供后续写稿技能直接消费。

### 场景 B · 上传已填申报书（DOCX / DOC / PDF）六大章深度材料体检
当用户上传已填好的小巨人、专精特新、高企或专项申请书要求“体检、自检、审查、看看有没有问题”时，先运行 `scripts/split_application_sections.py <文件> --company "<企业全称>" --alias "<曾用名>"` 切出十大章节、识别基准年并测量四大叙事栏位字数与匿名泄露，再严格按 `references/application-material-checkup-guide.md` 执行六大章闭环诊断，报告写完运行 `scripts/checkup_self_review.py <报告.md>`（不通过则补齐缺项后重出）：
- **壹、硬性指标与底线排查**（自动识别基准年 `Y/Y-1/Y-2`，对接 `工信部企业〔2026〕2号` 等最新阈值与脚本复算）；
- **贰、财务数据穿透验算与逻辑研判**（表内比例 vs 绝对值推导比对 + 经营合理性穿透）；
- **叁、跨表单一致性与知识产权支撑互证**（行业代码/六基/主导产品/补短板闭环 + 专利实质支撑度）；
- **肆、重点产业链 + 工业“六基”双维度定位评判**；
- **伍、四大重点文字板块质量诊断与改写骨架**（主导产品名、300 字补短板[含字数与匿名核查]、300 字产学研/成果应用、2000 字企业简介，同步核查工程时序）；
- **陆、红黄绿三级整改清单**（客观温和建设性口吻，逐条给位置与动作；用户确认后可直接无缝衔接到 `sme-giant-writer`、`hightech-application-writer` 或 `general-grant-writer` 输出最终版成稿）。

## 标准命令行用法

```bash
# 1. 查询企业本地画像、财务冲突与去重认定，并落盘黑板
python3 scripts/run_checkup.py profile --company "示例精密制造有限公司" --workspace . --write-blackboard

# 2. 高新技术企业 9 大硬条件确定性体检（国科发火〔2016〕32号 & 195号）
python3 scripts/run_checkup.py hightech --input company_ht.json --strict

# 3. 专精特新中小企业 / 小巨人（工信部企业〔2026〕2号）体检
python3 scripts/run_checkup.py sme --input company_sme.json --strict

# 4. 洁净检索政策并核验有效期与省市区县层级
python3 scripts/run_checkup.py policy --query "高新技术企业认定管理工作指引" --region "宁波市鄞州区" --strict

# 5. 查询同项目、同地区去重可比同行（支持按申报当年回溯统计）
python3 scripts/run_checkup.py peers --project "隐形冠军" --region "杭州" --year 2025 --exclude-review --apply-date 2025-10-31 --benchmark --limit 50

# 5b. 写入/查询侧挂懒加载时间轴缓存库（与只读主库物理隔离，按统一社会信用代码关联）
python3 scripts/run_checkup.py cache-ingest --type patent --uscc 913301097345191192 --input qcc_patent.json
python3 scripts/run_checkup.py cache-query --uscc 913301097345191192 --as-of 2025-12-28

# 6. 叶节点加权检索《产业链架构》与《产业基础创新发展目录（2021）》
python3 scripts/run_checkup.py catalog "高阻隔复合膜"
```

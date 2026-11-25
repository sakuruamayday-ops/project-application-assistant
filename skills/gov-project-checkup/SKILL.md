---
name: gov-project-checkup
description: 政府项目免费诊断与智能匹配入口。整合企业画像、财务与知产核验、政策检索与效力核验、高企/专精特新/小巨人预评估、多项目匹配规划、可比同行对标及产业链与“工业六基”目录匹配；优先直连本地知识库（无需 MCP），输出确定性复算结果并写入主体隔离事实黑板。
---

# 政府项目诊断与智能匹配（gov-project-checkup）

本技能是 V3 架构的统一免费前置诊断引擎，用 1 个高可靠闭环替代旧版 11 个分散查库/体检/匹配技能。

## 核心原则

1. **本地知识库优先（零 MCP 依赖）**：优先调用 `scripts/run_checkup.py` 直查本地 `jiaotang.db` 与洁净版 `rag-query.sh`；仅当本地缺失且用户提供在线工具时作为补充。
2. **确定性复算与真严格门禁**：所有信用代码校验（GB 32100 模31）、资产负债表平衡（资产 = 负债 + 权益）、研发费用率分档（5%/4%/3%）、2年复合增长率、专利第5位类型核验/法定到期日/受让满1年均由 Python 脚本复算；`--strict` 模式遇红线或过期政策返回退出码 `2`。
3. **跨省市全覆盖**：自动解析浙江省11个地级市全部区县及全国省市层级，不再硬编码杭州。
4. **事实黑板落盘**：完成企业画像与诊断后，通过 `fact_ledger.py` 将核验事实写入 `.facts/<企业简称>_<代码后6位>.facts.json` 供后续高企、小巨人或专项申报写作技能直接消费。

## 标准命令行用法

```bash
# 1. 查询企业本地画像、财务冲突与去重认定，并落盘黑板
python3 scripts/run_checkup.py profile --company "浙江申新新材料包装有限公司" --workspace . --write-blackboard

# 2. 高新技术企业 9 大硬条件确定性体检（国科发火〔2016〕32号 & 195号）
python3 scripts/run_checkup.py hightech --input company_ht.json --strict

# 3. 专精特新中小企业 / 小巨人（工信部企业〔2026〕2号）体检
python3 scripts/run_checkup.py sme --input company_sme.json --strict

# 4. 洁净检索政策并核验有效期与省市区县层级
python3 scripts/run_checkup.py policy --query "高新技术企业认定管理工作指引" --region "宁波市鄞州区" --strict

# 5. 查询同项目、同地区去重可比同行
python3 scripts/run_checkup.py peers --project "专精特新" --region "杭州" --limit 15

# 6. 叶节点加权检索《产业链架构》与《产业基础创新发展目录（2021）》
python3 scripts/run_checkup.py catalog "高阻隔复合膜"
```

## 交付结构

- **综合结论**：先给出「可申报 / 补证后申报 / 暂不建议」与首选项目排序。
- **确定性核验表**：逐项列出红线、阈值、企业实测值与差距（附计算公式）。
- **政策与同行依据**：列出核验有效的文号、层级及去重同行参考。
- **下一步补强清单**：按优先级列出财务、知产、资质与产品归类补强动作。
- 免费诊断层**不包含**付费空白申报书母版或成品全文撰写；如需正文撰写，转入 `hightech-application-writer`、`sme-giant-writer` 或 `general-grant-writer`。

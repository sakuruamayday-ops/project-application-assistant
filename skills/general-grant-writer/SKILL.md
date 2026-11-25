---
name: general-grant-writer
description: 通用政府项目可行性报告与专项申报书撰写引擎。统一覆盖省级企业研究院、首台套/首批次/首版次/工业新产品、技改设备更新、智能/未来工厂、绿色工厂、现代农业、领军人才、外贸跨境、知产强企及通用立项可行性10大赛道，配套高密度 Playbook 与真严格统一门禁脚本。
---

# 通用政府专项申报与可行性报告撰写（general-grant-writer）

本技能将旧版 11 个高度同质化的垂类项目与写作技能融合为 **1 套强核心引擎 + 10 份高密度赛道 Playbook + 1 个全赛道真严格校验器**，彻底消除空壳目录与假严格门禁。

## 10 大专项赛道与 Playbook 索引

执行任何专项任务前，先读取对应 Playbook 确认当年政策基线、指标口径与撰写结构：

1. **省级企业研究院 / 研发机构 / 科技计划与奖励** → `references/playbooks/01-institute-and-tech-innovation.md`（含 `浙经信高新〔2025〕169号`）
2. **首台套 / 首批次 / 首版次 / 工业新产品** → `references/playbooks/02-three-first-and-industrialization.md`
3. **技改 / 设备更新 / 固定资产投资补助** → `references/playbooks/03-investment-subsidy-and-tech-renovation.md`
4. **数字化车间 / 智能工厂 / 未来工厂 / 5G工厂** → `references/playbooks/04-digitalization-and-smart-factory.md`
5. **绿色工厂 / 绿色供应链 / 节能降碳** → `references/playbooks/05-green-factory-and-carbon.md`（含 `工信部节〔2024〕13号`）
6. **农业龙头企业 / 现代农业与乡村振兴** → `references/playbooks/06-agriculture-and-rural.md`
7. **海外高层次人才 / 领军人才 / 杭州算力与人才政策** → `references/playbooks/07-talent-and-startup.md`
8. **外贸稳拓调优 / 跨境电商 / 海外仓** → `references/playbooks/08-trade-and-open-economy.md`
9. **知识产权示范 / 强企 / 高价值专利培育** → `references/playbooks/09-ip-projects.md`
10. **通用可行性评估报告与立项申报书撰写** → `references/playbooks/10-general-feasibility-and-writing.md`

## 强制交付前硬门禁

任何赛道成品交付前，必须执行统一校验脚本（所有违规均返回退出码 `2`）：

```bash
python3 scripts/validate_grant_deliverable.py \
  --track <institute|three-first|subsidy|digitalization|green|agriculture|talent|trade|ip-project|feasibility> \
  --input <track_data.json> \
  --text-file <申报正文.md> \
  --company "<企业全称>" \
  --min-chars 250
```

如需生成标准化可行性评估 Word / HTML 报告，使用 `scripts/generate_report.py`（已修复 `conditions` 静默丢弃与 `客户填写` 占位词缺陷）。

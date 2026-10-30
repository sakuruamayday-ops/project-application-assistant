---
name: project-rule-manager
description: 在用户工作区录入、更新、比较、撤回和读取各地区政府项目规则，管理年度、官方来源、门槛评分材料及核验状态；本地修改与团队知识服务分别管理。
---

# 本地项目规则管理

按用户指定资料和目录管理规则，默认 `project-rules/`；隔离任务采用指定目录。联网核验按用户任务要求使用官方来源，本地录入和查询可直接进行。

## 目录与接口

```text
project-rules/<省>/<市>/<区县或省级>/<项目标准名称>/
├── rule.yaml
├── sources/
├── versions/
└── audit.jsonl
```

`rule.yaml` 保存结构化规则，`sources/` 保存原文及链接，`versions/` 保存变更快照，`audit.jsonl` 记实际修改和查询事件及时间，敏感信息采用脱敏值。

```bash
python3 scripts/local_rules.py create --input <提取的JSON> --output <新项目目录>
python3 scripts/local_rules.py query --input <rule.yaml> --status candidate --status verified --year <年度>
```

`rules` 数组各项有唯一 `id`、状态、来源及已知年度，未知日期留空；新建输出 JSON 兼容 YAML 的 `rule.yaml`。征求意见可用 `--status draft` 单列，筛选状态与法律效力分别核验。

## 版本与状态

1. 状态采用 `draft`、`candidate`、`verified`、`stale`、`superseded`、`withdrawn`，按实际来源与核验记录填写。
2. 管理办法、细则、通知、公示及废止依据分别关联，每项条件保留官方 URL、页码或原文位置。
3. 数字、日期、机关、地区与口径变化生成差异及旧来源快照，更正关系与状态分别登记；`superseded` 用于已替代的旧记录。
4. 用户新增或模型提取内容记候选，对照政府原文后的已核项记 `verified`。日期和有效期按原文或明确适用关系继承，操作时间由真实写入进程取得。
5. 撤回使用 `withdrawn` 并保留历史；具体删除、替换及云端写入按用户本轮对象和宿主权限执行，本地与团队服务分别记录。
6. 判断使用当前地区已核规则、知识服务及官方原文，冲突保留差异并说明最新适用依据。

## 地区与交付

地区按当前任务、企业登记或已确认默认值，检索覆盖对应区县、市、省和国家；临时切换保留其他地区资料。文件能力待满足时提供 `rule.yaml`、来源和差异下载，说明实际保存状态。动态日期和申报状态按官方来源更新，已有本地规则继续可用。

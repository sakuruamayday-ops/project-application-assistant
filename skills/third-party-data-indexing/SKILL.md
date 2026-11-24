---
name: third-party-data-indexing
description: 按用户任务增量索引企策顾问等已授权第三方的政策、条件、项目和公示名单，支持 SQLite、补采、断点、去重、版本、链接检查及 Markdown/JSONL 导出。
---

# 第三方数据增量索引

当前为实验性能力。离线资料直接交索引引擎处理；网页采集使用现有浏览器及授权会话，需要配置时衔接 `first-run-configuration`，官方政策判断按任务参考 `policy-retrieval`。

## 采集与更新

1. 按用户账号权限和指定范围采集，`web-task-operator` 负责网页搜索、翻页、详情及登录交互。凭据由浏览器与宿主安全接口管理，业务导出使用脱敏字段。
2. 将业务 JSON/JSONL 放入入箱后 `scripts/index_engine.py ingest`。申报通知提取条件，公示提取页面或附件的企业名单，新增、变更和缺原文记录展开详情。
3. 记录批次、日期、新增、变更、重复、失败和官方链接缺失数，`scripts/quality_monitor.py` 可记录分页、限频、验证码、登录和链接情况。
4. 登录、验证码及访问权限通过网站正常流程处理；暂未取得数据保留采集计划，已取得部分继续入库和输出。
5. 用户要求定时任务时，由宿主按选择时间调用 `scripts/daily_update.py`，读取上次成功日补采。已有 `aiqice-YYYY-MM-DD.json/.jsonl` 可直接更新，待采部分输出请求并由可用网页能力补齐。

自动化参考 `references/daily-automation-prompt.md`，实际采集、计划和无人值守能力分别记录。

## 批次履历与交付检查

每批索引交付附采集履历和检查表，两者以批次和源记录标识关联入箱数据。沿用 `source_record_id` 或原始 `id`，缺源标识时用入箱文件及行号或数组位置定位记录。

- 采集履历按批次承接上游已尝试通道及失败原因，逐记录保留实际取得方法和来源位置，分别标明网页自动提取、浏览器本地导出和人工提供文件。原始证据缺失的记录列入缺项清单，已取得且可校验的数据继续导入。
- 检查表对字段完整性、分页覆盖、去重、来源链接和授权范围逐项记录「已取得」「部分取得」「未取得」或「不适用」，并附证据路径或索引记录 ID。证据齐全记「已取得」，证据有缺项记「部分取得」并列出缺项，无证据记「未取得」，不适用时记录原因。

`ingest` 在数据库所在目录的 `reports/` 生成 `<批次号>_batch_history.json` 和 `<批次号>_delivery_checklist.json`，输出的 `reports` 字段给出两份路径。两份文件均通过回读校验才可记为成功。缺文件或缺字段时命令返回非零，批次记为失败，已写记录可查询和重导。

## 路径与命令

默认根 `~/.project-application-assistant/index/`，含 `policy-index.sqlite3`、`inbox/`、`requests/`、`markdown/`。可用参数或 `PROJECT_APPLICATION_ASSISTANT_INDEX_ROOT` 设置路径。

```bash
python3 scripts/index_engine.py init
python3 scripts/index_engine.py ingest --input <browser-export.jsonl> --source aiqice
python3 scripts/index_engine.py query --region 浙江省 --keyword 申报 --limit 20
python3 scripts/index_engine.py query --year 2026 --include-inactive
python3 scripts/index_engine.py status
python3 scripts/index_engine.py export --format markdown
python3 scripts/daily_update.py --open-browser
```

## 数据方法

字段及去重见 `references/index-schema.md`。源 `id/year/version/status/source` 分别保存 ID、年度、源版本、申报状态及来源，URL 和发布日期取原文。`--source` 作为稳定命名空间，同来源复用；年度用 `--year`，失效记录用 `--include-inactive`，initial/update 批次依序原样导入。

采集日取引擎系统时钟，来源明确的历史日或用户要求回填时使用 `--collection-date`。输入采用当前指定文件，输出记录实际范围、状态和待采项。

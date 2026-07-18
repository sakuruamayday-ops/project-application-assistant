---
name: third-party-data-indexing
description: 实验性第三方数据索引技能。将企策顾问等用户有权访问的第三方政策、申报项目、申报条件及通过或公示企业名单增量写入本地SQLite索引，支持漏采补采、断点、限速、去重、版本记录、官方链接健康检查及Markdown或JSONL导出。仅在用户明确启用并要求更新政策库、采集企策顾问、建立项目索引、查询当日申报通知、公示名单或配置定时补采时使用。
---

# 第三方数据增量索引

> 当前状态：实验性。默认不启用，不作为项目匹配或正式政策判断的必需依赖。

启用前读取 `first-run-configuration` 生成的能力报告；浏览器能力未确认时回到统一向导，不单独保存或重复询问企策顾问登录信息。

## 执行边界

1. 只处理用户使用自有账号和合法权限取得的数据。
2. 调用 `web-task-operator` 完成扫码登录、列表检索、翻页、详情读取和人工接管；本Skill不保存密码、Cookie、Token或认证Header。
3. 浏览器将脱敏业务数据导出到入箱，再运行 `scripts/index_engine.py ingest`。
4. 第三方数据只是发现线索；进入正式推荐前调用政策检索Skill核验官方原文。
5. 遇到登录失效、验证码、付费限制、访问拒绝或服务条款限制时停止，不规避。

## 每日工作流

1. 仅在用户明确配置后，由宿主自动化按用户选择的时间调用 `scripts/daily_update.py`；每日17:00只是可选示例，不是强制默认值。
2. 读取上次成功日期，生成当日与缺失日期的补采计划。
3. 如入箱已有 `aiqice-YYYY-MM-DD.json` 或 `.jsonl`，自动写入SQLite。
4. 如缺少数据，输出标准采集请求；宿主自动化继续调用 `web-task-operator` 取得数据后再执行当日更新。
5. 采集成功后写入批次、日期、新增、变更、重复、失败和官方链接缺失数。
6. 只对新增、变更或缺少官方原文的记录打开详情页。
7. 申报通知必须采集申报条件；公示公告必须采集页面或附件明确列出的通过、公示企业名单。
8. 使用 `scripts/quality_monitor.py` 记录翻页、限频、验证码、登录失效和官方链接有效率。

宿主自动化提示词见 `references/daily-automation-prompt.md`。宿主不支持自动化时，本地调度器会产生待采集请求并可打开企策顾问页面，但不得声称已完成无人值守取数。

## 默认路径

- 根目录：`~/.project-application-assistant/index/`
- SQLite：`policy-index.sqlite3`
- 浏览器导出入箱：`inbox/`
- 待执行采集请求：`requests/`
- Markdown归档视图：`markdown/`

用户不需要手工编辑多份配置。需要改路径时使用命令参数或 `PROJECT_APPLICATION_ASSISTANT_INDEX_ROOT`。

## 命令

```bash
python3 scripts/index_engine.py init
python3 scripts/index_engine.py ingest --input <browser-export.jsonl> --source aiqice --collection-date 2026-07-13
python3 scripts/index_engine.py query --region 浙江省 --keyword 申报 --limit 20
python3 scripts/index_engine.py status
python3 scripts/index_engine.py export --format markdown
python3 scripts/daily_update.py --open-browser
```

## 数据规范

字段、去重、版本和授权规则见 `references/index-schema.md`。企策顾问浏览器导出字段与本Skill字段一致，不包含认证信息。

---
name: third-party-data-indexing
description: 实验性第三方数据索引技能。将企策顾问等用户有权访问的第三方政策、申报项目、申报条件及通过或公示企业名单增量写入本地SQLite索引，支持漏采补采、断点、限速、去重、版本记录、官方链接健康检查及Markdown或JSONL导出。仅在用户明确启用并要求更新政策库、采集企策顾问、建立项目索引、查询当日申报通知、公示名单或配置定时补采时使用。
---

# 第三方数据增量索引


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

每次触发时，从宿主提供或当前已读取的 `SKILL.md` 实际路径定位本技能目录，并运行其 `scripts/portable_skill_runtime.py prepare`。不得假设特定宿主变量或猜测路径。

宿主若只暴露 `run_code`，`skill`、`read`、`web_search`、校验器等工具均须在其中以 `await tools.<name>(...)` 调用，不得根级调用隐藏工具。先按 `SKILL.md` 或参考文档执行命令；不得为理解用法预读脚本、模板、示例或测试，只有真实命令报错且契约不明确时才读取直接相关源码。

`fail` 表示签名、发布者身份或完整性失败，必须停用受影响副本；`limited` 表示已验签副本的依赖或偏好读写受限，仅在任务所需能力仍满足时继续并说明边界。只应用返回的 `active_preferences`；临时要求不持久化，明确授权的长期习惯才按协议保存。偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

> 当前状态：实验性。默认不启用，不作为项目匹配或正式政策判断的必需依赖。

启用前读取 `first-run-configuration` 生成的能力报告；浏览器能力未确认时回到统一向导，不单独保存或重复询问企策顾问登录信息。

用户已提供离线数据时，直接使用现有索引引擎处理，不为入库先启动浏览器、联网或专业政策校验。只在实际采集或作正式政策判断时执行对应步骤。

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
python3 scripts/index_engine.py ingest --input <browser-export.jsonl> --source aiqice
python3 scripts/index_engine.py query --region 浙江省 --keyword 申报 --limit 20
python3 scripts/index_engine.py query --year 2026 --include-inactive
python3 scripts/index_engine.py status
python3 scripts/index_engine.py export --format markdown
python3 scripts/daily_update.py --open-browser
```

## 数据规范

字段、去重、版本和授权规则见 `references/index-schema.md`。企策顾问浏览器导出字段与本Skill字段一致，不包含认证信息。

离线记录的 `id/year/version/status/source` 可直接导入，分别保留为源记录 ID、年度、源版本、申报状态和逐条来源。不要把 ID 伪造成网址，也不要把年度补成不存在的发布日期。`--source` 是整批采集来源的命名空间，重复导入同一来源时保持不变。按年度使用 `query --year`，不是标题关键词；检查失效记录时加 `--include-inactive`。若输入按 initial/update 分批，分别原样导出数组再依次导入，不改业务字段。

采集日期默认由引擎读取当前系统日期。只有来源明确记载实际采集日或用户要求历史回填时才传 `--collection-date`；不能为 initial/update 自行编造两个历史日期。只读取指定输入和技能自身脚本说明，不借阅同目录中的旧任务结果作为输入或格式依据。

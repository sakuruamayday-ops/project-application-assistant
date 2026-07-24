---
name: third-party-data-indexing
description: 实验性第三方数据索引技能。将企策顾问等用户有权访问的第三方政策、申报项目、申报条件及通过或公示企业名单增量写入本地SQLite索引，支持漏采补采、断点、限速、去重、版本记录、官方链接健康检查及Markdown或JSONL导出。仅在用户明确启用并要求更新政策库、采集企策顾问、建立项目索引、查询当日申报通知、公示名单或配置定时补采时使用。
---

# 第三方数据增量索引


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "third-party-data-indexing" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

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

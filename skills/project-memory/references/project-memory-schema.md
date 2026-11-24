# 项目记忆结构

项目标识由企业完整名称、项目全称和申报年度组成。

记录分为：`identity` 企业与项目身份、`policy` 已确认政策版本、`facts` 已确认事实及证据编号、`decisions` 用户确认决定、`pending` 待补材料、`artifacts` 交付物路径和结果引用、`updated_at` 更新时间。

已授权保存的交付引用分别记录 request_id、result_id、result_version、result_digest 和 artifact_path，request_id 只定位当前调用，result_id 与版本定位可复用业务结果，result_digest 核对内容；取宿主真实返回值，只有文件哈希时另记 artifact_sha256 并将缺失的业务身份字段保留空值，凭据留在宿主安全存储。

政策效力、企业登记、专利状态和服务状态属于可变事实，超过七天或进入新申报批次时重新核验。

项目事实与个人写作偏好分别保存；凭据、证件原文及无关通信留在其受控来源，项目记录采用必要脱敏字段。

## 交接清单

1. 写明企业、项目、年度、当前版本及接手目标。
2. 梳理已核事实、采用的政策和用户决定，附能打开的原件或产物引用。明确实际回读结果与验证范围。
3. 列出缺项、阻塞、优先级及接手人的下一步，注明每项验收条件。需要客户端或账号操作的，记录当前会话状态和由接手人完成的登录步骤。
4. 给出必要技能入口和产物位置。外部接手只提供授权范围内的材料和访问入口，凭据留在宿主安全存储。

## 迁移事件

在本次已授权的项目状态保存范围内，为移除或搬迁条目记录事件版本、日期、条目标识、操作类型、前后内容 SHA-256 和去向，删除操作的去向记空值；合并前先查同一企业、项目及年度授权状态集合内的事件和现存内容，已移除条目沿移除状态处理，已迁移条目沿新位置处理，恢复旧内容须有当前明确恢复指令。

## 同步回执

1. 写入前运行 `python3 scripts/project_state.py prepare-sync 项目状态.json --fields facts pending > 写入快照.json`。把 `--fields` 换成本轮授权的顶层字段。快照记录 `identity`、`version`、`fields` 和结构化的 `local_state`。
2. 宿主按快照写入目标后，从目标存储重新取出实际状态。回读文件保留原有类型及字段缺失情况。将已发生操作按顺序存为 JSON 数组，运行 `python3 scripts/project_state.py verify-sync 写入快照.json --readback 目标回读.json --operations 已发生操作.json`。宿主回读失败时，传入 `--readback-error` 及实际错误原因。
3. 回执保留写入快照、`target_readback`、`differences` 和 `operations`。主体、版本及授权字段逐项一致时返回 `pass`。授权字段下的对象和数组逐层比对。差异记录 `path`（JSON Pointer）、`expected`、`actual` 和 `kind`（`missing` 缺失、`unexpected` 多出、`mismatch` 不同）。回读失败时 `target_readback` 为 `null`，差异记录回读失败原因。`fail` 的退出码为 `2`。保存本地状态与回执，结束该次同步，继续独立任务。

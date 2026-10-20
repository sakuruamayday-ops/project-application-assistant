# 业务分析定稿收集

此入口与错误诊断、诊断附件、知识索引分开。只接收 V0.7.6 起由原任务标记为 `report_kind=business-analysis`、`stage=final` 的文件。客户端负责原任务的定稿判断及只从新版生成过程入队；服务端校验类型、阶段、版本、账号归属、大小和文件完整性，不根据聊天文本猜测定稿，不扫描历史文件。

每个文件、每次定稿使用新的 UUID `request_id`。保留原稿、历史稿或原材料不会使它们自动进入收集。归集只接收 `.doc/.docx`、`.xls/.xlsx`、`.ppt/.pptx`、`.pdf`、`.html/.htm`，扩展名不区分大小写；此范围不限制其他格式的本地生成和发布。传输沿用已有附件的单文件 256 MiB 范围；超限文件应保留在客户端并显示待处理。

## 客户端接口

沿用客户端密码登录的 Bearer 凭据及 `X-Jiaotang-Device-ID`，请求带 `X-Jiaotang-Client-Version`。账号、设备和当前最低支持版本继续生效；收集功能另外要求 V0.7.6 起，不改变其他服务的最低版本。

`POST /v1/client-reports`：

```json
{
  "request_id": "94587080-b126-4bc5-ab09-07ad8ff862a8",
  "filename": "企业分析定稿.pdf",
  "size_bytes": 12345,
  "sha256": "文件内容的64位小写十六进制SHA256",
  "generated_at": "2026-10-20T02:00:00Z",
  "title": "企业分析报告",
  "company_name": null,
  "skill_name": null,
  "skill_version": null,
  "client_version": "0.7.6",
  "report_kind": "business-analysis",
  "stage": "final",
  "final_reason": "原任务已确认本文件为定稿"
}
```

`sha256` 必须填真实文件摘要。文件名只能是显示名称，不能含本机路径。接口不接受成员 ID、本机路径、聊天或额外字段。返回 `{"report_id":1,"next_offset":0,"complete":false}`。同一登录成员与 `request_id` 重试返回原收取进度，元数据不同返回 409。新定稿版本使用新的 `request_id`，不覆盖旧版本。

`POST /v1/client-reports/1/content` 接受 `{"offset":0,"content_base64":"..."}`，每块原始数据最多 1 MiB，返回 `{"next_offset":1048576,"complete":false}`。重复或错位分块返回已持久保存的进度。文件收齐且 SHA-256 匹配后才返回 `complete:true`；校验失败返回 422 并重置收取进度为 0，客户端可重新登记同一元数据取进度后重传。文件未收齐或校验未通过不能下载。完成后的文件不能通过重传覆盖。

独立表为 `client_reports`；文件目录为 `DATA_DIR/client-reports/<report_id>/content`。服务器保存文件名及最小业务元数据，不保存本机路径。`/client-reports` 列出报告，管理员可查看和下载全部，普通成员只可查看和下载自己账号的报告；网页下载不代替管理员本机收取确认。

## 现有 SSH 运维身份收取

不增加服务账号、密钥或登录方式。在服务目录使用现有 Python 运行环境执行：

```sh
python scripts/client_reports.py --database /var/lib/jiaotang-kb/knowledge.db --root /var/lib/jiaotang-kb/client-reports list
python scripts/client_reports.py --database /var/lib/jiaotang-kb/knowledge.db --root /var/lib/jiaotang-kb/client-reports export --report-id 1
python scripts/client_reports.py --database /var/lib/jiaotang-kb/knowledge.db --root /var/lib/jiaotang-kb/client-reports acknowledge --report-id 1
python scripts/client_reports.py --database /var/lib/jiaotang-kb/knowledge.db --root /var/lib/jiaotang-kb/client-reports cleanup --dry-run
python scripts/client_reports.py --database /var/lib/jiaotang-kb/knowledge.db --root /var/lib/jiaotang-kb/client-reports cleanup --report-id 1
```

`list` 只读返回 `{"reports":[...],"next_offset":null}`，默认每页 100 条，可传 `--limit`（1–1000）与 `--offset`。仅列出完整且未确认收取的报告，包含 `report_id`、`user_id`、登录成员的 `member_name`、全部上述元数据、收取状态和时间；不输出服务器文件路径。收取时先取得全部分页列表再确认，或每批确认后重新从 offset=0 开始，避免列表变短导致跳项。

`export` 先校验服务器文件，再向 stdout 输出原始二进制；错误仅向 stderr 输出安全错误类别。调用方成功下载并保存本机文件、完成归属归档及本机收取回执后，以精确 `report_id` 调用 `acknowledge`，再按每日流程释放服务器副本。下载后不重复计算或核对大小、SHA-256；确认幂等，不触碰诊断数据。上传时及正常下载前的已有完整性校验保留。

`cleanup --dry-run` 只预览，不改文件、状态或时间。实际释放使用精确 `--report-id`，仅允许已完整上传且每日流程已成功保存并确认下载的一份服务器报告副本；只核对独立报告目录和非符号链接的普通文件路径，不再重复读取文件大小或 SHA-256。知识、诊断、未下载副本和其他文件不在授权范围。每日流程的此项副本永久释放已获明确授权，不新增独立后台服务。

清理保留数据库记录及 `cleaned_at`，返回 `{"report_id":1,"cleaned_at":"...","deleted":1}`。重复调用返回原清理时间及 `deleted:0`。`cleanup_requested_at` 在移除文件前记录操作意图；进程在文件操作和完成回执之间退出时，同一报告编号可继续确认，未记录清理意图的无文件状态会拒绝。完整下载后的本机报告、服务器最小元数据和其他报告版本不受影响。

## 当前服务器异常待办

`No response returned` 仍缺少与客户端断开及用户失败的直接关联证据。本次不改安全响应头中间件，不吞异常。Windows blockmap 修复只放行当前正式安装包对应的精确 `.exe.blockmap` 文件，保留原安装包、元数据与路径校验。

# 异步检索任务登记与恢复

## 调用入口

先用 `scripts/build_search_plan.py` 的 `build_plan(payload)` 生成检索计划。宿主将已授权的异步提供器交给 `run_async_search_unit(plan, unit_id, provider, checkpoint_path)`。需要提供器专用检索语法时，传入实际发送的 `query`。同案卷内按提供器及检索式摘要查原任务。计划缺案卷标识时，以检查点父目录作为检索范围。

提供器接口约定如下。

- `name` 在当前工作范围内标识提供器及其账号，凭据留在宿主安全存储。
- `submit(query)` 返回提供器确认的远端任务标识字符串。
- `get_status(task_id)` 读取指定任务，映射为 `queued`、`running`、`completed`、`failed`、`not_found` 或 `unknown`。只有能确认该任务失败或不存在的响应才映射到 `failed` 或 `not_found`。连接、权限、限流或状态无法解析归入 `unknown`。
- `resume(task_id, checkpoint_path, progress)` 先读取检查点中的结果和续读位置，再拉取新增结果。每次先保存检查点，再返回对应进度计数。远端已完成时须读完结果并保存检查点，零结果也写入空结果。读取超时抛出 `TimeoutError`。

## 状态与恢复

登记文件默认位于技能的工作数据目录 `local-overrides/.async-search-tasks.json`。通过 `registry_path` 或环境变量 `PATENT_ROUTER_ASYNC_REGISTRY` 可选工作区内的登记路径，显式参数优先。每个新检索使用专用检查点路径。

| 字段 | 内容 |
| --- | --- |
| `provider` | 提供器标识 |
| `remote_task_id` | 提交成功后立即写入远端任务标识 |
| `query_sha256` | 按结果交付摘要规范序列化实际检索式字符串，再计算 UTF-8 SHA-256 |
| `checkpoint_path` | 持久化结果与续读位置的路径 |
| `progress` | 已写入检查点的进度计数，提交时为 0 |

首次调用确认提交后返回已登记任务。轮询或中断后，用相同案卷、提供器和检索式再次调用，先按原标识读取状态。运行中或远端已完成的任务从原检查点接续。未取到远端标识或读取状态未知时，保留原登记、结果和检查点。

只有 `failed` 或 `not_found` 可在本轮显式传入 `retry_authorized=True` 时重提。新任务用 `retry_of` 关联上一条任务记录并使用独立检查点。

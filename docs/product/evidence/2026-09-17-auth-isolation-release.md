# 客户端与通用 MCP 授权隔离部署证据

## 正式部署

- 完成时间：2026-09-17 17:05:47，中国标准时间。
- 源提交：`14fba533f22dddea77f86f18f7681beb3b0e656e`。
- 部署编号：`20260917T090433Z-14fba533f22d-d91baab8`。
- 前一部署：`20260909T030501Z-0a5b4df00397-96e692bf`，保留为 previous。
- 服务器持久化事务返回 `phase=completed`、`success=true`、`rollback=not-required`。
- 公网 `/health` 返回 `status=ok`，数据库和知识索引检查为 true，返回的提交及部署编号与上述一致。
- 部署模式为 code，客户端安装包、技能版本和知识索引未更新。

## CI

[正式 CI 运行](https://github.com/sakuruamayday-ops/project-application-assistant/actions/runs/35202667141)全部成功：根测试 388 passed / 8 skipped；门户测试 695 passed / 8 skipped；Windows 与 Linux WorkBuddy 连接器检查通过。跳过项不计为通过。

最初 CI 因新文档包含内部工作树名称失败，文档修正后重新运行；最终部署仅使用上述成功 CI 的依赖产物。

## 公网专项验收

使用独立合成普通账号，通过正式域名发送 HTTP 请求，不使用真实客户账号或凭据。

| 场景 | 实际结果 |
| --- | --- |
| 设备 A 登录客户端 | 200 |
| 登录态门户获取通用 MCP 配置 | 200；通用 Token 与客户端 Token 不同 |
| 取得通用配置后继续使用设备 A | 200 |
| 设备 B 登录客户端 | 200 |
| 设备 A 再访问 | 409 |
| 设备 B 再访问 | 200 |
| 设备 B 的 Token 不提供设备标识 | 401 |
| 模拟 WorkBuddy 使用通用 Token 调用 knowledge_service_status | 200，connected=true |
| 模拟其他宿主使用相同通用 Token 调用 knowledge_service_status | 200，connected=true |
| 两次 MCP 调用后设备 B 再访问 | 200 |

测试完成后，合成账号已停用并软删除，凭据已撤销，网页会话已过期；审计记录保留。测试未打开 WorkBuddy 原生界面，验证范围是其实际使用的公网 Bearer/MCP 接口。

## 数据与恢复

部署前使用 SQLite backup API 完成 45,035,520 字节数据库备份，quick_check=ok。备份保存在服务器部署事务目录，权限仅限管理员。与备份逐条关联核对：上线前 10 个 active 凭据，上线后原 10 个均仍有效。

数据库已删除全账号 active Token 唯一约束，保留仅 client 类型的唯一约束；设备绑定按客户端与历史第三方分组保持唯一。历史第三方绑定不会占用客户端登录名额。

本次没有执行灾难恢复演练。若需回退旧代码，必须评估旧版初始化的全账号凭据去重行为，不能把代码回退等同于授权状态无损回退。

## 使用提示

旧配置若包含客户端专用 Token 或已吊销 Token，需要从手工配置页重新复制。有效通用配置不会因客户端登录被再次吊销。未恢复任何历史已撤销凭据。

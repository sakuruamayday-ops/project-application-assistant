# 客户端与通用 MCP 授权隔离

更新日期：2026-09-17

状态：已正式部署。AUTH-0917-01 至 AUTH-0917-04 的部署回执、CI 和公网验收见[发布证据](evidence/2026-09-17-auth-isolation-release.md)。下方本地验证记录保留为部署前阶段记录。

## 范围与规则

同一账号的桌面客户端保持单设备登录，通用技能和 MCP 允许跨设备、跨宿主使用。两类凭据互不吊销。身份验证、账号状态、权限、主动撤销及客户端设备校验继续生效。

| 需求 | 实现与验证 | 发布证据 |
| --- | --- | --- |
| AUTH-0917-01 门户只提供通用凭据 | ensure_personal_access_token 和个人凭据启用入口只复用 personal 且无 binding 的 Token；test_personal_mcp_and_single_device_client_are_independent 检查真实门户响应 | [已部署及公网验收](evidence/2026-09-17-auth-isolation-release.md) |
| AUTH-0917-02 客户端单设备且不影响 MCP | issue_client_login_token 只撤销客户端凭据和客户端绑定；上述参数化测试覆盖两种授权顺序、旧客户端 409、缺设备 401、双宿主 MCP 调用成功 | [已部署及公网验收](evidence/2026-09-17-auth-isolation-release.md) |
| AUTH-0917-03 重启和技能安装不踢掉其他授权 | 数据库按已规范化的 client 类型去重并约束唯一；安装激活不再撤销其他有效凭据；数据库迁移及安装回执测试通过 | [已部署及公网验收](evidence/2026-09-17-auth-isolation-release.md) |
| AUTH-0917-04 通用凭据可主动撤销 | 上述参数化测试撤销并重新取得个人 Token，旧 Token 401，客户端仍有效 | [已部署及公网验收](evidence/2026-09-17-auth-isolation-release.md) |

## 实现边界

不引入第三方设备识别、OAuth 或按宿主限制；复制同一个有效个人 Token 可以在不同软件中使用。旧凭据曾被吊销的状态不自动恢复，用户应重新从门户取得有效配置。已下载的技能文件不受远程吊销控制。

旧的账号级 active Token 唯一索引在数据库初始化中移除；先规范化历史客户端凭据类型，再执行客户端去重，最后建立仅针对 client 的唯一约束。不得恢复旧版全账号去重逻辑，否则服务重启会破坏授权隔离。

## 测试证据

执行目录：正式部署工作树根目录。

```sh
PYTHONPATH=services/knowledge-portal:. .venv/bin/python -m pytest services/knowledge-portal/tests/test_portal.py -q --disable-warnings --maxfail=3
```

结果：159 passed, 5 skipped。5 项跳过为既有 V1.4.5 废弃设备登记流程测试，不作为通过计数。

补充门户取 Token 与两个模拟宿主通过 HTTP 调用 knowledge_service_status 后，定向复测 test_personal_mcp_and_single_device_client_are_independent：2 passed。均使用临时测试数据库及合成账号，未轮换生产用户凭据。

## 发布状态

已将本次补丁单独提取到正式部署工作树，基于线上原提交部署，未混入其他工作树改动。正式部署 `20260917T090433Z-14fba533f22d-d91baab8`，源提交 `14fba533f22dddea77f86f18f7681beb3b0e656e`；未发布客户端或技能包。各需求的发布证据均见上述发布记录，不再处于待发布状态。

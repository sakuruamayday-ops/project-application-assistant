# 登录失败限流取消

状态：已正式部署并通过公网验证。

## 目标与范围

AUTH-0922-03：网页登录和客户端密码登录不再因同一来源地址累计失败次数而阻止后续尝试。保留账号状态与密码校验、失败记录、客户端单设备及通用 MCP 授权隔离。注册和密码找回的限制不属于本次变更。

## 实现与验证

移除 /login 和 /v1/client-login 调用 auth_attempts_blocked 的分支，不改变认证查询或凭据签发。

| 需求 | 测试证据 | 发布证据 |
| --- | --- | --- |
| AUTH-0922-03 取消两个登录入口失败次数限制 | test_login_after_shared_ip_failures_still_checks_password 两个参数场景：同地址预置 12 次失败后，错误密码仍返回 401，正确密码分别返回 303 和 200，失败记录继续保存；连同客户端与通用凭据隔离等定向测试共 10 passed | 部署 20260922T010901Z-8f8664915134-aa6cf17d；公网两个入口各连续 12 次无效登录均返回 401，无 429 |

定向执行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=services/knowledge-portal:. python3 -m pytest services/knowledge-portal/tests/test_portal.py -q -k 'login_after_shared_ip or client_password_login or personal_mcp_and_single_device or registration_invite or login_rate_limit'。

## 风险与恢复

连续错误密码不再触发登录等待期，服务器会持续执行密码校验；此为明确要求的行为变更。现有部署事务保留上一运行槽位用于恢复。无需更新客户端安装包，不更改用户密码或管理员角色。

## 正式发布证据

- 源提交：8f866491513476982dd6786a194a2594837f3769。
- CI：https://github.com/sakuruamayday-ops/project-application-assistant/actions/runs/35674410127，全部成功；根测试 388 passed / 8 skipped，门户 697 passed / 8 skipped。跳过不计通过。
- 部署：20260922T010901Z-8f8664915134-aa6cf17d，2026-09-22 09:10:42 北京时间完成。服务器持久化事务 success=true、phase=completed、rollback=not-required，部署命令退出 0。
- 公网 /login 和 /v1/client-login 各以不存在的合成账号连续请求 12 次，24 次均返回 401，无 429。未创建测试账号或尝试真实用户密码。正确密码超过阈值后成功由 CI 参数化用例验证，未在公网以真实用户登录复测。
- 部署前后 users 全表逐项一致，原有 16 个有效凭据全部保留，服务健康正常。技能和客户端未重新发包。
- 上一部署 20260917T090433Z-14fba533f22d-d91baab8 保留。更旧槽位由既有保留流程移入服务器回收站，未永久删除；回执 cleanup_pending 指回收站待后续清理，不影响部署成功。

本地执行日志与公网回执：`本机数据目录/deployment-inputs/login-throttle-20260922/deploy.log`、`public-login-verification.json`。服务器数据库备份及验收：`/var/lib/jiaotang-kb/admin-audit/login-throttle-20260922/`。原有私有导航与页面覆盖层随代码槽位保留。

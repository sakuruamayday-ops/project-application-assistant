# 登录失败限流取消

状态：已实现并通过定向测试，正式部署待完成。

## 目标与范围

AUTH-0922-03：网页登录和客户端密码登录不再因同一来源地址累计失败次数而阻止后续尝试。保留账号状态与密码校验、失败记录、客户端单设备及通用 MCP 授权隔离。注册和密码找回的限制不属于本次变更。

## 实现与验证

移除 /login 和 /v1/client-login 调用 auth_attempts_blocked 的分支，不改变认证查询或凭据签发。

| 需求 | 测试证据 | 发布证据 |
| --- | --- | --- |
| AUTH-0922-03 取消两个登录入口失败次数限制 | test_login_after_shared_ip_failures_still_checks_password 两个参数场景：同地址预置 12 次失败后，错误密码仍返回 401，正确密码分别返回 303 和 200，失败记录继续保存；连同客户端与通用凭据隔离等定向测试共 10 passed | 待回填 |

定向执行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=services/knowledge-portal:. python3 -m pytest services/knowledge-portal/tests/test_portal.py -q -k 'login_after_shared_ip or client_password_login or personal_mcp_and_single_device or registration_invite or login_rate_limit'。

## 风险与恢复

连续错误密码不再触发登录等待期，服务器会持续执行密码校验；此为明确要求的行为变更。现有部署事务保留上一运行槽位用于恢复。无需更新客户端安装包，不更改用户密码或管理员角色。

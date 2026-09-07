# 门户防误重启补丁

状态：用户已授权继续发布，49 项定向测试通过；正式部署待完成。

## 范围

REQ-25：聚合健康检查包含磁盘、证书、索引巡检等运维状态。2026-09-07 磁盘占用达到 92% 后，健康恢复器对仍可正常服务的门户反复执行重启，实际打断安装包下载并出现 502。

恢复器在原有重启判断前读取本机 readyz，并确认服务处于运行状态、数据库及知识索引就绪。就绪成功只将恢复状态记为 success，清零连续失败计数，不删除运维告警；就绪失败继续原有两次连续失败、窗口内最多三次重启与冷却流程。未修改磁盘失败阈值、证书检查、报警服务、签名、权限或部署回滚。

这不是放宽服务正确性检查：readyz 必須明确返回 status=ok、portal_database=true、knowledge_index=true；缺失字段、非 JSON、HTTP 失败或服务停止均不能跳过原恢复流程。没有新建监控定时器。

## 验证

定向命令：在 services/knowledge-portal 中执行 `PYTHONPATH=.:scripts PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_health_recovery_wrapper.py tests/test_health_recovery_state.py tests/test_deployment_guards.py tests/test_operational_resilience.py tests/test_application_deployment_transaction.py -q`，49 项通过。

受影响的是恢复脚本、现有部署包装器和状态机消费者；上线前按现有 main CI 生成同源依赖产物，再走 code 模式可回滚部署，不发布知识索引或技能包。现有生产私有页面覆盖层保持逐文件一致。

上线验收：正常门户真实执行新恢复入口两次，必须记录 alert_only、主进程不变；以独立临时输出将现有容量阈值设为 1% 触发测试告警，不更改生产阈值，检查告警仍存在、服务不重启。真实服务停机和数据库故障只在隔离测试中模拟，不故意破坏线上服务。公开 readyz、更新清单和安装包 Range 必须可用。

## 发布

CI、源提交、部署编号、回滚槽和线上回执：待回填。客户端仍为 V0.4.5，技能仍为 V1.6.19；本次不要求用户重新安装。

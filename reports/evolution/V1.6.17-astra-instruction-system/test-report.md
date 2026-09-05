# 回归测试报告

## 已完成结果

| 测试层 | 结果 |
|---|---|
| 根目录全量 pytest | 420 passed，3 skipped，74 subtests passed，0 failed |
| 便携运行时与收据定向回归 | 47 passed，1 skipped |
| 独立发布管理器 V1.15.8 | 11 passed |
| 51 项发布清单刷新 | 51/51 pass，0 failures |
| Grounded 产品配置 | pass，全部配置检查为 true |
| 发布管理器源码安装检查 | pass，16 files，固定官方发布者信任 |
| 发布管理器下载包安装检查 | pass，16 files，固定官方发布者信任 |
| `git diff --check` | pass |

## 说明

- pytest 使用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，避免无关全局插件污染仓库测试环境。
- 三个跳过项由测试自身声明的环境条件触发；七条 warning 为 Python/SWIG 弃用提示及恶意重复 ZIP 测试样本的预期告警，不是失败。
- 完整发布清单门禁、通用包隔离安装、GitHub CI、正式 Release 和本机安装回执在提交后执行，并由正式发布回执记录；这些后续结果不得由本报告预先冒充。

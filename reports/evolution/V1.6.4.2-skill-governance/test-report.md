# 回归测试报告

## 结果

| 测试层 | 结果 |
|---|---|
| 根目录全量 pytest | 277 passed，2 skipped，67 subtests passed |
| 知识门户全量 pytest | 592 passed，7 skipped |
| 定向版本、对账、专精特新与 Grounded 合同 | 32 passed |
| 门户发布介绍与安装提示 | 11 passed |
| 对抗用例 | 108 cases pass |
| 技能行为覆盖 | 50 skills pass |
| 技能内容与路由 | 88 cases pass |
| 三首金标 | 20 cases pass |
| 废弃政策语义 | pass |
| 单知识 MCP | pass |
| 套件结构与依赖 | 50 skills，12 dependencies，0 unresolved references |
| 本机全目录对账 | 150 个不同技能名，0 未登记，0 正式缺失 |
| Grounded 注册表 | 50 registered，30 grounded，状态 pass |
| `git diff --check` | pass |

## 环境说明

- 使用系统 Python 运行 pytest 时设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，避免无关的全局 `langsmith` 插件因缺少 `requests_toolbelt` 干扰仓库测试。
- 知识门户按子项目目录和 `PYTHONPATH=.` 执行。
- 旧报告提及的仓库内 `validate_skill_structure.py` 当前不存在；结构校验改由签名发布管理器的 `suite_validation.py` 和后续打包门禁执行，不把脚本路径缺失冒充业务失败。

## 结论

代码、门户、技能内容、行为、对抗、专精特新谈单合同、对账及版本一致性均通过，可进入提交和三平台签名候选构建。

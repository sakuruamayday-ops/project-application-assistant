# 回归测试报告

## 结果

| 测试层 | 命令摘要 | 结果 |
|---|---|---|
| 定向契约与路由 | `pytest test_sme_presale_report_contract.py test_sme_score_preflight.py test_policy_application_path_contract.py test_skill_call_graph.py` | 20 passed |
| 根目录技能套件 | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests` | 275 passed, 2 skipped, 67 subtests passed |
| 知识门户 | 在 `services/knowledge-portal` 运行 `PYTHONPATH=. python3 -m pytest -q` | 591 passed, 7 skipped |
| 技能结构 | `validate_skill_structure.py skills/sme-score-preassessment` | pass |
| 差异格式 | `git diff --check` | pass |

## 环境说明

从仓库根目录一次性运行所有 pytest 时，知识门户测试收集因子项目独立 `PYTHONPATH` 未设置而报 `ModuleNotFoundError` 。该层按子项目入口在 `services/knowledge-portal` 目录配置 `PYTHONPATH=.` 后，591 项通过。该错误属于测试收集路径，不是本批次业务补丁失败。

## 结论

本批次已通过单技能契约、跨技能路由、根目录强制测试和门户子项目回归，可进入与 V1.6.4.2 其他候选补丁的合并和签名前门禁。

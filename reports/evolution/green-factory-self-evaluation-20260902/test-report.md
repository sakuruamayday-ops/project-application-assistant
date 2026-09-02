# 绿色工厂自评价技能候选测试报告

## 自动化结果

| 范围 | 命令或检查 | 结果 |
|---|---|---|
| 新校验器和关联单元测试 | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_green_factory_skill.py tests/test_project_dual_report_contract_v165.py tests/test_skill_call_graph.py tests/test_core_skill_engines.py` | `32 passed` |
| 技能仓全量回归 | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests` | `384 passed, 3 skipped, 74 subtests passed` |
| 技能内容覆盖 | `python3 tests/validate_skill_content_suite.py` | `pass`，22项技能、88个案例 |
| 技能行为覆盖 | `python3 tests/validate_skill_behavior_coverage.py` | `pass`，51项技能基线 |
| Codex Skill 结构 | `quick_validate.py skills/green-development-projects` | `Skill is valid!` |
| 套件技能结构 | `validate_skill_structure.py skills/green-development-projects` | `pass` |
| 进化批次合同 | `validate_evolution_batch.py .../evolution-batch.json` | `pass` |
| Python 语法 | `python3 -m py_compile .../validate_green_factory_ledger.py` | 通过 |
| 差异格式 | `git diff --check` | 通过 |
| 客户标识扫描 | 企业名称模式和中国大陆手机号模式定向扫描 | 未命中 |

系统 Python 首次运行 pytest 时自动加载了环境中的 LangSmith 插件，该插件缺少 `requests_toolbelt`，测试代码尚未执行即退出。随后设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，在不安装新依赖的情况下运行同一测试，全部通过；此环境问题不计为业务回归。

全量回归首次运行时发现绿色工厂技能描述扩展后漏掉既有路由短语“旧通知”，导致只核验历史政策时的 `policy-retrieval` 竞争者门禁失败。候选仅恢复该短语，没有放宽测试或改变评分逻辑；再次运行全量回归后全部通过。该修复改变目标文件哈希，原审批按治理契约失效。

## PDF 样本视觉与结构核验

- 完整提取两份样本的页数、目录、正文、自评表和附件目录文本。
- 分别渲染并查看封面、目录、评价指标表和加分项表代表页，确认表格中的分值、权重、证据栏和附件编号关系不是文本抽取错位。
- 样本 PDF 和渲染中间文件只位于原路径和 `/private/tmp`，未复制进候选仓库。

## 尚未执行

候选当前尚未绑定修复后的新审批。V1.6.16 版本事实已在隔离工作树准备；目标文件变化后的最终发布清单和签名尚未重新生成，也未运行最终三套件解压安装、预发布、宿主安装或正式发布。批准后必须绑定本报告和候选差异的新哈希，再从固定发布者身份重新签名。

# 回归测试报告

## 合并前批准依据

- 高企与模板专项：18 passed。
- 批准时测试报告 SHA-256：`f9befff2342efb2b5a83e5957fac1bc80e78725815cdc745f90c7461e33935f6`。
- 批准时影响报告 SHA-256：`10ca69bca49514727f14565014b432fc20448d7ca1457d15e2ac17781ec72855`。

## V1.6.4.2 合并后回归

| 测试层 | 结果 |
|---|---|
| 高企、模板与套件版本定向用例 | 23 passed |
| 门户发布介绍定向用例 | 10 passed |
| 根目录全量 pytest | 282 passed，2 skipped，67 subtests passed |
| 知识门户全量 pytest | 592 passed，7 skipped |
| 高企技能安装自检 | pass，14 files |
| Grounded 注册表生成一致性 | pass，50 registered，30 grounded |
| JSON、Git差异和脚本权限 | pass |
| WPS Office可用性 | `/Applications/wpsoffice.app` 已发现 |

签名套件的发布清单、三平台解压安装和最终包哈希在打包阶段另行生成回执。

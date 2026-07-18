# 云端知识库上传边界

## 只上传两个目录

1. `<知识库根目录>/_云端知识库`
2. `<知识库根目录>/_云端迁移索引/cloud_package_index`

不得上传整个 `<知识库根目录>/_云端迁移索引`。该目录包含本地 OCR 工作区、构建缓存、干运行报告和清理隔离文件。

## 原始资料目录

`_云端知识库` 保存原始政策、指南、名单、案例、模板和内部方法。上传前已将 macOS AppleDouble、`.WeDrive`、Office临时文件等223份非生产元数据移入隔离区；传输仍设置同类排除规则，防止后续同步工具重新生成。

## 生产索引目录

`cloud_package_index` 只保留以下生产文件：

- `README.md`
- `manifest.jsonl`
- `knowledge_inventory.sqlite3`
- `knowledge_content.sqlite3`
- `policy_versions.sqlite3`
- `summary.json`
- `extraction_summary.json`
- `policy_version_summary.json`
- `extraction_report.csv`
- `upload_allowlist.csv`
- `upload_allowlist_summary.json`

其中：

- `knowledge_content.sqlite3` 是 `/v1/search` 与 `/v1/documents/{id}` 的全文数据源。
- `knowledge_inventory.sqlite3` 保存文件名、分类、哈希和原始路径映射。
- `policy_versions.sqlite3` 保存政策版本、替代关系和原文依据。
- `manifest.jsonl`、`extraction_report.csv` 与 `upload_allowlist.csv` 用于后续增量更新和故障审计。

## 不进入生产上传包

以下文件保留在本地隔离归档中，不上传到生产服务器：

- macOS `._*` 伴生文件。
- `.DS_Store`、`.WeDrive`、`Thumbs.db`、`desktop.ini` 等系统或同步盘元数据。
- `~$*`、`*.tmp`、`*.part` 等Office或断点临时文件。
- `manifest.csv` 等与 JSONL 或 SQLite 重复的人工查看副本。
- `documents.jsonl`、`documents_with_versions.jsonl` 等一次性导入源。
- `policy_versions.csv`、`policy_version_groups.jsonl` 等数据库重复导出。
- `duplicates.csv`、`upload_batches.csv`、`dlp_scan.csv`、`dlp_summary.json`。
- `local_ocr_report.csv` 等本地处理报告。

清理操作只将文件移动到 `<知识库根目录>/_云端迁移索引/_生产包隔离_日期`，不永久删除。

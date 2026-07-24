#!/usr/bin/env python3
import argparse
import csv
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成知识库物理整理计划，不移动或删除文件")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(args.database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT documents.id AS document_id,
                   documents.source AS current_path,
                   canonical_documents.canonical_document_id,
                   canonical.source AS canonical_path,
                   CASE
                     WHEN documents.id=canonical_documents.canonical_document_id THEN '保留原文件'
                     ELSE '归档精确重复副本'
                   END AS proposed_action,
                   MIN(virtual_catalog_entries.virtual_path) AS preferred_virtual_path
            FROM documents
            JOIN document_duplicates
              ON document_duplicates.document_id=documents.id
            JOIN canonical_documents
              ON canonical_documents.canonical_document_id=document_duplicates.canonical_document_id
            JOIN documents canonical
              ON canonical.id=canonical_documents.canonical_document_id
            LEFT JOIN virtual_catalog_entries
              ON virtual_catalog_entries.document_id=canonical_documents.canonical_document_id
            GROUP BY documents.id,documents.source,canonical_documents.canonical_document_id,
                     canonical.source,proposed_action
            ORDER BY canonical_documents.canonical_document_id,documents.id
            """
        ).fetchall()
    fieldnames = [
        "document_id",
        "current_path",
        "canonical_document_id",
        "canonical_path",
        "proposed_action",
        "preferred_virtual_path",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(dict(row) for row in rows)
    counts = Counter(str(row["proposed_action"]) for row in rows)
    report_path = args.output.with_suffix(".md")
    report_path.write_text(
        "\n".join(
            (
                "# 知识库物理整理迁移计划",
                "",
                f"- 生成时间：{datetime.now().strftime('%Y年%m月%d日%H：%M：%S')}",
                f"- 文档记录：{len(rows)}",
                f"- 保留原文件：{counts['保留原文件']}",
                f"- 待归档精确重复副本：{counts['归档精确重复副本']}",
                "- 当前仅生成迁移计划，未移动、覆盖或删除任何文件。",
                "- 执行物理迁移前必须先完成生产索引切换、OSS同步和检索冒烟。",
                "",
                f"明细：`{args.output}`",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    print(report_path)


if __name__ == "__main__":
    main()

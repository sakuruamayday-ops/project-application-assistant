from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将旧索引中的结构化增强表迁入文档ID一致的新核心索引"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    return parser.parse_args()


def object_definitions(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], str]:
    return {
        (str(name), str(object_type)): str(sql)
        for name, object_type, sql in connection.execute(
            """
            SELECT name,type,sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            """
        )
    }


def document_identity(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        str(source): int(document_id)
        for document_id, source in connection.execute(
            "SELECT id,source FROM documents"
        )
    }


def main() -> None:
    args = parse_args()
    source_path = args.source.expanduser().resolve()
    target_path = args.target.expanduser().resolve()
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        source_identity = document_identity(source)
        target_identity = document_identity(target)
        if source_identity != target_identity:
            missing = sorted(source_identity.keys() - target_identity.keys())
            added = sorted(target_identity.keys() - source_identity.keys())
            id_mismatches = sum(
                source_identity[path] != target_identity[path]
                for path in source_identity.keys() & target_identity.keys()
            )
            raise RuntimeError(
                "文档ID未收敛，禁止迁移结构化表："
                f"missing={len(missing)} added={len(added)} "
                f"id_mismatches={id_mismatches}"
            )

        source_objects = object_definitions(source)
        target_objects = set(object_definitions(target))
        source_only = {
            key: sql
            for key, sql in source_objects.items()
            if key not in target_objects
        }
        tables = sorted(
            (name, sql)
            for (name, object_type), sql in source_only.items()
            if object_type == "table"
        )
        indexes = sorted(
            (name, sql)
            for (name, object_type), sql in source_only.items()
            if object_type == "index"
        )

        target.execute("ATTACH DATABASE ? AS structured_source", (str(source_path),))
        target.execute("PRAGMA foreign_keys=OFF")
        for name, sql in tables:
            target.execute(sql)
            columns = [
                str(row[1])
                for row in source.execute(f'PRAGMA table_info("{name}")')
            ]
            quoted = ",".join(f'"{column}"' for column in columns)
            target.execute(
                f'INSERT INTO "{name}" ({quoted}) '
                f'SELECT {quoted} FROM structured_source."{name}"'
            )
        for _, sql in indexes:
            target.execute(sql)
        target.commit()

        row_counts = {
            name: int(
                target.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            )
            for name, _ in tables
        }
        integrity = str(target.execute("PRAGMA quick_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"SQLite quick_check失败：{integrity}")
        print(
            json.dumps(
                {
                    "copied_tables": len(tables),
                    "copied_indexes": len(indexes),
                    "integrity": integrity,
                    "row_counts": row_counts,
                },
                ensure_ascii=False,
            )
        )
    finally:
        target.close()
        source.close()


if __name__ == "__main__":
    main()

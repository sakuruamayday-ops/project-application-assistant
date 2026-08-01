from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


DOCUMENT_ID_COLUMNS = {
    "document_id",
    "representative_document_id",
    "source_document_id",
    "target_document_id",
    "canonical_document_id",
}
DOCUMENT_ID_LIST_COLUMNS = {
    "document_ids",
    "source_documents_json",
}
CSV_DOCUMENT_ID_COLUMNS = {
    "final_document_ids",
    "public_document_ids",
}
PRESERVED_EXISTING_TABLES = {
    "canonical_list_sources",
}


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


def remap_document_references(
    columns: list[str],
    row: tuple[object, ...],
    id_remap: dict[int, int],
) -> tuple[tuple[object, ...], int]:
    values = list(row)
    remapped = 0
    for position, column in enumerate(columns):
        value = values[position]
        if value is None:
            continue
        if column in DOCUMENT_ID_COLUMNS:
            old_id = int(value)
            if old_id not in id_remap:
                raise RuntimeError(
                    f"结构化表引用的旧文档ID在新索引中不存在："
                    f"column={column} document_id={old_id}"
                )
            values[position] = id_remap[old_id]
            remapped += int(id_remap[old_id] != old_id)
        elif column in DOCUMENT_ID_LIST_COLUMNS:
            document_ids = json.loads(str(value))
            if not isinstance(document_ids, list):
                raise RuntimeError(f"{column} 必须是JSON数组")
            mapped_ids: list[object] = []
            for item in document_ids:
                if not isinstance(item, int):
                    mapped_ids.append(item)
                    continue
                if item not in id_remap:
                    raise RuntimeError(
                        f"结构化表引用的旧文档ID在新索引中不存在："
                        f"column={column} document_id={item}"
                    )
                mapped_ids.append(id_remap[item])
                remapped += int(id_remap[item] != item)
            values[position] = json.dumps(mapped_ids, ensure_ascii=False)
        elif column in CSV_DOCUMENT_ID_COLUMNS:
            document_ids = [
                int(item)
                for item in str(value).split(",")
                if item.strip()
            ]
            mapped_ids = []
            for item in document_ids:
                if item not in id_remap:
                    raise RuntimeError(
                        f"结构化表引用的旧文档ID在新索引中不存在："
                        f"column={column} document_id={item}"
                    )
                mapped_ids.append(id_remap[item])
                remapped += int(id_remap[item] != item)
            values[position] = ",".join(str(item) for item in mapped_ids)
    return tuple(values), remapped


def main() -> None:
    args = parse_args()
    source_path = args.source.expanduser().resolve()
    target_path = args.target.expanduser().resolve()
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        source_identity = document_identity(source)
        target_identity = document_identity(target)
        id_remap = {
            source_id: target_identity[path]
            for path, source_id in source_identity.items()
            if path in target_identity
        }
        missing = sorted(source_identity.keys() - target_identity.keys())
        added = sorted(target_identity.keys() - source_identity.keys())
        id_mismatches = sum(
            source_identity[path] != target_identity[path]
            for path in source_identity.keys() & target_identity.keys()
        )

        source_objects = object_definitions(source)
        target_objects = set(object_definitions(target))
        source_only = {
            key: sql
            for key, sql in source_objects.items()
            if key not in target_objects
            or (
                key[1] == "table"
                and key[0] in PRESERVED_EXISTING_TABLES
            )
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
        remapped_document_references = 0
        for name, sql in tables:
            if (name, "table") in target_objects:
                target.execute(f'DELETE FROM "{name}"')
            else:
                target.execute(sql)
            columns = [
                str(row[1])
                for row in source.execute(f'PRAGMA table_info("{name}")')
            ]
            quoted = ",".join(f'"{column}"' for column in columns)
            if (
                set(columns) & DOCUMENT_ID_COLUMNS
                or set(columns) & DOCUMENT_ID_LIST_COLUMNS
                or set(columns) & CSV_DOCUMENT_ID_COLUMNS
            ):
                transformed_rows = []
                for row in source.execute(f'SELECT {quoted} FROM "{name}"'):
                    transformed, count = remap_document_references(
                        columns,
                        tuple(row),
                        id_remap,
                    )
                    transformed_rows.append(transformed)
                    remapped_document_references += count
                placeholders = ",".join("?" for _ in columns)
                target.executemany(
                    f'INSERT INTO "{name}" ({quoted}) VALUES ({placeholders})',
                    transformed_rows,
                )
            else:
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
                    "document_identity": {
                        "source_documents": len(source_identity),
                        "target_documents": len(target_identity),
                        "missing_sources": len(missing),
                        "added_sources": len(added),
                        "id_mismatches": id_mismatches,
                        "remapped_references": remapped_document_references,
                    },
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

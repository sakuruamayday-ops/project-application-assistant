#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

try:
    from scripts.build_knowledge_content_index import (
        YEAR_PATTERN,
        enterprise_mentions,
        structured_small_giant_entities,
    )
except ModuleNotFoundError:
    from build_knowledge_content_index import (
        YEAR_PATTERN,
        enterprise_mentions,
        structured_small_giant_entities,
    )


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按当前解析规则原位重建名单文档的企业实体，不触碰全文和非名单文档"
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--allow-shrink",
        action="store_true",
        help="显式允许重建后的名单记录数少于重建前；默认保护已有结构化提取结果",
    )
    return parser.parse_args()


def rebuild(database: Path, *, allow_shrink: bool = False) -> dict[str, int]:
    connection = sqlite3.connect(database)
    try:
        original_public_list_entities = connection.execute(
            "SELECT COUNT(*) FROM public_list_entities"
        ).fetchone()[0]
        documents = connection.execute(
            """
            SELECT id,content,canonical_project_name,policy_year,batch,region,document_stage
            FROM documents
            WHERE document_role='50_名单与对标'
            ORDER BY id
            """
        ).fetchall()
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_list_entity_years'"
        ).fetchone():
            connection.execute("DELETE FROM public_list_entity_years")
        connection.execute("DELETE FROM public_list_entities")
        connection.execute(
            """
            DELETE FROM enterprise_mentions
            WHERE document_id IN (
                SELECT id FROM documents WHERE document_role='50_名单与对标'
            )
            """
        )
        mention_rows: list[tuple[int, str, str, str]] = []
        entity_rows: list[tuple[object, ...]] = []
        for document_id, content, project_name, policy_year, batch, region, stage in documents:
            structured = structured_small_giant_entities(str(content))
            if structured:
                for entity in structured:
                    mention_rows.append(
                        (int(document_id), str(entity[0]), str(entity[1]), str(entity[7]))
                    )
                    entity_rows.append((int(document_id), *entity))
                continue
            for name, sequence, context in enterprise_mentions(str(content)):
                mention_rows.append((int(document_id), name, sequence, context))
                confidence = "high" if project_name and stage != "其他" else "medium"
                entity_rows.append(
                    (
                        int(document_id),
                        name,
                        sequence,
                        str(project_name or ""),
                        policy_year,
                        str(batch or ""),
                        str(region or ""),
                        str(stage or ""),
                        context,
                        confidence,
                    )
                )
        connection.executemany(
            """
            INSERT OR IGNORE INTO enterprise_mentions(
                document_id,enterprise_name,sequence_no,context
            ) VALUES(?,?,?,?)
            """,
            mention_rows,
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO public_list_entities(
                document_id,enterprise_name,sequence_no,canonical_project_name,
                policy_year,batch,region,list_status,context,confidence
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            entity_rows,
        )
        rebuilt_public_list_entities = connection.execute(
            "SELECT COUNT(*) FROM public_list_entities"
        ).fetchone()[0]
        if (
            rebuilt_public_list_entities < original_public_list_entities
            and not allow_shrink
        ):
            raise RuntimeError(
                "refusing to shrink public_list_entities without --allow-shrink: "
                f"{original_public_list_entities} -> {rebuilt_public_list_entities}"
            )
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_list_entity_years'"
        ).fetchone():
            year_rows: list[tuple[int, int, str]] = []
            for entity_id, entity_year, context, confidence in connection.execute(
                "SELECT id,policy_year,context,confidence FROM public_list_entities"
            ):
                years = {int(year) for year in YEAR_PATTERN.findall(str(context or ""))}
                if entity_year:
                    years.add(int(entity_year))
                role = "platform_record" if confidence == "medium" else "official_document_year"
                year_rows.extend((int(entity_id), year, role) for year in sorted(years))
            connection.executemany(
                """
                INSERT OR IGNORE INTO public_list_entity_years(entity_id,year,year_role)
                VALUES(?,?,?)
                """,
                year_rows,
            )
        connection.commit()
        return {
            "documents": len(documents),
            "enterprise_mentions": connection.execute(
                """
                SELECT COUNT(*) FROM enterprise_mentions
                WHERE document_id IN (
                    SELECT id FROM documents WHERE document_role='50_名单与对标'
                )
                """
            ).fetchone()[0],
            "public_list_entities": connection.execute(
                "SELECT COUNT(*) FROM public_list_entities"
            ).fetchone()[0],
            "previous_public_list_entities": original_public_list_entities,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            rebuild(args.database, allow_shrink=args.allow_shrink),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

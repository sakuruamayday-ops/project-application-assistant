from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import re
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.build_knowledge_content_index import iter_chunks, structured_small_giant_entities
except ModuleNotFoundError:
    from build_knowledge_content_index import iter_chunks, structured_small_giant_entities


SOURCE_KEY = "qice-project-98-small-giant-history"
TITLE = "企策顾问国家专精特新“小巨人”企业历史获批结构化索引"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入企策顾问国家小巨人历史获批结构化数据")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source",
        default="50_名单与对标/优质中小企业梯度培育/企策顾问动态索引/国家专精特新小巨人历史获批.json",
    )
    return parser.parse_args()


def summary_text(payload: dict[str, object], entities: list[tuple[object, ...]]) -> str:
    year_counts: Counter[str] = Counter()
    for record in payload.get("records", []):
        if not isinstance(record, dict):
            continue
        year_counts.update(set(re.findall(r"20\d{2}", str(record.get("subsidyYear") or ""))))
    province_counts = Counter(
        str(record.get("province") or "待核验")
        for record in payload.get("records", [])
        if isinstance(record, dict)
    )
    lines = [
        f"# {TITLE}",
        f"- 采集时间：{payload.get('capturedAt') or ''}",
        f"- 原始平台记录：{len(payload.get('records', []))}",
        f"- 结构化企业记录：{len(entities)}",
        f"- 无企业名称未结构化：{max(0, len(payload.get('records', [])) - len(entities))}",
        "- 数据性质：企策顾问动态发现与比对索引，不替代工信部及地方主管部门官方名单。",
        "- 年份口径：平台年份仅用于检索关联，可能同时包含认定、复核或后续批次，不据此推定首次认定年份。",
        "## 平台年份关联分布",
    ]
    lines.extend(f"- {year}：{count}" for year, count in sorted(year_counts.items()))
    lines.append("## 登记省份分布")
    lines.extend(f"- {region}：{count}" for region, count in sorted(province_counts.items()))
    return "\n".join(lines)


def replace_document_fts(
    connection: sqlite3.Connection,
    table: str,
    document_id: int,
    old_values: tuple[str, str, str, str] | None,
    new_values: tuple[str, str, str, str],
) -> None:
    if old_values is not None:
        connection.execute(
            f"INSERT INTO {table}({table},rowid,title,content,source,document_role) "
            "VALUES('delete',?,?,?,?,?)",
            (document_id, *old_values),
        )
    connection.execute(
        f"INSERT INTO {table}(rowid,title,content,source,document_role) VALUES (?,?,?,?,?)",
        (document_id, *new_values),
    )


def import_dataset(database: Path, dataset: Path, output: Path, source: str) -> dict[str, object]:
    if not database.is_file():
        raise FileNotFoundError(database)
    if not dataset.is_file():
        raise FileNotFoundError(dataset)
    if output.exists():
        raise FileExistsError(output)
    raw = dataset.read_text(encoding="utf-8")
    payload = json.loads(raw)
    entities = structured_small_giant_entities(raw)
    if not entities:
        raise ValueError("未识别到企策顾问国家小巨人结构化记录")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    content = summary_text(payload, entities)
    updated_at = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    shutil.copy2(database, temporary)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS public_list_entity_years (
                    id INTEGER PRIMARY KEY,
                    entity_id INTEGER NOT NULL REFERENCES public_list_entities(id) ON DELETE CASCADE,
                    year INTEGER NOT NULL,
                    year_role TEXT NOT NULL,
                    UNIQUE(entity_id, year)
                );
                CREATE INDEX IF NOT EXISTS public_list_entity_years_year_idx
                    ON public_list_entity_years(year, entity_id);
                """
            )
            existing = connection.execute(
                "SELECT id,title,content,source,document_role FROM documents WHERE source_key=?",
                (SOURCE_KEY,),
            ).fetchone()
            old_fts = tuple(str(value) for value in existing[1:]) if existing else None
            if existing:
                document_id = int(existing[0])
                connection.execute(
                    """
                    UPDATE documents
                    SET title=?,content=?,source=?,cloud_path=?,document_role=?,sensitivity=?,
                        sha256=?,updated_at=?,canonical_project_name=?,region=?,document_stage=?,
                        validity_status=?,policy_year=NULL,batch='',replacement_title='',
                        replacement_basis='',replacement_url=''
                    WHERE id=?
                    """,
                    (
                        TITLE,
                        content,
                        source,
                        source,
                        "50_名单与对标",
                        "internal",
                        digest,
                        updated_at,
                        "国家专精特新“小巨人”企业",
                        "全国",
                        "认定名单",
                        "active_candidate",
                        document_id,
                    ),
                )
                connection.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
                connection.execute("DELETE FROM document_chunks_fts WHERE document_id=?", (document_id,))
                connection.execute("DELETE FROM enterprise_mentions WHERE document_id=?", (document_id,))
                connection.execute("DELETE FROM public_list_entities WHERE document_id=?", (document_id,))
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO documents(
                        source_key,title,content,source,cloud_path,document_role,sensitivity,
                        sha256,updated_at,canonical_project_name,region,document_stage,
                        validity_status,policy_year,batch,replacement_title,replacement_basis,
                        replacement_url
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,'','','','')
                    """,
                    (
                        SOURCE_KEY,
                        TITLE,
                        content,
                        source,
                        source,
                        "50_名单与对标",
                        "internal",
                        digest,
                        updated_at,
                        "国家专精特新“小巨人”企业",
                        "全国",
                        "认定名单",
                        "active_candidate",
                    ),
                )
                document_id = int(cursor.lastrowid)
            new_fts = (TITLE, content, source, "50_名单与对标")
            replace_document_fts(connection, "documents_fts", document_id, old_fts, new_fts)
            replace_document_fts(connection, "documents_fts_trigram", document_id, old_fts, new_fts)
            for chunk_number, chunk in iter_chunks(content):
                connection.execute(
                    "INSERT INTO document_chunks(document_id,chunk_number,content) VALUES (?,?,?)",
                    (document_id, chunk_number, chunk),
                )
                connection.execute(
                    "INSERT INTO document_chunks_fts(document_id,chunk_number,title,content,source) VALUES (?,?,?,?,?)",
                    (document_id, chunk_number, TITLE, chunk, source),
                )
            connection.executemany(
                "INSERT INTO enterprise_mentions(document_id,enterprise_name,sequence_no,context) VALUES (?,?,?,?)",
                ((document_id, entity[0], entity[1], entity[7]) for entity in entities),
            )
            connection.executemany(
                """
                INSERT INTO public_list_entities(
                    document_id,enterprise_name,sequence_no,canonical_project_name,
                    policy_year,batch,region,list_status,context,confidence
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                ((document_id, *entity) for entity in entities),
            )
            entity_year_rows: list[tuple[int, int, str]] = []
            for entity_id, context in connection.execute(
                "SELECT id,context FROM public_list_entities WHERE document_id=?",
                (document_id,),
            ):
                years = sorted({int(year) for year in re.findall(r"20\d{2}", str(context))})
                entity_year_rows.extend(
                    (int(entity_id), year, "platform_record") for year in years
                )
            connection.executemany(
                "INSERT INTO public_list_entity_years(entity_id,year,year_role) VALUES (?,?,?)",
                entity_year_rows,
            )
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise RuntimeError(f"索引完整性检查失败：{integrity}")
            connection.commit()
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            failed_directory = output.parent / "failed-imports"
            failed_directory.mkdir(parents=True, exist_ok=True)
            temporary.replace(
                failed_directory
                / f"{temporary.name}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            )
    return {
        "document_id": document_id,
        "records": len(entities),
        "sha256": digest,
        "integrity": "ok",
        "output": str(output),
    }


def main() -> None:
    args = parse_args()
    result = import_dataset(
        args.database.expanduser().resolve(),
        args.dataset.expanduser().resolve(),
        args.output.expanduser().resolve(),
        args.source,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

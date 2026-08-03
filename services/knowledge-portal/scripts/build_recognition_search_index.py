#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Iterable


DEFAULT_TAXONOMY = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "recognized-subject-taxonomy.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从现有权威名单与知识证据构建统一认定反向检索索引"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    return parser.parse_args()


def stable_id(*values: object) -> str:
    payload = "\x1f".join(str(value or "") for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_enterprise(value: object) -> str:
    return re.sub(r"[\s·•・,，。;；:：()（）【】\[\]\"“”'‘’]+", "", str(value or "")).lower()


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def table_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, object]]:
    if not table_exists(connection, table):
        return []
    return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]


def load_taxonomy(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    subjects = payload.get("subjects", []) if isinstance(payload, dict) else []
    return [dict(item) for item in subjects if isinstance(item, dict)]


def canonical_matches(
    text: object,
    taxonomy: list[dict[str, object]],
) -> list[tuple[str, str, str]]:
    haystack = str(text or "")
    matches: list[tuple[str, str, str]] = []
    for subject in taxonomy:
        canonical = str(subject.get("canonical_subject") or "")
        for level, field in (("exact", "exact_terms"), ("related", "related_terms")):
            terms = subject.get(field, [])
            if not isinstance(terms, list):
                continue
            for term in (str(value).strip() for value in terms):
                if term and term in haystack:
                    matches.append((canonical, term, level))
    return list(dict.fromkeys(matches))


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS subject_taxonomy;
        DROP TABLE IF EXISTS recognition_records;
        DROP TABLE IF EXISTS enterprise_subject_evidence;
        CREATE TABLE subject_taxonomy(
            canonical_subject TEXT PRIMARY KEY,
            exact_terms_json TEXT NOT NULL,
            related_terms_json TEXT NOT NULL,
            excluded_terms_json TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE recognition_records(
            record_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            enterprise_id TEXT NOT NULL,
            enterprise_name_at_recognition TEXT NOT NULL,
            product_name TEXT NOT NULL DEFAULT '',
            product_category TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL DEFAULT '',
            province TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            county TEXT NOT NULL DEFAULT '',
            year INTEGER,
            batch TEXT NOT NULL DEFAULT '',
            recognition_status TEXT NOT NULL DEFAULT '',
            recognition_level TEXT NOT NULL DEFAULT '',
            source_document_id INTEGER,
            source_title TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            source_grade TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL DEFAULT '',
            source_table TEXT NOT NULL,
            source_row_id TEXT NOT NULL
        );
        CREATE INDEX recognition_records_project_idx
            ON recognition_records(project_id,project_name,year,region,recognition_status);
        CREATE INDEX recognition_records_enterprise_idx
            ON recognition_records(enterprise_id,enterprise_name_at_recognition);
        CREATE TABLE enterprise_subject_evidence(
            evidence_id TEXT PRIMARY KEY,
            enterprise_id TEXT NOT NULL,
            enterprise_name TEXT NOT NULL,
            canonical_subject TEXT NOT NULL,
            raw_subject TEXT NOT NULL,
            match_level TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            evidence_excerpt TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            source_document_id INTEGER,
            verification_status TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_row_id TEXT NOT NULL
        );
        CREATE INDEX enterprise_subject_evidence_subject_idx
            ON enterprise_subject_evidence(canonical_subject,raw_subject,match_level);
        CREATE INDEX enterprise_subject_evidence_enterprise_idx
            ON enterprise_subject_evidence(enterprise_id,enterprise_name);
        """
    )


def insert_taxonomy(
    connection: sqlite3.Connection,
    taxonomy: list[dict[str, object]],
) -> None:
    connection.executemany(
        """
        INSERT INTO subject_taxonomy(
            canonical_subject,exact_terms_json,related_terms_json,excluded_terms_json,notes
        ) VALUES(?,?,?,?,?)
        """,
        (
            (
                str(item.get("canonical_subject") or ""),
                json.dumps(item.get("exact_terms", []), ensure_ascii=False),
                json.dumps(item.get("related_terms", []), ensure_ascii=False),
                json.dumps(item.get("excluded_terms", []), ensure_ascii=False),
                str(item.get("notes") or ""),
            )
            for item in taxonomy
            if str(item.get("canonical_subject") or "")
        ),
    )


def insert_recognition_record(
    connection: sqlite3.Connection,
    *,
    source_table: str,
    source_row_id: object,
    project_id: object,
    project_name: object,
    enterprise_name: object,
    product_name: object = "",
    product_category: object = "",
    region: object = "",
    province: object = "",
    city: object = "",
    county: object = "",
    year: object = None,
    batch: object = "",
    recognition_status: object = "",
    recognition_level: object = "",
    source_document_id: object = None,
    source_title: object = "",
    source_url: object = "",
    source_grade: object = "",
    verification_status: object = "",
) -> None:
    normalized_name = normalize_enterprise(enterprise_name)
    if not normalized_name:
        return
    record_id = stable_id(source_table, source_row_id)
    connection.execute(
        """
        INSERT OR REPLACE INTO recognition_records(
            record_id,project_id,project_name,enterprise_id,enterprise_name_at_recognition,
            product_name,product_category,region,province,city,county,year,batch,
            recognition_status,recognition_level,source_document_id,source_title,source_url,
            source_grade,verification_status,source_table,source_row_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            record_id,
            str(project_id or ""),
            str(project_name or ""),
            normalized_name,
            str(enterprise_name or ""),
            str(product_name or ""),
            str(product_category or ""),
            str(region or province or city or county or ""),
            str(province or ""),
            str(city or ""),
            str(county or ""),
            int(year) if year not in (None, "") else None,
            str(batch or ""),
            str(recognition_status or ""),
            str(recognition_level or ""),
            int(source_document_id) if source_document_id not in (None, "") else None,
            str(source_title or ""),
            str(source_url or ""),
            str(source_grade or ""),
            str(verification_status or ""),
            source_table,
            str(source_row_id or ""),
        ),
    )


def insert_subject_evidence(
    connection: sqlite3.Connection,
    taxonomy: list[dict[str, object]],
    *,
    source_table: str,
    source_row_id: object,
    enterprise_name: object,
    raw_texts: Iterable[object],
    evidence_type: str,
    evidence_excerpt: object = "",
    source_url: object = "",
    source_document_id: object = None,
    verification_status: str,
) -> None:
    normalized_name = normalize_enterprise(enterprise_name)
    if not normalized_name:
        return
    seen: set[tuple[str, str, str]] = set()
    for raw_text in raw_texts:
        raw_subject = str(raw_text or "").strip()
        if not raw_subject:
            continue
        matches = canonical_matches(raw_subject, taxonomy)
        if not matches and source_table == "three_first_project_awards":
            matches = [(raw_subject, raw_subject, "exact")]
        for canonical, matched_term, level in matches:
            key = (canonical, matched_term, level)
            if key in seen:
                continue
            seen.add(key)
            evidence_id = stable_id(
                source_table,
                source_row_id,
                normalized_name,
                canonical,
                matched_term,
                level,
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO enterprise_subject_evidence(
                    evidence_id,enterprise_id,enterprise_name,canonical_subject,raw_subject,
                    match_level,evidence_type,evidence_excerpt,source_url,source_document_id,
                    verification_status,source_table,source_row_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    evidence_id,
                    normalized_name,
                    str(enterprise_name or ""),
                    canonical,
                    raw_subject,
                    level,
                    evidence_type,
                    str(evidence_excerpt or "")[:2000],
                    str(source_url or ""),
                    int(source_document_id) if source_document_id not in (None, "") else None,
                    verification_status,
                    source_table,
                    str(source_row_id or ""),
                ),
            )


def build_index(
    connection: sqlite3.Connection,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
) -> dict[str, int]:
    connection.row_factory = sqlite3.Row
    taxonomy = load_taxonomy(taxonomy_path)
    ensure_schema(connection)
    insert_taxonomy(connection, taxonomy)

    for row in table_rows(connection, "three_first_project_awards"):
        row_id = row.get("id") or stable_id(*row.values())
        insert_recognition_record(
            connection,
            source_table="three_first_project_awards",
            source_row_id=row_id,
            project_id=row.get("project_id"),
            project_name=row.get("project_name"),
            enterprise_name=row.get("enterprise_name"),
            product_name=row.get("product_name"),
            product_category=row.get("product_category"),
            region=row.get("province") or row.get("city") or row.get("county"),
            province=row.get("province"),
            city=row.get("city"),
            county=row.get("county"),
            year=row.get("year"),
            recognition_status=row.get("list_status"),
            recognition_level=row.get("recognition_tier"),
            source_title=row.get("source_title"),
            source_url=row.get("source_url"),
            source_grade=row.get("source_tier"),
            verification_status=row.get("confidence"),
        )
        insert_subject_evidence(
            connection,
            taxonomy,
            source_table="three_first_project_awards",
            source_row_id=row_id,
            enterprise_name=row.get("enterprise_name"),
            raw_texts=(row.get("product_name"), row.get("industry")),
            evidence_type="official_recognition_product",
            evidence_excerpt=row.get("source_title"),
            source_url=row.get("source_url"),
            verification_status=str(row.get("confidence") or "verified"),
        )

    for row in table_rows(connection, "national_small_giant_master"):
        row_id = row.get("id") or stable_id(*row.values())
        insert_recognition_record(
            connection,
            source_table="national_small_giant_master",
            source_row_id=row_id,
            project_id="national_small_giant",
            project_name="国家专精特新“小巨人”企业",
            enterprise_name=row.get("enterprise_name"),
            region=row.get("region"),
            province=row.get("region"),
            city=row.get("city"),
            county=row.get("county"),
            year=row.get("recognition_year"),
            batch=row.get("batch"),
            recognition_status=row.get("status"),
            recognition_level="国家级",
            source_url=row.get("official_url"),
            source_grade=row.get("official_url_role"),
            verification_status=row.get("verification_status"),
        )

    for row in table_rows(connection, "enterprise_recognition_events"):
        row_id = row.get("id") or row.get("event_uid") or stable_id(*row.values())
        source_urls = []
        try:
            source_urls = json.loads(str(row.get("source_urls_json") or "[]"))
        except json.JSONDecodeError:
            pass
        insert_recognition_record(
            connection,
            source_table="enterprise_recognition_events",
            source_row_id=row_id,
            project_id=row.get("lifecycle_rule_id") or row.get("project_name"),
            project_name=row.get("project_name"),
            enterprise_name=row.get("enterprise_name_at_event"),
            product_name=row.get("product_name"),
            region=row.get("recognition_province") or row.get("recognition_city"),
            province=row.get("recognition_province"),
            city=row.get("recognition_city"),
            county=row.get("recognition_county"),
            year=row.get("recognition_year") or row.get("event_year"),
            batch=row.get("batch"),
            recognition_status=row.get("status") or row.get("event_type"),
            recognition_level=row.get("event_scope"),
            source_title=row.get("source_title"),
            source_url=source_urls[0] if isinstance(source_urls, list) and source_urls else "",
            source_grade=row.get("source_kinds_json"),
            verification_status=row.get("evidence_status"),
        )

    if table_exists(connection, "enterprise_mentions") and table_exists(connection, "documents"):
        rows = connection.execute(
            """
            SELECT em.id,em.enterprise_name,em.context,em.document_id,d.title,d.source
            FROM enterprise_mentions em JOIN documents d ON d.id=em.document_id
            """
        ).fetchall()
        for raw_row in rows:
            row = dict(raw_row)
            insert_subject_evidence(
                connection,
                taxonomy,
                source_table="enterprise_mentions",
                source_row_id=row["id"],
                enterprise_name=row["enterprise_name"],
                raw_texts=(row["context"], row["title"]),
                evidence_type="knowledge_document_mention",
                evidence_excerpt=row["context"],
                source_url=row["source"],
                source_document_id=row["document_id"],
                verification_status="candidate",
            )

    for row in table_rows(connection, "case_packs"):
        insert_subject_evidence(
            connection,
            taxonomy,
            source_table="case_packs",
            source_row_id=row.get("case_pack_id"),
            enterprise_name=row.get("enterprise_name"),
            raw_texts=(row.get("industry"), row.get("title")),
            evidence_type="case_pack_metadata",
            evidence_excerpt=row.get("title"),
            source_url=row.get("source_root"),
            verification_status=str(row.get("verification_status") or "candidate"),
        )

    connection.commit()
    counts = {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in (
            "subject_taxonomy",
            "recognition_records",
            "enterprise_subject_evidence",
        )
    }
    integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
    if integrity != "ok":
        raise RuntimeError(f"统一认定索引完整性检查失败：{integrity}")
    return counts


def main() -> None:
    args = parse_args()
    database = args.database.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database)
    try:
        counts = build_index(connection, args.taxonomy)
    finally:
        connection.close()
    print(json.dumps({"database": str(database), "tables": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()

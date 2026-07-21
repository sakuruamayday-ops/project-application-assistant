from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

try:
    from scripts.build_knowledge_content_index import (
        DEFAULT_PROJECT_INDEX,
        ensure_policy_cluster_schema,
        infer_document_metadata,
        insert_metadata_audit_records,
        load_project_catalog,
        rebuild_policy_document_clusters,
    )
except ModuleNotFoundError:
    from build_knowledge_content_index import (
        DEFAULT_PROJECT_INDEX,
        ensure_policy_cluster_schema,
        infer_document_metadata,
        insert_metadata_audit_records,
        load_project_catalog,
        rebuild_policy_document_clusters,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在不重新提取全文的前提下生成结构化名单与政策元数据索引"
    )
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-index", type=Path, default=DEFAULT_PROJECT_INDEX)
    return parser.parse_args()


def ensure_schema(connection: sqlite3.Connection) -> None:
    existing_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(documents)")
    }
    columns = {
        "canonical_project_name": "TEXT NOT NULL DEFAULT ''",
        "region": "TEXT NOT NULL DEFAULT ''",
        "document_stage": "TEXT NOT NULL DEFAULT '其他'",
        "validity_status": "TEXT NOT NULL DEFAULT 'active_candidate'",
        "policy_year": "INTEGER",
        "batch": "TEXT NOT NULL DEFAULT ''",
        "replacement_title": "TEXT NOT NULL DEFAULT ''",
        "replacement_basis": "TEXT NOT NULL DEFAULT ''",
        "replacement_url": "TEXT NOT NULL DEFAULT ''",
    }
    for name, declaration in columns.items():
        if name not in existing_columns:
            connection.execute(f"ALTER TABLE documents ADD COLUMN {name} {declaration}")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS public_list_entities (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            enterprise_name TEXT NOT NULL,
            sequence_no TEXT NOT NULL,
            canonical_project_name TEXT NOT NULL,
            policy_year INTEGER,
            batch TEXT NOT NULL,
            region TEXT NOT NULL,
            list_status TEXT NOT NULL,
            context TEXT NOT NULL,
            confidence TEXT NOT NULL,
            UNIQUE(document_id, enterprise_name, sequence_no)
        );
        CREATE INDEX IF NOT EXISTS public_list_entities_name_idx
            ON public_list_entities(enterprise_name);
        CREATE INDEX IF NOT EXISTS public_list_entities_project_idx
            ON public_list_entities(canonical_project_name, policy_year, region);
        CREATE INDEX IF NOT EXISTS documents_policy_metadata_idx
            ON documents(canonical_project_name, region, document_stage, validity_status);
        CREATE TABLE IF NOT EXISTS project_alias_corrections (
            id INTEGER PRIMARY KEY,
            raw_project_name TEXT NOT NULL,
            canonical_project_name TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT '',
            start_year INTEGER,
            end_year INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            confirmed_by TEXT NOT NULL DEFAULT '',
            confirmed_at TEXT,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(raw_project_name,canonical_project_name,region,start_year,end_year)
        );
        CREATE INDEX IF NOT EXISTS project_alias_corrections_lookup_idx
            ON project_alias_corrections(raw_project_name,status,region);
        CREATE UNIQUE INDEX IF NOT EXISTS project_alias_corrections_scope_idx
            ON project_alias_corrections(
                raw_project_name,canonical_project_name,region,
                COALESCE(start_year,0),COALESCE(end_year,9999)
            );
        CREATE TABLE IF NOT EXISTS metadata_match_evidence (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            field_name TEXT NOT NULL,
            inferred_value TEXT NOT NULL,
            matched_term TEXT NOT NULL,
            match_method TEXT NOT NULL,
            source_scope TEXT NOT NULL,
            source_excerpt TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            confidence TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'unreviewed',
            correction_id INTEGER REFERENCES project_alias_corrections(id),
            created_at TEXT NOT NULL,
            UNIQUE(document_id,field_name,rule_version)
        );
        CREATE INDEX IF NOT EXISTS metadata_match_evidence_review_idx
            ON metadata_match_evidence(review_status,confidence,field_name);
        CREATE TABLE IF NOT EXISTS policy_verification_queue (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            reason TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            official_source_url TEXT NOT NULL DEFAULT '',
            official_document_title TEXT NOT NULL DEFAULT '',
            official_published_at TEXT,
            verification_note TEXT NOT NULL DEFAULT '',
            verified_by TEXT NOT NULL DEFAULT '',
            verified_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(document_id,reason)
        );
        CREATE INDEX IF NOT EXISTS policy_verification_queue_status_idx
            ON policy_verification_queue(status,priority,document_id);
        """
    )
    ensure_policy_cluster_schema(connection)


def upgrade_database(
    source: Path,
    output: Path,
    project_index: Path = DEFAULT_PROJECT_INDEX,
) -> dict[str, object]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == output:
        raise ValueError("输出路径必须与原索引不同，避免覆盖现有生产索引")
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog = load_project_catalog(project_index.expanduser().resolve())

    with tempfile.TemporaryDirectory(prefix="jiaotang-structured-index-") as directory:
        temporary = Path(directory) / output.name
        shutil.copy2(source, temporary)
        connection = sqlite3.connect(temporary)
        connection.row_factory = sqlite3.Row
        try:
            ensure_schema(connection)
            documents = connection.execute(
                "SELECT id,title,content,source,document_role FROM documents ORDER BY id"
            ).fetchall()
            corrections = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM project_alias_corrections WHERE status='confirmed'"
                ).fetchall()
            ]
            connection.execute("DELETE FROM public_list_entities")
            connection.execute(
                """
                DELETE FROM metadata_match_evidence
                WHERE match_method NOT IN ('official_manual_review','official_cluster_propagation')
                """
            )
            connection.execute("DELETE FROM policy_verification_queue WHERE status='pending'")
            structured_documents = 0
            for row in documents:
                metadata = infer_document_metadata(
                    str(row["title"]),
                    str(row["source"]),
                    str(row["content"]),
                    str(row["document_role"]),
                    catalog,
                    corrections,
                )
                connection.execute(
                    """
                    UPDATE documents
                    SET canonical_project_name=?,region=?,document_stage=?,
                        validity_status=?,policy_year=?,batch=?,replacement_title=?,
                        replacement_basis=?,replacement_url=?
                    WHERE id=?
                    """,
                    (
                        metadata["canonical_project_name"],
                        metadata["region"],
                        metadata["document_stage"],
                        metadata["validity_status"],
                        metadata["policy_year"],
                        metadata["batch"],
                        metadata["replacement_title"],
                        metadata["replacement_basis"],
                        metadata["replacement_url"],
                        int(row["id"]),
                    ),
                )
                if any(
                    (
                        metadata["canonical_project_name"],
                        metadata["region"],
                        metadata["document_stage"] != "其他",
                        metadata["policy_year"],
                    )
                ):
                    structured_documents += 1
                if row["document_role"] != "50_名单与对标":
                    insert_metadata_audit_records(
                        connection,
                        int(row["id"]),
                        str(row["document_role"]),
                        metadata,
                    )
                    continue
                confidence = (
                    "high"
                    if metadata["canonical_project_name"]
                    and metadata["document_stage"] != "其他"
                    else "medium"
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO public_list_entities(
                        document_id,enterprise_name,sequence_no,canonical_project_name,
                        policy_year,batch,region,list_status,context,confidence
                    )
                    SELECT document_id,enterprise_name,sequence_no,?,?,?,?,?,context,?
                    FROM enterprise_mentions WHERE document_id=?
                    """,
                    (
                        metadata["canonical_project_name"],
                        metadata["policy_year"],
                        metadata["batch"],
                        metadata["region"],
                        metadata["document_stage"],
                        confidence,
                        int(row["id"]),
                    ),
                )
                insert_metadata_audit_records(
                    connection,
                    int(row["id"]),
                    str(row["document_role"]),
                    metadata,
                )
            cluster_stats = rebuild_policy_document_clusters(connection)
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise RuntimeError(f"结构化索引完整性检查失败：{integrity}")
            list_entities = int(
                connection.execute("SELECT COUNT(*) FROM public_list_entities").fetchone()[0]
            )
            evidence_records = int(
                connection.execute("SELECT COUNT(*) FROM metadata_match_evidence").fetchone()[0]
            )
            verification_queue = int(
                connection.execute("SELECT COUNT(*) FROM policy_verification_queue").fetchone()[0]
            )
            connection.commit()
        finally:
            connection.close()
        shutil.copy2(temporary, output)

    return {
        "source": str(source),
        "output": str(output),
        "documents": len(documents),
        "structured_documents": structured_documents,
        "public_list_entities": list_entities,
        "metadata_match_evidence": evidence_records,
        "policy_verification_queue": verification_queue,
        "policy_document_clusters": cluster_stats["clusters"],
        "duplicate_policy_clusters": cluster_stats["duplicate_clusters"],
        "duplicate_policy_documents": cluster_stats["duplicate_documents"],
        "integrity": "ok",
    }


def main() -> None:
    args = parse_args()
    result = upgrade_database(args.database, args.output, args.project_index)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

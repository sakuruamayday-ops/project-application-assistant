#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path


DEFAULT_DB = Path(
    "/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3"
)

REQUIRED_TABLES = {
    "list_coverage_matrix": 384,
    "list_entity_reconciliation": 1,
    "national_small_giant_master": 1,
    "national_small_giant_batch_coverage": 7,
    "national_small_giant_platform_year_claims": 1,
    "enterprise_recognition_events": 1,
    "enterprise_lifecycle_source_audits": 1,
    "enterprise_regional_coverage_audits": 3,
    "enterprise_unified_digital_identities": 1,
    "enterprise_peer_comparison_terms": 1,
    "enterprise_unified_identity_coverage": 3,
    "enterprise_profile_enrichment_queue": 0,
    "three_first_project_awards": 1,
    "three_first_status_timeline": 1,
    "three_first_guidance_directory_entries": 1,
    "three_first_guidance_directory_diffs": 1,
    "three_first_award_directory_links": 1,
    "enterprise_product_graph_nodes": 1,
    "enterprise_product_graph_edges": 1,
    "subject_taxonomy": 3,
    "recognition_records": 1,
    "enterprise_subject_evidence": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验生产知识库派生专表完整性")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    return parser.parse_args()


def verify(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = sorted(set(REQUIRED_TABLES) - existing)
        if missing:
            raise RuntimeError("缺少结构化专表：" + "、".join(missing))

        counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in REQUIRED_TABLES
        }
    finally:
        connection.close()

    insufficient = {
        table: {"actual": counts[table], "minimum": minimum}
        for table, minimum in REQUIRED_TABLES.items()
        if counts[table] < minimum
    }
    if insufficient:
        raise RuntimeError(
            "结构化专表记录不足：" + json.dumps(insufficient, ensure_ascii=False)
        )
    return counts


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            {"database": str(args.database), "tables": verify(args.database)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

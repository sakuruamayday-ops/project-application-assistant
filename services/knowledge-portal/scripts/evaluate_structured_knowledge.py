from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from scripts.build_knowledge_content_index import infer_document_metadata, normalize_match_text


DEFAULT_GOLD_SET = Path(__file__).resolve().parents[1] / "tests/fixtures/structured_knowledge_gold.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评估名单、政策元数据和项目地图的金标准准确率")
    parser.add_argument("--gold-set", type=Path, default=DEFAULT_GOLD_SET)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--core-threshold", type=float, default=0.95)
    parser.add_argument("--top5-threshold", type=float, default=0.90)
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def sql_filtered_rows(
    connection: sqlite3.Connection,
    table: str,
    filters: dict[str, object],
    columns: str,
) -> list[sqlite3.Row]:
    conditions: list[str] = []
    parameters: list[object] = []
    for column, value in filters.items():
        if value in (None, ""):
            continue
        if column in {"canonical_project_name", "region", "batch", "document_stage", "validity_status"}:
            conditions.append(f"{column} LIKE ?")
            parameters.append(f"%{value}%")
        else:
            conditions.append(f"{column}=?")
            parameters.append(value)
    where = " AND ".join(conditions) or "1=1"
    return connection.execute(
        f"SELECT {columns} FROM {table} WHERE {where} LIMIT 5",
        parameters,
    ).fetchall()


def evaluate(
    cases: list[dict[str, object]],
    database_path: Path | None = None,
) -> dict[str, object]:
    counts: Counter[str] = Counter()
    failures: list[dict[str, object]] = []
    connection: sqlite3.Connection | None = None
    if database_path:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
    try:
        for case in cases:
            kind = str(case["kind"])
            counts[f"{kind}_total"] += 1
            passed = False
            actual: object = None
            if kind == "metadata":
                metadata = infer_document_metadata(
                    str(case["title"]), str(case["source"]), str(case.get("content") or ""), str(case["role"])
                )
                expected = dict(case["expected"])
                comparisons = {field: metadata.get(field) == value for field, value in expected.items()}
                for matched in comparisons.values():
                    counts["core_fields_total"] += 1
                    counts["core_fields_passed"] += int(matched)
                passed = all(comparisons.values())
                actual = {field: metadata.get(field) for field in expected}
            elif kind in {"list_query", "policy_query"}:
                if connection is None:
                    counts[f"{kind}_skipped"] += 1
                    continue
                table = "public_list_entities" if kind == "list_query" else "documents"
                rows = sql_filtered_rows(
                    connection, table, dict(case["filters"]),
                    "enterprise_name,canonical_project_name,region,policy_year,batch,list_status" if kind == "list_query" else "title,canonical_project_name,region,policy_year,document_stage,validity_status",
                )
                expected_contains = str(case["expected_contains"])
                actual = [dict(row) for row in rows]
                passed = any(expected_contains in " ".join(str(value) for value in row) for row in rows)
                counts["top5_total"] += 1
                counts["top5_passed"] += int(passed)
            elif kind == "project_match":
                from scripts.project_catalog_matching import match_project_records

                result = match_project_records(
                    regions=list(case.get("regions") or []),
                    keywords=list(case.get("keywords") or []),
                    limit=5,
                )
                names = [str(item["canonical_project_name"]) for item in result["results"]]
                expected_contains = str(case["expected_contains"])
                actual = names
                normalized_expected = normalize_match_text(expected_contains)
                passed = any(
                    normalized_expected in normalize_match_text(name) for name in names
                )
                counts["top5_total"] += 1
                counts["top5_passed"] += int(passed)
            counts[f"{kind}_passed"] += int(passed)
            if not passed:
                failures.append({"id": case["id"], "kind": kind, "actual": actual})
    finally:
        if connection is not None:
            connection.close()

    core_accuracy = counts["core_fields_passed"] / max(1, counts["core_fields_total"])
    top5_accuracy = counts["top5_passed"] / max(1, counts["top5_total"])
    return {
        "cases": len(cases),
        "counts": dict(counts),
        "core_field_accuracy": round(core_accuracy, 4),
        "top5_hit_rate": round(top5_accuracy, 4),
        "failures": failures,
    }


def main() -> None:
    args = parse_args()
    result = evaluate(
        load_cases(args.gold_set.expanduser().resolve()),
        args.database.expanduser().resolve() if args.database else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["core_field_accuracy"] < args.core_threshold:
        raise SystemExit("核心字段准确率未达到验收阈值")
    if args.database and result["top5_hit_rate"] < args.top5_threshold:
        raise SystemExit("查询前五位命中率未达到验收阈值")


if __name__ == "__main__":
    main()

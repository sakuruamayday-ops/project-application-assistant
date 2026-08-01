#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.authoritative_list_facts import query_authoritative_list_facts


DEFAULT_DATABASE = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_GOLD = SERVICE_ROOT / "references" / "authoritative-list-fact-gold-standard.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证权威名单事实查询的总数、来源、官方匹配和分页完整性")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    return parser.parse_args()


def evaluate(database: Path, gold_path: Path) -> dict[str, object]:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    failures: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for case in gold["cases"]:
            filters = dict(case["filters"])
            page_size = int(case["page_size"])
            expected = dict(case["expected"])
            offset = 0
            page_sizes: list[int] = []
            fact_ids: list[str] = []
            first_summary: dict[str, object] | None = None
            first_coverage: dict[str, object] | None = None
            first_total: int | None = None
            try:
                while True:
                    response = query_authoritative_list_facts(
                        connection,
                        **filters,
                        offset=offset,
                        limit=page_size,
                    )
                    if first_summary is None:
                        first_summary = dict(response["summary"])
                        first_coverage = dict(response["coverage"])
                        first_total = int(response["total"])
                    page = list(response["results"])
                    page_sizes.append(len(page))
                    fact_ids.extend(str(item["fact_id"]) for item in page)
                    pagination = dict(response["pagination"])
                    if not pagination["has_more"]:
                        if pagination["next_offset"] is not None or pagination["is_truncated"]:
                            raise AssertionError("末页分页状态不闭合")
                        break
                    next_offset = pagination["next_offset"]
                    if next_offset is None or int(next_offset) <= offset:
                        raise AssertionError("分页游标未前进")
                    offset = int(next_offset)
                    if len(page_sizes) > 10000:
                        raise AssertionError("分页次数异常")
            except Exception as error:  # noqa: BLE001 - 金标准需要收集完整失败原因
                failures.append({"id": case["id"], "error": f"{type(error).__name__}: {error}"})
                continue

            actual = {
                "total": first_total,
                "official_match_count": int((first_summary or {}).get("official_match_count", -1)),
                "completeness_claim_allowed": bool(
                    (first_coverage or {}).get("completeness_claim_allowed")
                ),
                "source_tier_counts": dict((first_summary or {}).get("source_tier_counts", {})),
                "page_sizes": page_sizes,
                "unique_fact_count": len(set(fact_ids)),
                "retrieved_fact_count": len(fact_ids),
            }
            expected_actual = {
                "total": expected["total"],
                "official_match_count": expected["official_match_count"],
                "completeness_claim_allowed": expected[
                    "completeness_claim_allowed"
                ],
                "source_tier_counts": expected["source_tier_counts"],
                "page_sizes": expected["page_sizes"],
                "unique_fact_count": expected["total"],
                "retrieved_fact_count": expected["total"],
            }
            passed = actual == expected_actual
            results.append({"id": case["id"], "passed": passed, "actual": actual})
            if not passed:
                failures.append(
                    {"id": case["id"], "expected": expected_actual, "actual": actual}
                )
    return {
        "schema_version": gold["schema_version"],
        "database": str(database),
        "gold": str(gold_path),
        "cases": results,
        "passed": not failures,
        "failures": failures,
    }


def main() -> None:
    args = parse_args()
    result = evaluate(args.database.expanduser().resolve(), args.gold.expanduser().resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit("权威名单事实查询金标准未通过")


if __name__ == "__main__":
    main()

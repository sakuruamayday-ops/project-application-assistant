#!/usr/bin/env python3
"""Create an explicitly labelled Qice fallback for a missing city attachment."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TIMELINE_SCRIPT = ROOT / "scripts" / "build_zhejiang_enterprise_identity_timeline.py"


def normalize_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value or "").lower()


def load_timeline_module() -> Any:
    specification = importlib.util.spec_from_file_location(
        "identity_timeline_for_qice_gap",
        TIMELINE_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot import timeline builder: {TIMELINE_SCRIPT}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--qice-json", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--document-title", required=True)
    parser.add_argument("--event-year", type=int, required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--target-city", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--announced-count", type=int, required=True)
    parser.add_argument("--exclude-document-id", action="append", type=int, default=[])
    parser.add_argument("--exclude-spreadsheet", action="append", type=Path, default=[])
    parser.add_argument("--official-url", default="")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def exclusion_names(args: argparse.Namespace, timeline: Any) -> set[str]:
    excluded: set[str] = set()
    connection = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    for document_id in args.exclude_document_id:
        rows = connection.execute(
            """
            SELECT enterprise_name FROM public_list_entities WHERE document_id=?
            UNION ALL
            SELECT enterprise_name FROM enterprise_mentions WHERE document_id=?
            """,
            (document_id, document_id),
        ).fetchall()
        excluded.update(normalize_name(str(row[0] or "")) for row in rows)
    connection.close()
    for path in args.exclude_spreadsheet:
        excluded.update(
            normalize_name(name)
            for name, _ in timeline.xlsx_enterprise_column(path.expanduser())
        )
    return {name for name in excluded if name}


def main() -> None:
    args = parse_args()
    timeline = load_timeline_module()
    excluded = exclusion_names(args, timeline)
    records = json.loads(args.qice_json.read_text(encoding="utf-8"))
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if str(record.get("city") or "") != args.target_city:
            continue
        aliases = {normalize_name(str(record.get("entName") or ""))}
        aliases.update(
            normalize_name(str(item.get("entHisName") or ""))
            for item in record.get("entHisList") or []
        )
        aliases.discard("")
        if aliases & excluded:
            continue
        name = str(record.get("entName") or "").strip()
        normalized = normalize_name(name)
        if not name or normalized in seen:
            continue
        seen.add(normalized)
        entities.append(
            {
                "sequence_no": len(entities) + 1,
                "enterprise_name": name,
                "province": "浙江省",
                "city": args.target_city,
                "county": str(record.get("county") or ""),
                "qice_eid": str(record.get("eid") or ""),
                "former_names": [
                    str(item.get("entHisName") or "")
                    for item in record.get("entHisList") or []
                    if str(item.get("entHisName") or "")
                ],
            }
        )
    if len(entities) != args.expected_count:
        raise ValueError(
            f"Qice gap count mismatch: expected={args.expected_count} "
            f"actual={len(entities)}"
        )

    payload = {
        "schema_version": 1,
        "source_id": args.source_id,
        "document_title": args.document_title,
        "project_name": "浙江省专精特新中小企业",
        "event_year": args.event_year,
        "batch": args.batch,
        "city": args.target_city,
        "coverage_status": (
            "qice_gap_complete"
            if args.expected_count == args.announced_count
            else "qice_gap_partial"
        ),
        "coverage_basis": "official_announced_count_plus_qice_gap_after_local_source_subtraction",
        "expected_count": args.expected_count,
        "announced_count": args.announced_count,
        "official_url": args.official_url,
        "excluded_local_entity_keys": len(excluded),
        "entities": entities,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "source_id": args.source_id,
                "entities": len(entities),
                "announced_count": args.announced_count,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

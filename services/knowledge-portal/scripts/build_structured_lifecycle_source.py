#!/usr/bin/env python3
"""Bind an ordered official lifecycle list to its event-time city blocks.

The Zhejiang final notices commonly publish one numbered provincial list whose
rows are grouped by prefecture but whose extracted text omits the city heading.
This helper keeps the official row order and applies audited block sizes.  It is
deliberately deterministic: a block-size mismatch stops the build instead of
guessing a city from an enterprise's current address.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TIMELINE_SCRIPT = ROOT / "scripts" / "build_zhejiang_enterprise_identity_timeline.py"


def load_timeline_module() -> Any:
    specification = importlib.util.spec_from_file_location(
        "identity_timeline_for_structured_source",
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
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument(
        "--city-block",
        action="append",
        default=[],
        help="ordered CITY:COUNT block; repeat once per city",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def parse_blocks(values: list[str]) -> list[tuple[str, int]]:
    blocks: list[tuple[str, int]] = []
    for value in values:
        city, separator, count = value.rpartition(":")
        if not separator or not city.strip() or not count.isdigit():
            raise ValueError(f"invalid city block: {value}")
        blocks.append((city.strip(), int(count)))
    if not blocks:
        raise ValueError("at least one --city-block is required")
    return blocks


def source_rows(
    database: Path,
    source: dict[str, Any],
    timeline: Any,
) -> list[tuple[str, str]]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    document = connection.execute(
        """
        SELECT content
        FROM documents
        WHERE title=?
        ORDER BY id
        LIMIT 1
        """,
        (source["document_title"],),
    ).fetchone()
    connection.close()
    if document is None:
        raise ValueError(f"source document not indexed: {source['document_title']}")
    section = timeline.lifecycle_section(
        str(document["content"] or ""),
        str(source.get("start_pattern") or ""),
        str(source.get("end_pattern") or ""),
    )
    extraction = str(source.get("entity_extraction") or "")
    if extraction != "numbered_organization_lines":
        raise ValueError(
            f"unsupported extraction for ordered source: {extraction or 'default'}"
        )
    return timeline.numbered_organization_lines(section)


def main() -> None:
    args = parse_args()
    timeline = load_timeline_module()
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    source = next(
        (
            item
            for item in configuration.get("local_event_sources", [])
            if item.get("source_id") == args.source_id
        ),
        None,
    )
    if source is None:
        raise ValueError(f"lifecycle source not configured: {args.source_id}")
    rows = source_rows(args.database, source, timeline)
    blocks = parse_blocks(args.city_block)
    expected = int(source.get("expected_count") or len(rows))
    block_total = sum(count for _, count in blocks)
    if len(rows) != expected or block_total != expected:
        raise ValueError(
            f"source/block count mismatch: rows={len(rows)} "
            f"blocks={block_total} expected={expected}"
        )

    entities: list[dict[str, Any]] = []
    offset = 0
    block_audit: list[dict[str, Any]] = []
    for city, count in blocks:
        start = offset + 1
        for name, sequence_no in rows[offset : offset + count]:
            entities.append(
                {
                    "sequence_no": sequence_no,
                    "enterprise_name": name,
                    "province": "浙江省",
                    "city": city,
                    "county": "",
                }
            )
        offset += count
        block_audit.append(
            {
                "city": city,
                "start_row": start,
                "end_row": offset,
                "count": count,
            }
        )

    payload = {
        "schema_version": 1,
        "source_id": args.source_id,
        "document_title": source["document_title"],
        "project_name": source["project_name"],
        "event_year": source.get("event_year"),
        "batch": source.get("batch"),
        "coverage_basis": "official_ordered_attachment_plus_audited_city_blocks",
        "block_audit": block_audit,
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
                "blocks": block_audit,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

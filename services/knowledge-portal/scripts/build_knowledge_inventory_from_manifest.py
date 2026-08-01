#!/usr/bin/env python3
"""Rebuild the filename/path inventory from an already frozen manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prepare_knowledge_upload import build_database


REQUIRED_FIELDS = {
    "source_path",
    "relative_path",
    "cloud_path",
    "name",
    "extension",
    "size_bytes",
    "modified_at",
    "sha256",
    "top_category",
    "document_role",
    "sensitivity",
    "index_mode",
    "upload_priority",
    "upload_action",
    "canonical_path",
}


def load_manifest(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        record = json.loads(line)
        missing = sorted(REQUIRED_FIELDS - record.keys())
        if missing:
            raise ValueError(
                f"manifest line {line_number} missing fields: {', '.join(missing)}"
            )
        records.append(record)
    if not records:
        raise ValueError("manifest contains no records")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从已冻结manifest重建文件名与路径检索库，不重写manifest"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = args.manifest.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    records = load_manifest(manifest)
    build_database(output, records)
    print(
        json.dumps(
            {
                "status": "pass",
                "manifest": str(manifest),
                "output": str(output),
                "documents": len(records),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_knowledge_inventory_from_manifest.py"
)


def test_inventory_is_rebuilt_from_frozen_manifest(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    output = tmp_path / "knowledge_inventory.sqlite3"
    record = {
        "source_path": "/knowledge/policy.pdf",
        "relative_path": "10_政策与目录/policy.pdf",
        "cloud_path": "10_政策与通知/10_政策与目录/policy.pdf",
        "name": "policy.pdf",
        "extension": ".pdf",
        "size_bytes": 7,
        "modified_at": "2026-08-01T00:00:00+00:00",
        "sha256": "0" * 64,
        "top_category": "10_政策与目录",
        "document_role": "10_政策与通知",
        "sensitivity": "public_reference",
        "index_mode": "extract_text",
        "upload_priority": 1,
        "upload_action": "upload",
        "canonical_path": "10_政策与目录/policy.pdf",
    }
    original = json.dumps(record, ensure_ascii=False) + "\n"
    manifest.write_text(original, encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert manifest.read_text(encoding="utf-8") == original
    with sqlite3.connect(output) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert connection.execute(
            "SELECT relative_path FROM documents_fts WHERE documents_fts MATCH ?",
            ("policy",),
        ).fetchone()[0] == record["relative_path"]

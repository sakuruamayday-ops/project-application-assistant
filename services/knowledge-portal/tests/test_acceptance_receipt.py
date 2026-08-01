from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "verify_acceptance_receipt.py"
)
SPEC = importlib.util.spec_from_file_location("verify_acceptance_receipt", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_receipt_is_reused_only_when_all_inputs_match(tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    index_root = tmp_path / "index"
    index_root.mkdir()
    (index_root / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (index_root / "knowledge_content.sqlite3").write_bytes(b"sqlite")
    receipt = tmp_path / "acceptance-harness.json"
    payload = {
        "receipt_schema": "jiaotang-acceptance-receipt/v1",
        "profile_id": "test",
        "generated_at": "2026-08-01T00:00:00+00:00",
        "requested_suites": ["knowledge_base"],
        "status": "pass",
        "release_allowed": True,
        "target_evidence": MODULE.expected_evidence(profile, index_root),
    }
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    result = MODULE.verify_receipt(
        receipt, profile, index_root, "knowledge_base"
    )
    assert result["status"] == "pass"

    (index_root / "manifest.jsonl").write_text('{"changed":true}\n', encoding="utf-8")
    result = MODULE.verify_receipt(
        receipt, profile, index_root, "knowledge_base"
    )
    assert result["status"] == "fail"
    assert "manifest_sha256" in result["mismatches"]

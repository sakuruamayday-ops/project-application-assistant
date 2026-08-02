from __future__ import annotations

import importlib.util
import hashlib
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
    (index_root / "knowledge_inventory.sqlite3").write_bytes(b"inventory")
    (index_root / "policy_versions.sqlite3").write_bytes(b"versions")
    (index_root / "upload_allowlist.csv").write_text(
        "relative_path,cloud_object_allowed\n", encoding="utf-8"
    )
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

    receipt.write_text(json.dumps(payload), encoding="utf-8")
    (index_root / "knowledge_inventory.sqlite3").write_bytes(b"changed")
    result = MODULE.verify_receipt(
        receipt, profile, index_root, "knowledge_base"
    )
    assert result["status"] == "fail"
    assert "inventory_index_sha256" in result["mismatches"]


def test_signed_receipt_verification_never_hashes_large_index_files(
    tmp_path,
    monkeypatch,
):
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    evidence = MODULE.expected_static_evidence(profile)
    signed_index_hashes = {
        evidence_name: hashlib.sha256(filename.encode()).hexdigest()
        for evidence_name, filename in MODULE.INDEX_EVIDENCE_FILES.items()
    }
    payload = {
        "receipt_schema": "jiaotang-acceptance-receipt/v1",
        "profile_id": "test",
        "generated_at": "2026-08-02T00:00:00+00:00",
        "requested_suites": ["knowledge_base"],
        "status": "pass",
        "release_allowed": True,
        "target_evidence": {**evidence, **signed_index_hashes},
    }
    receipt = tmp_path / "acceptance-harness.json"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    rows = [
        {
            "name": filename,
            "sha256": signed_index_hashes[evidence_name],
        }
        for evidence_name, filename in MODULE.INDEX_EVIDENCE_FILES.items()
    ]
    rows.append(
        {
            "name": "acceptance-harness.json",
            "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        }
    )
    release = {"files": rows}
    original_sha256_file = MODULE.sha256_file
    hashed_paths = []

    def tracking_sha256(path):
        hashed_paths.append(Path(path).name)
        return original_sha256_file(path)

    monkeypatch.setattr(MODULE, "sha256_file", tracking_sha256)
    result = MODULE.verify_signed_receipt(
        receipt,
        profile,
        release,
        "knowledge_base",
    )

    assert result["status"] == "pass"
    assert result["large_files_hashed"] == 0
    assert not set(MODULE.INDEX_EVIDENCE_FILES.values()) & set(hashed_paths)

    receipt.write_text(
        json.dumps(payload | {"profile_id": "tampered"}),
        encoding="utf-8",
    )
    tampered = MODULE.verify_signed_receipt(
        receipt,
        profile,
        release,
        "knowledge_base",
    )
    assert tampered["status"] == "fail"
    assert "acceptance receipt digest differs from signed pointer" in tampered["errors"]

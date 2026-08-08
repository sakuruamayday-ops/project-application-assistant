from __future__ import annotations

import hashlib
import json
import sqlite3
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import policy_increment_release as release
from scripts import verify_policy_increment_server as server_verify
from scripts.policy_increment_delta import PolicyIncrementError, generate_key


def file_row(path: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "crc64": "0",
    }


def test_signed_pointer_detects_tampering(tmp_path: Path) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    generate_key(private_path, public_path)
    private_key = release.load_private_key(private_path)
    public_key = release.load_public_key(public_path)
    assert server_verify.key_id(public_key) == release.public_key_id(public_key)
    payload = release.sign_document(
        {
            "schema": release.POINTER_SCHEMA,
            "key_id": release.public_key_id(public_key),
            "current_chain_sha256": "ab" * 32,
        },
        private_key,
    )
    release.verify_signed_document(payload, public_key)
    payload["current_chain_sha256"] = "cd" * 32
    with pytest.raises(Exception):
        release.verify_signed_document(payload, public_key)


def test_pointer_is_byte_stable_for_same_state(tmp_path: Path) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    generate_key(private_path, public_path)
    private_key = release.load_private_key(private_path)
    public_key = release.load_public_key(public_path)
    state = {
        "updated_at": "2026-08-08T08:22:21+08:00",
        "key_id": release.public_key_id(public_key),
        "base_release_id": "index-base",
        "base_index_sha256": "11" * 32,
        "base_manifest_sha256": "22" * 32,
        "base_chain_sha256": "33" * 32,
        "current_release_id": "policy-current",
        "current_chain_sha256": "44" * 32,
        "current_index_sha256": "55" * 32,
        "current_manifest_sha256": "66" * 32,
        "entries": [],
    }
    first = release.pointer_for_state(state, private_key)
    second = release.pointer_for_state(state, private_key)
    assert release.canonical_json_bytes(first) == release.canonical_json_bytes(second)


def test_initialize_requires_exact_complete_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        release,
        "PRODUCTION_FILES",
        ("knowledge_content.sqlite3", "manifest.jsonl"),
    )
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    database = baseline / "knowledge_content.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
    manifest = baseline / "manifest.jsonl"
    manifest.write_text("", encoding="utf-8")
    release_json = tmp_path / "release.json"
    release_json.write_text(
        json.dumps(
            {
                "schema": release.MANIFEST_SCHEMA,
                "release_id": "index-test-baseline",
                "file_whitelist": list(release.PRODUCTION_FILES),
                "files": [file_row(database), file_row(manifest)],
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / "chain"
    result = release.command_initialize(
        Namespace(
            baseline_index_dir=baseline,
            base_release_json=release_json,
            base_release_id="index-test-baseline",
            state_root=root,
            private_key=tmp_path / "keys/private.pem",
            public_key=tmp_path / "keys/public.pem",
        )
    )
    assert result["status"] == "initialized"
    state = release.load_state(root)
    assert state["current_release_id"] == "index-test-baseline"
    assert state["current_chain_sha256"] == state["base_chain_sha256"]
    assert release.verify_pointer_file(
        root / "base-pointer.json", Path(state["trusted_public_key"])
    )["chain_length"] == 0

    manifest.write_text("changed\n", encoding="utf-8")
    with pytest.raises(PolicyIncrementError, match="exact"):
        release.verify_against_release(baseline, release_json)


def test_finalize_is_fail_closed_until_all_production_receipts_pass(tmp_path: Path) -> None:
    root = tmp_path / "chain"
    root.mkdir()
    previous = "11" * 32
    current_state = {
        "schema": release.STATE_SCHEMA,
        "current_chain_sha256": previous,
    }
    release.write_json(root / "state.json", current_state)
    pending = current_state | {
        "current_chain_sha256": "22" * 32,
        "current_release_id": "policy-test-release",
    }
    run = tmp_path / "run"
    run.mkdir()
    release.write_json(run / "pending-state.json", pending)
    prepared = {
        "schema": release.PREPARED_SCHEMA,
        "state_root": str(root),
        "run_dir": str(run),
        "release_id": "policy-test-release",
        "chain_sha256": "22" * 32,
        "previous_chain_sha256": previous,
        "candidate_index_sha256": "33" * 32,
        "candidate_manifest_sha256": "44" * 32,
        "pending_state_path": str(run / "pending-state.json"),
    }
    release.write_json(run / "prepared-release.json", prepared)
    receipt = {
        "schema": release.RECEIPT_SCHEMA,
        "release_id": prepared["release_id"],
        "chain_sha256": prepared["chain_sha256"],
        "candidate_index_sha256": prepared["candidate_index_sha256"],
        "candidate_manifest_sha256": prepared["candidate_manifest_sha256"],
        "server_status": "healthy",
        "cloud_status": "exact",
        "rest_status": "pass",
        "mcp_status": "failed",
    }
    release.write_json(run / "receipt.json", receipt)
    args = Namespace(prepared=run / "prepared-release.json", receipt=run / "receipt.json")
    with pytest.raises(PolicyIncrementError, match="finalize门禁"):
        release.command_finalize(args)
    assert release.load_state(root)["current_chain_sha256"] == previous

    receipt["mcp_status"] = "pass"
    release.write_json(run / "receipt.json", receipt)
    result = release.command_finalize(args)
    assert result["status"] == "finalized"
    assert release.load_state(root)["current_chain_sha256"] == "22" * 32


def test_delta_upload_allowlist_contains_only_frozen_rows(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    rows = [
        {
            "relative_path": "10_政策与目录/a.md",
            "sha256": "ab" * 32,
            "source_path": "/tmp/a.md",
            "upload_action": "upload",
        }
    ]
    release.write_json(package / "delta_payload.json", {"manifest_rows": rows})
    manifest, allowlist = release.create_upload_files(package, tmp_path)
    assert manifest.read_text(encoding="utf-8").count("relative_path") == 1
    text = allowlist.read_text(encoding="utf-8-sig")
    assert "10_政策与目录/a.md" in text
    assert "true" in text


def test_server_release_verification_detects_local_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_verify, "PRODUCTION_FILES", ("knowledge_content.sqlite3", "manifest.jsonl"))
    release_id = "policy-" + "ab" * 20
    index_root = tmp_path / "index"
    release_dir = index_root / "releases" / release_id
    release_dir.mkdir(parents=True)
    database = release_dir / "knowledge_content.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
    manifest = release_dir / "manifest.jsonl"
    manifest.write_text("", encoding="utf-8")
    index_sha = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    release_payload = {
        "schema": server_verify.MANIFEST_SCHEMA,
        "release_id": release_id,
        "previous_release_id": "index-base-release",
        "storage_mode": "signed-policy-delta-chain-v1",
        "file_whitelist": list(server_verify.PRODUCTION_FILES),
        "files": [file_row(database), file_row(manifest)],
        "incremental_overlay": {"chain_sha256": "cd" * 32},
    }
    (release_dir / "release.json").write_text(json.dumps(release_payload), encoding="utf-8")
    (index_root / "current").symlink_to(Path("releases") / release_id)
    pointer = {
        "current_release_id": release_id,
        "current_chain_sha256": "cd" * 32,
        "current_index_sha256": index_sha,
        "current_manifest_sha256": manifest_sha,
    }
    assert server_verify.verify_local_release(index_root, pointer, deep=True)["release_id"] == release_id
    manifest.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(server_verify.VerificationError, match="身份|哈希"):
        server_verify.verify_local_release(index_root, pointer, deep=True)


def test_shell_release_contract_has_rollback_and_page_aligned_rsync() -> None:
    script_dir = Path(__file__).resolve().parents[1] / "scripts"
    deploy = (script_dir / "deploy_policy_increment_to_server.sh").read_text(encoding="utf-8")
    release_script = (script_dir / "release_policy_increment.sh").read_text(encoding="utf-8")
    assert "--block-size=4096" in deploy
    assert "--no-whole-file" in deploy
    assert "--partial-dir=.policy-rsync-partial" in deploy
    assert "--inplace" not in deploy
    assert "政策增量release健康失败，已自动回滚" in deploy
    assert "rollback-pointer" in release_script
    assert "restore-legacy-verifier" in release_script
    assert release_script.index("upload-immutable") < release_script.index("pause-verifiers")
    assert release_script.index("pause-verifiers") < release_script.index("switch-pointer")

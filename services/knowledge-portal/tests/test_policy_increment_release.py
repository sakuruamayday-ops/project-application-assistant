from __future__ import annotations

import hashlib
import json
import sqlite3
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

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


def test_server_status_inherits_protected_data_directory_group(
    tmp_path: Path,
) -> None:
    status = tmp_path / "oss-index-cache-status.json"

    server_verify.write_status(status, {"status": "正常"})

    assert status.stat().st_gid == tmp_path.stat().st_gid
    assert status.stat().st_mode & 0o777 == 0o640
    assert json.loads(status.read_text(encoding="utf-8")) == {"status": "正常"}


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


def test_pointer_binds_full_release_manifest_when_present(tmp_path: Path) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    generate_key(private_path, public_path)
    private_key = release.load_private_key(private_path)
    public_key = release.load_public_key(public_path)
    state = {
        "updated_at": "2026-08-11T08:25:09Z",
        "key_id": release.public_key_id(public_key),
        "base_release_id": "index-base",
        "base_index_sha256": "11" * 32,
        "base_manifest_sha256": "22" * 32,
        "base_chain_sha256": "33" * 32,
        "current_release_id": "index-current",
        "current_chain_sha256": "33" * 32,
        "current_index_sha256": "44" * 32,
        "current_manifest_sha256": "55" * 32,
        "current_release_manifest_sha256": "66" * 32,
        "entries": [],
    }

    pointer = release.pointer_for_state(state, private_key)

    assert pointer["current_release_manifest_sha256"] == "66" * 32


def test_new_release_manifest_replaces_inherited_binding_across_artifacts(
    tmp_path: Path,
) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    generate_key(private_path, public_path)
    private_key = release.load_private_key(private_path)
    public_key = release.load_public_key(public_path)
    raw_release = tmp_path / "candidate-index" / "release.json"
    package_release = tmp_path / "delta-package" / "release.json"
    raw_release.parent.mkdir()
    package_release.parent.mkdir()
    raw_release.write_text('{"release_id":"policy-new"}\n', encoding="utf-8")
    package_release.write_bytes(raw_release.read_bytes())
    state = {
        "updated_at": "2026-08-13T01:00:00Z",
        "key_id": release.public_key_id(public_key),
        "base_release_id": "index-base",
        "base_index_sha256": "11" * 32,
        "base_manifest_sha256": "22" * 32,
        "base_chain_sha256": "33" * 32,
        "current_release_id": "policy-new",
        "current_chain_sha256": "44" * 32,
        "current_index_sha256": "55" * 32,
        "current_manifest_sha256": "66" * 32,
        "current_release_manifest_sha256": "77" * 32,
        "entries": [],
    }

    digest = release.bind_current_release_manifest(
        state, raw_release, package_release
    )
    pointer = release.pointer_for_state(state, private_key)
    prepared = {
        "package_dir": str(package_release.parent),
        "release_manifest_sha256": digest,
    }

    assert digest == hashlib.sha256(raw_release.read_bytes()).hexdigest()
    assert pointer["current_release_manifest_sha256"] == digest
    assert release.verify_release_manifest_binding(prepared, pointer) == digest


def test_release_manifest_binding_rejects_divergent_artifacts(tmp_path: Path) -> None:
    raw_release = tmp_path / "candidate-release.json"
    package_release = tmp_path / "package-release.json"
    raw_release.write_text('{"release_id":"candidate"}\n', encoding="utf-8")
    package_release.write_text('{"release_id":"package"}\n', encoding="utf-8")

    with pytest.raises(PolicyIncrementError, match="release清单不一致"):
        release.bind_current_release_manifest({}, raw_release, package_release)


def test_release_manifest_binding_rejects_stale_signed_pointer(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    release_path = package / "release.json"
    release_path.write_text('{"release_id":"policy-new"}\n', encoding="utf-8")
    prepared = {"package_dir": str(package)}
    pointer = {"current_release_manifest_sha256": "11" * 32}

    with pytest.raises(PolicyIncrementError, match="签名指针绑定摘要不一致"):
        release.verify_release_manifest_binding(prepared, pointer)


def test_prepare_binds_generated_release_manifest_to_state_pointer_and_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    generate_key(private_path, public_path)
    private_key = release.load_private_key(private_path)
    public_key = release.load_public_key(public_path)
    current_index = tmp_path / "current-index"
    current_index.mkdir()
    database = current_index / "knowledge_content.sqlite3"
    database.write_bytes(b"sqlite")
    manifest = current_index / "manifest.jsonl"
    manifest.write_text("", encoding="utf-8")
    state_root = tmp_path / "state"
    state_root.mkdir()
    previous_release_manifest = "77" * 32
    state = {
        "schema": release.STATE_SCHEMA,
        "created_at": "2026-08-12T01:00:00Z",
        "updated_at": "2026-08-12T01:00:00Z",
        "key_id": release.public_key_id(public_key),
        "trusted_public_key": str(public_path),
        "base_release_id": "index-base",
        "base_index_sha256": "11" * 32,
        "base_manifest_sha256": "22" * 32,
        "base_chain_sha256": "33" * 32,
        "base_anchor_dir": str(tmp_path / "base-anchor"),
        "current_release_id": "policy-previous",
        "current_index_dir": str(current_index),
        "current_chain_sha256": "44" * 32,
        "current_index_sha256": "55" * 32,
        "current_manifest_sha256": "66" * 32,
        "current_release_manifest_sha256": previous_release_manifest,
        "entries": [],
    }
    release.write_json(state_root / "state.json", state)
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    release.write_json(handoff_dir / "increment_handoff.json", {"handoff_id": "h1"})

    def fake_build_package(namespace: Namespace) -> dict[str, object]:
        namespace.candidate_dir.mkdir()
        namespace.package_dir.mkdir()
        release.write_json(
            namespace.package_dir / "delta_manifest.json",
            {"generated_at": "2026-08-13T01:00:00Z"},
        )
        release.write_json(
            namespace.package_dir / "delta_payload.json",
            {"manifest_rows": []},
        )
        return {
            "chain_sha256": "88" * 32,
            "candidate_index_sha256": "99" * 32,
            "candidate_manifest_sha256": "aa" * 32,
            "counts": {},
            "validation": {},
        }

    def fake_prepare_release_files(
        candidate: Path,
        *,
        prevalidated: bool,
    ) -> tuple[list[tuple[Path, dict[str, object]]], dict[str, object]]:
        assert prevalidated is True
        return (
            [
                (candidate / name, file_row(candidate / name))
                for name in release.PRODUCTION_FILES
            ],
            {},
        )

    monkeypatch.setattr(release, "PRODUCTION_FILES", (database.name, manifest.name))
    monkeypatch.setattr(release, "verify_current_state", lambda *_args: current_index)
    monkeypatch.setattr(release, "build_package", fake_build_package)
    monkeypatch.setattr(release, "prepare_release_files", fake_prepare_release_files)
    monkeypatch.setenv("JIAOTANG_POLICY_ALLOW_FULL_COPY", "1")
    run_dir = tmp_path / "run"

    prepared = release.command_prepare(
        Namespace(
            state_root=state_root,
            handoff_dir=handoff_dir,
            run_dir=run_dir,
            knowledge_root=tmp_path / "knowledge",
            private_key=private_path,
        )
    )

    release_digest = release.sha256_file(run_dir / "candidate-index" / "release.json")
    pending = release.load_json(run_dir / "pending-state.json", "pending")
    pointer = release.verify_pointer_file(run_dir / "chain-pointer.json", public_path)
    assert release_digest != previous_release_manifest
    assert release.sha256_file(run_dir / "delta-package" / "release.json") == release_digest
    assert prepared["release_manifest_sha256"] == release_digest
    assert pending["current_release_manifest_sha256"] == release_digest
    assert pointer["current_release_manifest_sha256"] == release_digest
    assert release.verify_release_manifest_binding(prepared, pointer) == release_digest


def test_remote_pointer_requires_signed_structural_chain_consistency(
    tmp_path: Path,
) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    generate_key(private_path, public_path)
    private_key = release.load_private_key(private_path)
    public_key = release.load_public_key(public_path)

    class StoredObject:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

    class Bucket:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = release.canonical_json_bytes(payload)

        def head_object(self, _key: str) -> object:
            return SimpleNamespace()

        def get_object(self, _key: str) -> StoredObject:
            return StoredObject(self.payload)

    base_chain = "33" * 32
    payload = release.sign_document(
        {
            "schema": release.POINTER_SCHEMA,
            "updated_at": "2026-08-11T08:25:09Z",
            "key_id": release.public_key_id(public_key),
            "base_chain_sha256": base_chain,
            "current_chain_sha256": base_chain,
            "chain_length": 0,
            "entries": [],
        },
        private_key,
    )
    assert (
        release.remote_pointer(Bucket(payload), "current.json", public_path)[
            "current_chain_sha256"
        ]
        == base_chain
    )

    inconsistent = release.sign_document(
        {**payload, "chain_length": 1, "signature_base64": ""},
        private_key,
    )
    with pytest.raises(PolicyIncrementError, match="条目数量"):
        release.remote_pointer(Bucket(inconsistent), "current.json", public_path)


def test_existing_transition_is_reused_when_only_timestamp_differs() -> None:
    existing = {
        "schema": "jiaotang-policy-increment-transition/v1",
        "created_at": "2026-08-08T01:00:00Z",
        "reason": "weekly-policy-release",
        "expected_chain_sha256": "11" * 32,
        "target_chain_sha256": "22" * 32,
        "target_pointer_sha256": "33" * 32,
    }
    raw = release.canonical_json_bytes(existing)

    class StoredObject:
        def read(self) -> bytes:
            return raw

    class Bucket:
        def head_object(self, key: str) -> object:
            return SimpleNamespace(
                content_length=len(raw),
                headers={"x-oss-meta-sha256": hashlib.sha256(raw).hexdigest()},
            )

        def get_object(self, key: str) -> StoredObject:
            return StoredObject()

    retry = existing | {"created_at": "2026-08-08T02:00:00Z"}
    assert release.put_or_verify_transition(Bucket(), "transition.json", retry) == "existing"
    with pytest.raises(PolicyIncrementError, match="迁移凭证冲突"):
        release.put_or_verify_transition(
            Bucket(),
            "transition.json",
            retry | {"target_chain_sha256": "44" * 32},
        )


def test_initialize_requires_exact_complete_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GitHub Actions commonly uses overlayfs, which does not guarantee reflink
    # support. This fixture is deliberately tiny and tests baseline integrity,
    # not the production no-full-copy default.
    monkeypatch.setenv("JIAOTANG_POLICY_ALLOW_FULL_COPY", "1")
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
    assert "JIAOTANG_POLICY_RESUME_PREPARED" in release_script
    assert "复用原冻结发布包续发" in release_script
    assert "续发冻结产物与本次交接包不一致" in release_script
    assert "install_target}-repeat-" in deploy
    assert 'deployment_action="already-current"' in deploy
    assert 'deployment_action="switched-existing"' in deploy
    assert 'basename "${remote_inactive}"' in deploy
    assert 'row["source_key"]' in release_script
    assert "WHERE source_key=?" in release_script
    assert "source_path" not in release_script
    assert release_script.index("upload-immutable") < release_script.index("pause-verifiers")
    assert release_script.index("pause-verifiers") < release_script.index("switch-pointer")

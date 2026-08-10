from __future__ import annotations

import base64
import copy
import importlib.util
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release_transaction.py"
SPEC = importlib.util.spec_from_file_location("release_transaction_for_tests", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def transaction_manifest(*, commit: str = "abc123") -> dict[str, object]:
    return {
        "schema": MODULE.TRANSACTION_SCHEMA,
        "version": "2.0.0",
        "semantic_version": "2.0.0",
        "tag": "V2.0.0",
        "repository": "owner/repository",
        "git_commit": commit,
        "publisher_fingerprint": "filled-after-signing",
        "participants": {
            "github": {
                "release_tag": "V2.0.0",
                "target_commit": commit,
                "required_asset_sha256": {"generic.zip": "1" * 64},
            },
            "portal": {
                "release_version": "2.0.0",
                "package_sha256": {"generic": "1" * 64},
            },
            "installation": {
                "release_tag": "V2.0.0",
                "generic_package_sha256": "1" * 64,
                "skill_count": 49,
            },
        },
        "lease_policy": {
            "scope": "release-version",
            "single_writer": True,
            "non_holder_mode": "read-only-monitor",
        },
    }


def signed_transaction(
    tmp_path: Path,
    *,
    commit: str = "abc123",
) -> tuple[dict[str, object], dict[str, object], str]:
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / f"{commit}.key"
    public_path = tmp_path / f"{commit}.pub"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH,
        )
        + b"\n"
    )
    manifest = transaction_manifest(commit=commit)
    manifest_bytes, signature, fingerprint = (
        MODULE.sign_transaction_manifest(
            manifest,
            private_key_path=private_path,
            public_key_path=public_path,
        )
    )
    verification = MODULE.verify_transaction_manifest(
        manifest_bytes=manifest_bytes,
        signature_payload=signature,
        public_key_text=public_path.read_text(encoding="utf-8"),
        expected_fingerprint=fingerprint,
    )
    return verification, signature, public_path.read_text(encoding="utf-8")


def test_signed_transaction_manifest_is_deterministic_and_tamper_evident(
    tmp_path: Path,
) -> None:
    verification, signature, public_key = signed_transaction(tmp_path)
    canonical = MODULE.canonical_json_bytes(verification["manifest"])
    repeated = MODULE.verify_transaction_manifest(
        manifest_bytes=canonical,
        signature_payload=signature,
        public_key_text=public_key,
    )
    assert repeated["manifest_sha256"] == verification["manifest_sha256"]
    assert repeated["signature_status"] == "verified"
    assert repeated["manifest"]["schema"] == "gongchuang-release-transaction/v1"

    tampered = copy.deepcopy(verification["manifest"])
    tampered["git_commit"] = "attacker"
    with pytest.raises(RuntimeError, match="哈希与签名元数据不一致|签名验证失败"):
        MODULE.verify_transaction_manifest(
            manifest_bytes=MODULE.canonical_json_bytes(tampered),
            signature_payload=signature,
            public_key_text=public_key,
        )


def test_legacy_transaction_schema_remains_verifiable(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_text = (
        private_key.public_key().public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH,
        )
        + b"\n"
    ).decode("utf-8")
    public_path = tmp_path / "legacy.pub"
    public_path.write_text(public_text, encoding="utf-8")
    _, fingerprint, _ = MODULE.load_public_key(public_path)
    manifest = transaction_manifest()
    manifest["schema"] = MODULE.LEGACY_TRANSACTION_SCHEMA
    manifest_bytes = MODULE.canonical_json_bytes(manifest)
    signature_payload = {
        "schema": MODULE.LEGACY_SIGNATURE_SCHEMA,
        "algorithm": "Ed25519",
        "manifest_sha256": MODULE.sha256_bytes(manifest_bytes),
        "publisher_fingerprint": fingerprint,
        "signature_base64": base64.b64encode(
            private_key.sign(manifest_bytes)
        ).decode("ascii"),
    }

    verified = MODULE.verify_transaction_manifest(
        manifest_bytes=manifest_bytes,
        signature_payload=signature_payload,
        public_key_text=public_text,
    )

    assert verified["signature_status"] == "verified"
    assert verified["manifest"]["schema"] == MODULE.LEGACY_TRANSACTION_SCHEMA


def test_one_version_allows_one_writer_and_other_tasks_only_monitor(
    tmp_path: Path,
) -> None:
    verification, signature, public_key = signed_transaction(tmp_path)
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        first = MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-a",
            lease_token="a" * 32,
            ttl_seconds=3600,
            now=now,
        )
        assert first["status"] == "acquired"
        assert first["mode"] == "writer"

        second = MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-b",
            lease_token="b" * 32,
            ttl_seconds=3600,
            now=now + timedelta(minutes=1),
        )
        assert second["status"] == "held-by-other-task"
        assert second["mode"] == "read-only-monitor"
        assert second["holder_id"] == "thread-a"
        assert second["events"][0]["event_type"] == "lease-acquired"
        with pytest.raises(RuntimeError, match="不是该版本发布租约持有者"):
            MODULE.transition_release_transaction(
                connection,
                version="2.0.0",
                transaction_sha256=verification["manifest_sha256"],
                holder_id="thread-b",
                lease_token="b" * 32,
                target_state="github_staged",
                now=now + timedelta(minutes=1),
            )


def test_expired_lease_only_allows_same_signed_transaction_takeover(
    tmp_path: Path,
) -> None:
    verification, signature, public_key = signed_transaction(tmp_path)
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-a",
            lease_token="a" * 32,
            ttl_seconds=60,
            now=now,
        )
        takeover = MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-b",
            lease_token="b" * 32,
            ttl_seconds=60,
            now=now + timedelta(seconds=61),
        )
        assert takeover["status"] == "taken-over"
        assert takeover["holder_id"] == "thread-b"

        other_verification, other_signature, other_public_key = (
            signed_transaction(tmp_path, commit="different")
        )
        with pytest.raises(RuntimeError, match="不同的签名发布事务"):
            MODULE.acquire_release_lease(
                connection,
                verification=other_verification,
                signature_payload=other_signature,
                public_key_text=other_public_key,
                holder_id="thread-c",
                lease_token="c" * 32,
                ttl_seconds=60,
                now=now + timedelta(seconds=122),
            )


def test_early_failed_transaction_can_be_superseded_with_audit_evidence(
    tmp_path: Path,
) -> None:
    verification, signature, public_key = signed_transaction(tmp_path)
    replacement, replacement_signature, replacement_key = signed_transaction(
        tmp_path,
        commit="fixed-commit",
    )
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-a",
            lease_token="a" * 32,
            ttl_seconds=3600,
            now=now,
        )
        MODULE.transition_release_transaction(
            connection,
            version="2.0.0",
            transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            target_state="github_staged",
            now=now + timedelta(seconds=1),
        )
        MODULE.transition_release_transaction(
            connection,
            version="2.0.0",
            transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            target_state="failed",
            now=now + timedelta(seconds=2),
        )

        result = MODULE.supersede_failed_release_transaction(
            connection,
            verification=replacement,
            signature_payload=replacement_signature,
            public_key_text=replacement_key,
            previous_transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            evidence={
                "reason": "candidate source was repaired",
                "github_prerelease_removed": True,
                "portal_release_absent": True,
            },
            ttl_seconds=3600,
            now=now + timedelta(seconds=3),
        )

        assert result["status"] == "superseded"
        assert result["state"] == "leased"
        assert result["transaction_sha256"] == replacement["manifest_sha256"]
        assert {item["event_type"] for item in result["events"]} >= {
            "transaction-superseded",
            "lease-acquired-after-supersede",
        }


def test_failed_transaction_with_portal_state_cannot_be_superseded(
    tmp_path: Path,
) -> None:
    verification, signature, public_key = signed_transaction(tmp_path)
    replacement, replacement_signature, replacement_key = signed_transaction(
        tmp_path,
        commit="fixed-commit",
    )
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-a",
            lease_token="a" * 32,
            ttl_seconds=3600,
            now=now,
        )
        for offset, state in enumerate(("github_staged", "portal_staged"), 1):
            MODULE.transition_release_transaction(
                connection,
                version="2.0.0",
                transaction_sha256=verification["manifest_sha256"],
                holder_id="thread-a",
                lease_token="a" * 32,
                target_state=state,
                now=now + timedelta(seconds=offset),
            )
        MODULE.transition_release_transaction(
            connection,
            version="2.0.0",
            transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            target_state="failed",
            now=now + timedelta(seconds=3),
        )

        with pytest.raises(RuntimeError, match="门户已进入暂存或发布阶段"):
            MODULE.supersede_failed_release_transaction(
                connection,
                verification=replacement,
                signature_payload=replacement_signature,
                public_key_text=replacement_key,
                previous_transaction_sha256=verification["manifest_sha256"],
                holder_id="thread-a",
                lease_token="a" * 32,
                evidence={
                    "reason": "candidate source was repaired",
                    "github_prerelease_removed": True,
                    "portal_release_absent": True,
                },
                now=now + timedelta(seconds=4),
            )


def test_release_transaction_requires_ordered_three_party_completion(
    tmp_path: Path,
) -> None:
    verification, signature, public_key = signed_transaction(tmp_path)
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    states = [
        "github_staged",
        "portal_staged",
        "installing",
        "installed",
        "portal_published",
        "github_published",
        "completed",
    ]
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-a",
            lease_token="a" * 32,
            ttl_seconds=3600,
            now=now,
        )
        with pytest.raises(RuntimeError, match="不能从leased跳到installed"):
            MODULE.transition_release_transaction(
                connection,
                version="2.0.0",
                transaction_sha256=verification["manifest_sha256"],
                holder_id="thread-a",
                lease_token="a" * 32,
                target_state="installed",
                now=now,
            )
        for offset, state in enumerate(states, 1):
            result = MODULE.transition_release_transaction(
                connection,
                version="2.0.0",
                transaction_sha256=verification["manifest_sha256"],
                holder_id="thread-a",
                lease_token="a" * 32,
                target_state=state,
                evidence={"step": state},
                now=now + timedelta(seconds=offset),
            )
            assert result["state"] == state
        observed = MODULE.monitor_release_transaction(
            connection,
            version="2.0.0",
            observer_id="thread-b",
            now=now + timedelta(minutes=1),
        )
        assert observed["state"] == "completed"
        assert observed["lease_active"] is False
        assert observed["evidence"]["completed"]["step"] == "completed"


def test_failed_state_cannot_skip_remaining_release_participants(
    tmp_path: Path,
) -> None:
    verification, signature, public_key = signed_transaction(tmp_path)
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-a",
            lease_token="a" * 32,
            ttl_seconds=3600,
            now=now,
        )
        MODULE.transition_release_transaction(
            connection,
            version="2.0.0",
            transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            target_state="github_staged",
            now=now + timedelta(seconds=1),
        )
        failed = MODULE.transition_release_transaction(
            connection,
            version="2.0.0",
            transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            target_state="failed",
            evidence={"error": "portal unavailable"},
            now=now + timedelta(seconds=2),
        )
        assert failed["state"] == "failed"
        assert failed["last_success_state"] == "github_staged"

        with pytest.raises(
            RuntimeError,
            match="不能从github_staged跳到completed",
        ):
            MODULE.transition_release_transaction(
                connection,
                version="2.0.0",
                transaction_sha256=verification["manifest_sha256"],
                holder_id="thread-a",
                lease_token="a" * 32,
                target_state="completed",
                now=now + timedelta(seconds=3),
            )
        resumed = MODULE.transition_release_transaction(
            connection,
            version="2.0.0",
            transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            target_state="portal_staged",
            now=now + timedelta(seconds=4),
        )
        assert resumed["state"] == "portal_staged"
        assert resumed["last_success_state"] == "portal_staged"


def test_portal_published_failure_resumes_at_github_without_state_loss(
    tmp_path: Path,
) -> None:
    verification, signature, public_key = signed_transaction(tmp_path)
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        MODULE.acquire_release_lease(
            connection,
            verification=verification,
            signature_payload=signature,
            public_key_text=public_key,
            holder_id="thread-a",
            lease_token="a" * 32,
            ttl_seconds=3600,
            now=now,
        )
        for offset, state in enumerate(
            (
                "github_staged",
                "portal_staged",
                "installing",
                "installed",
                "portal_published",
            ),
            start=1,
        ):
            MODULE.transition_release_transaction(
                connection,
                version="2.0.0",
                transaction_sha256=verification["manifest_sha256"],
                holder_id="thread-a",
                lease_token="a" * 32,
                target_state=state,
                now=now + timedelta(seconds=offset),
            )
        failed = MODULE.transition_release_transaction(
            connection,
            version="2.0.0",
            transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            target_state="failed",
            evidence={
                "partial_state": "portal-published-github-pending",
            },
            now=now + timedelta(seconds=6),
        )
        assert failed["state"] == "failed"
        assert failed["last_success_state"] == "portal_published"

        resumed = MODULE.transition_release_transaction(
            connection,
            version="2.0.0",
            transaction_sha256=verification["manifest_sha256"],
            holder_id="thread-a",
            lease_token="a" * 32,
            target_state="github_published",
            now=now + timedelta(seconds=7),
        )
        assert resumed["state"] == "github_published"
        assert resumed["last_success_state"] == "github_published"

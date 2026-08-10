#!/usr/bin/env python3
"""Signed release transaction manifests and cross-task version leases."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


TRANSACTION_SCHEMA = "gongchuang-release-transaction/v1"
SIGNATURE_SCHEMA = "gongchuang-release-transaction-signature/v1"
LEGACY_TRANSACTION_SCHEMA = "jiaotang-release-transaction/v1"
LEGACY_SIGNATURE_SCHEMA = "jiaotang-release-transaction-signature/v1"
SUPPORTED_SCHEMA_PAIRS = {
    TRANSACTION_SCHEMA: SIGNATURE_SCHEMA,
    LEGACY_TRANSACTION_SCHEMA: LEGACY_SIGNATURE_SCHEMA,
}
DEFAULT_LEASE_TTL_SECONDS = 4 * 60 * 60
STATE_SEQUENCE = (
    "leased",
    "github_staged",
    "portal_staged",
    "installing",
    "installed",
    "portal_published",
    "github_published",
    "completed",
)
STATE_RANK = {state: index for index, state in enumerate(STATE_SEQUENCE)}


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    openssh = public_key.public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    )
    blob = base64.b64decode(openssh.split()[1])
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii")
    return "SHA256:" + digest.rstrip("=")


def load_public_key(path: Path) -> tuple[Ed25519PublicKey, str, str]:
    text = path.read_text(encoding="utf-8").strip()
    loaded = serialization.load_ssh_public_key(text.encode("utf-8"))
    if not isinstance(loaded, Ed25519PublicKey):
        raise RuntimeError("发布事务只接受Ed25519公钥")
    return loaded, _public_key_fingerprint(loaded), text


def sign_transaction_manifest(
    manifest: dict[str, Any],
    *,
    private_key_path: Path,
    public_key_path: Path,
) -> tuple[bytes, dict[str, Any], str]:
    if manifest.get("schema") != TRANSACTION_SCHEMA:
        raise RuntimeError("发布事务清单schema不受支持")
    manifest_bytes = canonical_json_bytes(manifest)
    private_key = serialization.load_ssh_private_key(
        private_key_path.read_bytes(),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise RuntimeError("发布事务只接受Ed25519私钥")
    public_key, fingerprint, _ = load_public_key(public_key_path)
    if (
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        != public_key.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ):
        raise RuntimeError("发布事务签名私钥与发布公钥不匹配")
    signature = private_key.sign(manifest_bytes)
    signature_payload = {
        "schema": SIGNATURE_SCHEMA,
        "algorithm": "Ed25519",
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "publisher_fingerprint": fingerprint,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    return manifest_bytes, signature_payload, fingerprint


def verify_transaction_manifest(
    *,
    manifest_bytes: bytes,
    signature_payload: dict[str, Any],
    public_key_text: str,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise RuntimeError("发布事务清单不是有效JSON") from exc
    manifest_schema = manifest.get("schema") if isinstance(manifest, dict) else None
    if manifest_schema not in SUPPORTED_SCHEMA_PAIRS:
        raise RuntimeError("发布事务清单schema不受支持")
    if canonical_json_bytes(manifest) != manifest_bytes:
        raise RuntimeError("发布事务清单不是规范化JSON")
    if signature_payload.get("schema") != SUPPORTED_SCHEMA_PAIRS[manifest_schema]:
        raise RuntimeError("发布事务签名schema不受支持")
    public_key = serialization.load_ssh_public_key(
        public_key_text.strip().encode("utf-8")
    )
    if not isinstance(public_key, Ed25519PublicKey):
        raise RuntimeError("发布事务只接受Ed25519公钥")
    fingerprint = _public_key_fingerprint(public_key)
    declared_fingerprint = str(
        signature_payload.get("publisher_fingerprint") or ""
    )
    if declared_fingerprint != fingerprint:
        raise RuntimeError("发布事务签名公钥指纹不一致")
    if expected_fingerprint and fingerprint != expected_fingerprint:
        raise RuntimeError("发布事务发布者指纹与正式包不一致")
    manifest_sha = sha256_bytes(manifest_bytes)
    if signature_payload.get("manifest_sha256") != manifest_sha:
        raise RuntimeError("发布事务清单哈希与签名元数据不一致")
    try:
        signature = base64.b64decode(
            str(signature_payload.get("signature_base64") or ""),
            validate=True,
        )
        public_key.verify(signature, manifest_bytes)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise RuntimeError("发布事务Ed25519签名无效") from exc
    return {
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "publisher_fingerprint": fingerprint,
        "signature_status": "verified",
    }


def verify_transaction_files(
    *,
    manifest_path: Path,
    signature_path: Path,
    public_key_path: Path,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    signature_payload = json.loads(signature_path.read_text(encoding="utf-8"))
    if not isinstance(signature_payload, dict):
        raise RuntimeError("发布事务签名文件根节点必须是对象")
    public_key_text = public_key_path.read_text(encoding="utf-8")
    return verify_transaction_manifest(
        manifest_bytes=manifest_path.read_bytes(),
        signature_payload=signature_payload,
        public_key_text=public_key_text,
        expected_fingerprint=expected_fingerprint,
    )


def ensure_release_transaction_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS release_transaction_leases(
            version TEXT PRIMARY KEY,
            transaction_sha256 TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            signature_json TEXT NOT NULL,
            publisher_public_key TEXT NOT NULL,
            publisher_fingerprint TEXT NOT NULL,
            holder_id TEXT NOT NULL,
            lease_token_sha256 TEXT NOT NULL,
            state TEXT NOT NULL,
            last_success_state TEXT NOT NULL,
            lease_acquired_at TEXT NOT NULL,
            lease_renewed_at TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(release_transaction_leases)"
        ).fetchall()
    }
    if "last_success_state" not in columns:
        connection.execute(
            """
            ALTER TABLE release_transaction_leases
            ADD COLUMN last_success_state TEXT NOT NULL DEFAULT 'leased'
            """
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS release_transaction_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            transaction_sha256 TEXT NOT NULL,
            holder_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            state TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    if len(token) < 24:
        raise RuntimeError("发布租约令牌长度不足")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _lease_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "version": str(row["version"]),
        "transaction_sha256": str(row["transaction_sha256"]),
        "holder_id": str(row["holder_id"]),
        "state": str(row["state"]),
        "last_success_state": str(row["last_success_state"]),
        "lease_acquired_at": str(row["lease_acquired_at"]),
        "lease_renewed_at": str(row["lease_renewed_at"]),
        "lease_expires_at": str(row["lease_expires_at"]),
        "publisher_fingerprint": str(row["publisher_fingerprint"]),
        "completed_at": row["completed_at"],
        "evidence": json.loads(str(row["evidence_json"] or "{}")),
    }


def _record_event(
    connection: sqlite3.Connection,
    *,
    version: str,
    transaction_sha256: str,
    holder_id: str,
    event_type: str,
    state: str,
    detail: dict[str, Any] | None,
    now: datetime,
) -> None:
    connection.execute(
        """
        INSERT INTO release_transaction_events(
            version,transaction_sha256,holder_id,event_type,state,
            detail_json,created_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            version,
            transaction_sha256,
            holder_id,
            event_type,
            state,
            json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
            now.isoformat(),
        ),
    )


def monitor_release_transaction(
    connection: sqlite3.Connection,
    *,
    version: str,
    observer_id: str = "read-only-observer",
    now: datetime | None = None,
) -> dict[str, Any]:
    ensure_release_transaction_tables(connection)
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM release_transaction_leases WHERE version=?",
        (version,),
    ).fetchone()
    if row is None:
        return {
            "status": "not-found",
            "mode": "read-only-monitor",
            "version": version,
        }
    current = _utc_now(now)
    summary = _lease_summary(row)
    event_rows = connection.execute(
        """
        SELECT holder_id,event_type,state,detail_json,created_at
        FROM release_transaction_events
        WHERE version=?
        ORDER BY id DESC
        LIMIT 50
        """,
        (version,),
    ).fetchall()
    events = [
        {
            "holder_id": str(event["holder_id"]),
            "event_type": str(event["event_type"]),
            "state": str(event["state"]),
            "detail": json.loads(str(event["detail_json"] or "{}")),
            "created_at": str(event["created_at"]),
        }
        for event in reversed(event_rows)
    ]
    summary.update(
        {
            "status": "observed",
            "mode": "read-only-monitor",
            "lease_active": (
                summary["state"] != "completed"
                and _parse_time(summary["lease_expires_at"]) > current
            ),
            "observer_id": observer_id,
            "events": events,
        }
    )
    return summary


def acquire_release_lease(
    connection: sqlite3.Connection,
    *,
    verification: dict[str, Any],
    signature_payload: dict[str, Any],
    public_key_text: str,
    holder_id: str,
    lease_token: str,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    if ttl_seconds < 60 or ttl_seconds > 7 * 24 * 60 * 60:
        raise RuntimeError("发布租约有效期必须在60秒至7天之间")
    manifest = verification["manifest"]
    version = str(manifest.get("version") or "")
    if not version:
        raise RuntimeError("发布事务清单缺少version")
    transaction_sha = str(verification["manifest_sha256"])
    fingerprint = str(verification["publisher_fingerprint"])
    token_hash = _token_hash(lease_token)
    current = _utc_now(now)
    expires = current + timedelta(seconds=ttl_seconds)
    ensure_release_transaction_tables(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM release_transaction_leases WHERE version=?",
            (version,),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO release_transaction_leases(
                    version,transaction_sha256,manifest_json,signature_json,
                    publisher_public_key,publisher_fingerprint,holder_id,
                    lease_token_sha256,state,last_success_state,
                    lease_acquired_at,lease_renewed_at,lease_expires_at,
                    evidence_json,completed_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)
                """,
                (
                    version,
                    transaction_sha,
                    canonical_json_bytes(manifest).decode("utf-8"),
                    json.dumps(
                        signature_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    public_key_text.strip(),
                    fingerprint,
                    holder_id,
                    token_hash,
                    "leased",
                    "leased",
                    current.isoformat(),
                    current.isoformat(),
                    expires.isoformat(),
                    "{}",
                    current.isoformat(),
                ),
            )
            event_type = "lease-acquired"
            status = "acquired"
        else:
            existing_sha = str(row["transaction_sha256"])
            existing_state = str(row["state"])
            active = (
                existing_state != "completed"
                and _parse_time(str(row["lease_expires_at"])) > current
            )
            same_holder = str(row["holder_id"]) == holder_id
            token_matches = str(row["lease_token_sha256"]) == token_hash
            if existing_state == "completed":
                connection.rollback()
                result = monitor_release_transaction(
                    connection,
                    version=version,
                    observer_id=holder_id,
                    now=current,
                )
                result.update(
                    {
                        "status": "completed",
                        "mode": "read-only-monitor",
                        "lease_active": False,
                    }
                )
                return result
            if existing_sha != transaction_sha:
                if active:
                    connection.rollback()
                    result = monitor_release_transaction(
                        connection,
                        version=version,
                        observer_id=holder_id,
                        now=current,
                    )
                    result.update(
                        {
                            "status": "held-by-other-task",
                            "mode": "read-only-monitor",
                            "lease_active": True,
                            "requested_transaction_sha256": transaction_sha,
                        }
                    )
                    return result
                raise RuntimeError(
                    "同一版本已绑定不同的签名发布事务，禁止过期后静默换包"
                )
            if active and not (same_holder and token_matches):
                connection.rollback()
                result = monitor_release_transaction(
                    connection,
                    version=version,
                    observer_id=holder_id,
                    now=current,
                )
                result.update(
                    {
                        "status": "held-by-other-task",
                        "mode": "read-only-monitor",
                        "lease_active": True,
                    }
                )
                return result
            if active:
                event_type = "lease-renewed"
                status = "renewed"
            else:
                event_type = "lease-taken-over"
                status = "taken-over"
            next_state = existing_state
            connection.execute(
                """
                UPDATE release_transaction_leases
                SET holder_id=?,lease_token_sha256=?,state=?,
                    lease_renewed_at=?,lease_expires_at=?,updated_at=?
                WHERE version=? AND transaction_sha256=?
                """,
                (
                    holder_id,
                    token_hash,
                    next_state,
                    current.isoformat(),
                    expires.isoformat(),
                    current.isoformat(),
                    version,
                    transaction_sha,
                ),
            )
        _record_event(
            connection,
            version=version,
            transaction_sha256=transaction_sha,
            holder_id=holder_id,
            event_type=event_type,
            state=(
                "leased"
                if row is None
                else str(row["state"])
            ),
            detail={"ttl_seconds": ttl_seconds},
            now=current,
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    result = monitor_release_transaction(
        connection,
        version=version,
        observer_id=holder_id,
        now=current,
    )
    result.update(
        {
            "status": status,
            "mode": "writer",
            "lease_active": True,
        }
    )
    return result


def supersede_failed_release_transaction(
    connection: sqlite3.Connection,
    *,
    verification: dict[str, Any],
    signature_payload: dict[str, Any],
    public_key_text: str,
    previous_transaction_sha256: str,
    holder_id: str,
    lease_token: str,
    evidence: dict[str, Any],
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Replace an early failed transaction without erasing its audit trail."""
    if ttl_seconds < 60 or ttl_seconds > 7 * 24 * 60 * 60:
        raise RuntimeError("发布租约有效期必须在60秒至7天之间")
    required_evidence = {
        "reason": lambda value: isinstance(value, str) and bool(value.strip()),
        "github_prerelease_removed": lambda value: value is True,
        "portal_release_absent": lambda value: value is True,
    }
    if any(not check(evidence.get(key)) for key, check in required_evidence.items()):
        raise RuntimeError("替换失败事务缺少旧预发布撤销、门户无记录或原因证据")

    manifest = verification["manifest"]
    version = str(manifest.get("version") or "")
    replacement_sha = str(verification["manifest_sha256"])
    if not version or replacement_sha == previous_transaction_sha256:
        raise RuntimeError("替换事务必须是同版本的不同签名事务")
    current = _utc_now(now)
    expires = current + timedelta(seconds=ttl_seconds)
    token_hash = _token_hash(lease_token)
    ensure_release_transaction_tables(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM release_transaction_leases WHERE version=?",
            (version,),
        ).fetchone()
        if row is None:
            raise RuntimeError("待替换的失败发布事务不存在")
        if str(row["transaction_sha256"]) != previous_transaction_sha256:
            raise RuntimeError("待替换事务哈希与服务器记录不一致")
        if str(row["state"]) != "failed":
            raise RuntimeError("只有明确失败的发布事务可以被替换")
        if str(row["last_success_state"]) not in {"leased", "github_staged"}:
            raise RuntimeError("门户已进入暂存或发布阶段，禁止替换签名事务")
        if (
            str(row["holder_id"]) != holder_id
            or str(row["lease_token_sha256"]) != token_hash
        ):
            raise RuntimeError("只有原失败事务租约持有者可以执行替换")

        for table in (
            "skill_releases",
            "skill_release_stages",
            "skill_release_stage_artifacts",
            "skill_release_artifact_stages",
        ):
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists and connection.execute(
                f"SELECT 1 FROM {table} WHERE version=? LIMIT 1",
                (version,),
            ).fetchone():
                raise RuntimeError("门户已有该版本记录，禁止替换签名事务")

        _record_event(
            connection,
            version=version,
            transaction_sha256=previous_transaction_sha256,
            holder_id=holder_id,
            event_type="transaction-superseded",
            state="failed",
            detail={
                "replacement_transaction_sha256": replacement_sha,
                "evidence": evidence,
            },
            now=current,
        )
        replacement_evidence = {
            "supersedes": {
                "transaction_sha256": previous_transaction_sha256,
                **evidence,
            }
        }
        connection.execute(
            """
            UPDATE release_transaction_leases
            SET transaction_sha256=?,manifest_json=?,signature_json=?,
                publisher_public_key=?,publisher_fingerprint=?,state='leased',
                last_success_state='leased',lease_acquired_at=?,
                lease_renewed_at=?,lease_expires_at=?,evidence_json=?,
                completed_at=NULL,updated_at=?
            WHERE version=? AND transaction_sha256=?
            """,
            (
                replacement_sha,
                canonical_json_bytes(manifest).decode("utf-8"),
                json.dumps(signature_payload, ensure_ascii=False, sort_keys=True),
                public_key_text.strip(),
                str(verification["publisher_fingerprint"]),
                current.isoformat(),
                current.isoformat(),
                expires.isoformat(),
                json.dumps(replacement_evidence, ensure_ascii=False, sort_keys=True),
                current.isoformat(),
                version,
                previous_transaction_sha256,
            ),
        )
        _record_event(
            connection,
            version=version,
            transaction_sha256=replacement_sha,
            holder_id=holder_id,
            event_type="lease-acquired-after-supersede",
            state="leased",
            detail={"previous_transaction_sha256": previous_transaction_sha256},
            now=current,
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    result = monitor_release_transaction(
        connection,
        version=version,
        observer_id=holder_id,
        now=current,
    )
    result.update({"status": "superseded", "mode": "writer"})
    return result


def transition_release_transaction(
    connection: sqlite3.Connection,
    *,
    version: str,
    transaction_sha256: str,
    holder_id: str,
    lease_token: str,
    target_state: str,
    evidence: dict[str, Any] | None = None,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    if target_state not in {*STATE_SEQUENCE, "failed"}:
        raise RuntimeError(f"不支持的发布事务状态：{target_state}")
    current = _utc_now(now)
    token_hash = _token_hash(lease_token)
    ensure_release_transaction_tables(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM release_transaction_leases WHERE version=?",
            (version,),
        ).fetchone()
        if row is None:
            raise RuntimeError("发布事务租约不存在")
        if str(row["transaction_sha256"]) != transaction_sha256:
            raise RuntimeError("发布事务哈希与租约不一致")
        if (
            str(row["holder_id"]) != holder_id
            or str(row["lease_token_sha256"]) != token_hash
        ):
            raise RuntimeError("当前任务不是该版本发布租约持有者")
        if (
            str(row["state"]) != "completed"
            and _parse_time(str(row["lease_expires_at"])) <= current
        ):
            raise RuntimeError("发布租约已过期，请先重新取得同一事务租约")
        current_state = str(row["state"])
        if current_state == "completed" and target_state != "completed":
            raise RuntimeError("已完成的发布事务不能回退")
        last_success_state = str(row["last_success_state"])
        if target_state != "failed":
            base_state = (
                last_success_state
                if current_state == "failed"
                else current_state
            )
            current_rank = STATE_RANK[base_state]
            target_rank = STATE_RANK[target_state]
            if target_rank > current_rank + 1:
                raise RuntimeError(
                    f"发布事务状态不能从{base_state}跳到{target_state}"
                )
            effective_state = (
                base_state if target_rank <= current_rank else target_state
            )
            effective_last_success_state = effective_state
        else:
            effective_state = "failed"
            effective_last_success_state = (
                last_success_state
                if current_state == "failed"
                else current_state
            )
        existing_evidence = json.loads(str(row["evidence_json"] or "{}"))
        if evidence:
            existing_evidence[target_state] = evidence
        expires = current + timedelta(seconds=ttl_seconds)
        completed_at = (
            current.isoformat()
            if effective_state == "completed"
            else row["completed_at"]
        )
        connection.execute(
            """
            UPDATE release_transaction_leases
            SET state=?,last_success_state=?,lease_renewed_at=?,lease_expires_at=?,
                evidence_json=?,completed_at=?,updated_at=?
            WHERE version=? AND transaction_sha256=?
            """,
            (
                effective_state,
                effective_last_success_state,
                current.isoformat(),
                expires.isoformat(),
                json.dumps(
                    existing_evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                completed_at,
                current.isoformat(),
                version,
                transaction_sha256,
            ),
        )
        _record_event(
            connection,
            version=version,
            transaction_sha256=transaction_sha256,
            holder_id=holder_id,
            event_type="state-transition",
            state=effective_state,
            detail={
                "requested_state": target_state,
                "evidence": evidence or {},
            },
            now=current,
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    result = monitor_release_transaction(
        connection,
        version=version,
        observer_id=holder_id,
        now=current,
    )
    result.update({"status": "transitioned", "mode": "writer"})
    return result

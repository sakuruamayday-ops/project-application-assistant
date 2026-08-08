#!/usr/bin/env python3
"""Production control plane for signed weekly policy-index increments.

The logical SQLite mutation stays in ``policy_increment_delta.py``.  This module
adds the production-only state machine: an exact complete baseline, immutable
OSS delta packages, an Ed25519-signed chain pointer, and finalization only after
an independently written deployment receipt is verified.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import oss2
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

try:
    from scripts.oss_auth import build_bucket
    from scripts.policy_increment_delta import (
        PolicyIncrementError,
        build_base_anchor,
        build_package,
        canonical_json_bytes,
        clone_file,
        generate_key,
        load_private_key,
        load_public_key,
        public_key_id,
        sha256_file,
        verify_base_anchor,
        verify_package,
    )
    from scripts.publish_index_to_oss import (
        MANIFEST_SCHEMA,
        PRODUCTION_FILES,
        prepare_release_files,
    )
except ImportError:  # direct script execution
    from oss_auth import build_bucket
    from policy_increment_delta import (
        PolicyIncrementError,
        build_base_anchor,
        build_package,
        canonical_json_bytes,
        clone_file,
        generate_key,
        load_private_key,
        load_public_key,
        public_key_id,
        sha256_file,
        verify_base_anchor,
        verify_package,
    )
    from publish_index_to_oss import MANIFEST_SCHEMA, PRODUCTION_FILES, prepare_release_files


STATE_SCHEMA = "jiaotang-policy-increment-state/v1"
POINTER_SCHEMA = "jiaotang-policy-increment-pointer/v1"
PREPARED_SCHEMA = "jiaotang-policy-increment-prepared/v1"
RECEIPT_SCHEMA = "jiaotang-policy-increment-deployment-receipt/v1"
DEFAULT_STATE_ROOT = Path("/Users/zsh/JiaotangData/索引/policy-increment-chain")
DEFAULT_PRIVATE_KEY = Path(
    "/Users/zsh/.config/project-assistant/policy-increment-chain/ed25519-private.pem"
)
DEFAULT_PUBLIC_KEY = Path(
    "/Users/zsh/.config/project-assistant/policy-increment-chain/ed25519-public.pem"
)
DEFAULT_KNOWLEDGE_ROOT = Path("/Users/zsh/JiaotangData/知识库")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any], *, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_bytes(canonical_json_bytes(payload))
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyIncrementError(f"{label}不可用：{path}") from error
    if not isinstance(payload, dict):
        raise PolicyIncrementError(f"{label}必须是JSON对象：{path}")
    return payload


def require_sha256(value: object, label: str) -> str:
    digest = str(value or "")
    if not SHA256_RE.fullmatch(digest):
        raise PolicyIncrementError(f"{label}不是合法SHA-256")
    return digest


def source_identity(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(stat.st_ctime_ns),
    )


def clone_production_files(source: Path, target: Path) -> None:
    if target.exists():
        raise PolicyIncrementError(f"完整基线目标已存在，拒绝覆盖：{target}")
    target.mkdir(parents=True)
    for name in PRODUCTION_FILES:
        path = source / name
        if not path.is_file():
            raise PolicyIncrementError(f"完整基线缺少生产文件：{name}")
        clone_file(path, target / name)


def verify_against_release(index_dir: Path, release_path: Path) -> dict[str, Any]:
    release = load_json(release_path, "生产release.json")
    if release.get("schema") != MANIFEST_SCHEMA:
        raise PolicyIncrementError("生产release.json schema不受支持")
    rows = release.get("files")
    if not isinstance(rows, list):
        raise PolicyIncrementError("生产release.json缺少files")
    expected_names = [str(row.get("name") or "") for row in rows if isinstance(row, dict)]
    if expected_names != list(PRODUCTION_FILES):
        raise PolicyIncrementError("生产release文件白名单与当前运行时不一致")
    results: list[dict[str, Any]] = []
    for row in rows:
        assert isinstance(row, dict)
        name = str(row["name"])
        path = index_dir / name
        status = "missing"
        actual = ""
        if path.is_file():
            actual = sha256_file(path)
            status = (
                "exact"
                if path.stat().st_size == int(row["size"]) and actual == str(row["sha256"])
                else "mismatch"
            )
        results.append({"name": name, "status": status, "sha256": actual})
    if any(row["status"] != "exact" for row in results):
        raise PolicyIncrementError(f"完整生产基线并非逐文件exact：{results}")
    return release


def state_path(root: Path) -> Path:
    return root / "state.json"


def load_state(root: Path) -> dict[str, Any]:
    state = load_json(state_path(root), "增量链状态")
    if state.get("schema") != STATE_SCHEMA:
        raise PolicyIncrementError("增量链状态schema不受支持")
    return state


def sign_document(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop("signature_base64", None)
    body = canonical_json_bytes(unsigned)
    return unsigned | {"signature_base64": base64.b64encode(private_key.sign(body)).decode("ascii")}


def verify_signed_document(payload: dict[str, Any], public_key: Ed25519PublicKey) -> None:
    signed = dict(payload)
    try:
        signature = base64.b64decode(str(signed.pop("signature_base64")), validate=True)
    except Exception as error:
        raise PolicyIncrementError("签名文档缺少合法signature_base64") from error
    public_key.verify(signature, canonical_json_bytes(signed))


def pointer_for_state(state: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    payload = {
        "schema": POINTER_SCHEMA,
        "updated_at": state.get("updated_at") or state.get("created_at") or utc_now(),
        "key_id": state["key_id"],
        "base_release_id": state["base_release_id"],
        "base_index_sha256": state["base_index_sha256"],
        "base_manifest_sha256": state["base_manifest_sha256"],
        "base_chain_sha256": state["base_chain_sha256"],
        "current_release_id": state["current_release_id"],
        "current_chain_sha256": state["current_chain_sha256"],
        "current_index_sha256": state["current_index_sha256"],
        "current_manifest_sha256": state["current_manifest_sha256"],
        "chain_length": len(state.get("entries", [])),
        "entries": state.get("entries", []),
    }
    return sign_document(payload, private_key)


def command_initialize(args: argparse.Namespace) -> dict[str, Any]:
    root = args.state_root.expanduser().resolve()
    if state_path(root).exists():
        state = load_state(root)
        return {"status": "existing", "state": state}
    baseline_source = args.baseline_index_dir.expanduser().resolve()
    release = verify_against_release(baseline_source, args.base_release_json.expanduser().resolve())
    release_id = str(release.get("release_id") or "")
    if not release_id or release_id != args.base_release_id:
        raise PolicyIncrementError("生产基线release_id与显式参数不一致")
    private_path = args.private_key.expanduser().resolve()
    public_path = args.public_key.expanduser().resolve()
    if not private_path.exists() and not public_path.exists():
        generate_key(private_path, public_path)
    elif not private_path.is_file() or not public_path.is_file():
        raise PolicyIncrementError("增量链公私钥必须同时存在")
    private_key = load_private_key(private_path)
    public_key = load_public_key(public_path)
    if public_key_id(private_key.public_key()) != public_key_id(public_key):
        raise PolicyIncrementError("增量链公私钥不匹配")
    baseline_dir = root / "baselines" / release_id / "index"
    anchor_dir = root / "baselines" / release_id / "anchor"
    clone_production_files(baseline_source, baseline_dir)
    shutil.copy2(args.base_release_json.expanduser().resolve(), baseline_dir / "release.json")
    anchor = build_base_anchor(
        baseline_dir / "knowledge_content.sqlite3",
        baseline_dir / "manifest.jsonl",
        anchor_dir,
        private_path,
    )
    verified = verify_base_anchor(
        anchor_dir,
        baseline_dir / "knowledge_content.sqlite3",
        baseline_dir / "manifest.jsonl",
        public_path,
    )
    base_chain = str(verified["signature"]["chain_sha256"])
    state = {
        "schema": STATE_SCHEMA,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "state_root": str(root),
        "key_id": public_key_id(public_key),
        "trusted_public_key": str(public_path),
        "base_release_id": release_id,
        "base_index_dir": str(baseline_dir),
        "base_anchor_dir": str(anchor_dir),
        "base_index_sha256": sha256_file(baseline_dir / "knowledge_content.sqlite3"),
        "base_manifest_sha256": sha256_file(baseline_dir / "manifest.jsonl"),
        "base_chain_sha256": base_chain,
        "current_release_id": release_id,
        "current_index_dir": str(baseline_dir),
        "current_index_sha256": sha256_file(baseline_dir / "knowledge_content.sqlite3"),
        "current_manifest_sha256": sha256_file(baseline_dir / "manifest.jsonl"),
        "current_chain_sha256": base_chain,
        "entries": [],
    }
    write_json(state_path(root), state)
    pointer = pointer_for_state(state, private_key)
    write_json(root / "base-pointer.json", pointer)
    return {"status": "initialized", "state": state, "anchor": anchor}


def verify_current_state(state: dict[str, Any], public_key: Path) -> Path:
    index_dir = Path(str(state["current_index_dir"])).resolve()
    if sha256_file(index_dir / "knowledge_content.sqlite3") != state["current_index_sha256"]:
        raise PolicyIncrementError("增量链当前SQLite已漂移")
    if sha256_file(index_dir / "manifest.jsonl") != state["current_manifest_sha256"]:
        raise PolicyIncrementError("增量链当前manifest已漂移")
    if not state.get("entries"):
        verify_base_anchor(
            Path(str(state["base_anchor_dir"])),
            index_dir / "knowledge_content.sqlite3",
            index_dir / "manifest.jsonl",
            public_key,
        )
    return index_dir


def create_upload_files(package_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    payload = load_json(package_dir / "delta_payload.json", "增量payload")
    rows = payload.get("manifest_rows")
    if not isinstance(rows, list):
        raise PolicyIncrementError("增量payload缺少manifest_rows")
    manifest_path = output_dir / "delta-upload-manifest.jsonl"
    with manifest_path.open("wb") as stream:
        for row in rows:
            if not isinstance(row, dict):
                raise PolicyIncrementError("增量manifest_rows存在非对象")
            stream.write(canonical_json_bytes(row))
    allowlist_path = output_dir / "delta-upload-allowlist.csv"
    with allowlist_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("relative_path", "sha256", "object_storage_allowed"),
        )
        writer.writeheader()
        for row in rows:
            assert isinstance(row, dict)
            writer.writerow(
                {
                    "relative_path": row["relative_path"],
                    "sha256": row["sha256"],
                    "object_storage_allowed": "true",
                }
            )
    return manifest_path, allowlist_path


def command_prepare(args: argparse.Namespace) -> dict[str, Any]:
    root = args.state_root.expanduser().resolve()
    state = load_state(root)
    public_path = Path(str(state["trusted_public_key"]))
    current_index = verify_current_state(state, public_path)
    handoff_id = load_json(
        args.handoff_dir.expanduser().resolve() / "increment_handoff.json",
        "冻结交接包",
    ).get("handoff_id")
    if any(str(entry.get("handoff_id")) == str(handoff_id) for entry in state.get("entries", [])):
        raise PolicyIncrementError(f"handoff已经发布：{handoff_id}")
    run_dir = args.run_dir.expanduser().resolve()
    if run_dir.exists():
        raise PolicyIncrementError(f"发布运行目录已存在，拒绝覆盖：{run_dir}")
    run_dir.mkdir(parents=True)
    raw_candidate = run_dir / "candidate-index"
    package_dir = run_dir / "delta-package"
    namespace = argparse.Namespace(
        handoff_dir=args.handoff_dir,
        knowledge_root=args.knowledge_root,
        base_db=current_index / "knowledge_content.sqlite3",
        base_manifest=current_index / "manifest.jsonl",
        candidate_dir=raw_candidate,
        package_dir=package_dir,
        signing_private_key=args.private_key,
        previous_chain_sha256=state["current_chain_sha256"],
    )
    result = build_package(namespace)
    delta_manifest = load_json(package_dir / "delta_manifest.json", "增量manifest")
    event_time = str(delta_manifest.get("generated_at") or "")
    if not event_time:
        raise PolicyIncrementError("增量manifest缺少确定性generated_at")
    for name in PRODUCTION_FILES:
        target = raw_candidate / name
        if target.exists():
            continue
        clone_file(current_index / name, target)
    files, _ = prepare_release_files(raw_candidate, prevalidated=True)
    chain_sha = require_sha256(result["chain_sha256"], "新链摘要")
    release_id = f"policy-{chain_sha[:40]}"
    policy_root = (
        os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
        + "/index/policy-increment/v1"
    )
    entry = {
        "sequence": len(state.get("entries", [])) + 1,
        "handoff_id": str(handoff_id),
        "release_id": release_id,
        "chain_sha256": chain_sha,
        "previous_chain_sha256": state["current_chain_sha256"],
        "candidate_index_sha256": result["candidate_index_sha256"],
        "candidate_manifest_sha256": result["candidate_manifest_sha256"],
        "delta_prefix": f"{policy_root}/deltas/{chain_sha}",
        "published_at": event_time,
    }
    release = {
        "schema": MANIFEST_SCHEMA,
        "release_id": release_id,
        "created_at": event_time,
        "previous_release_id": state["current_release_id"],
        "files": [metadata for _, metadata in files],
        "file_whitelist": list(PRODUCTION_FILES),
        "storage_mode": "signed-policy-delta-chain-v1",
        "base_release_id": state["base_release_id"],
        "incremental_overlay": entry,
        "baseline_companion_files_unchanged": [
            name
            for name in PRODUCTION_FILES
            if name not in {"knowledge_content.sqlite3", "manifest.jsonl"}
        ],
    }
    write_json(raw_candidate / "release.json", release)
    shutil.copy2(raw_candidate / "release.json", package_dir / "release.json")
    upload_manifest, upload_allowlist = create_upload_files(package_dir, run_dir)
    new_state = dict(state)
    new_state.update(
        {
            "updated_at": event_time,
            "current_release_id": release_id,
            "current_index_dir": str(raw_candidate),
            "current_index_sha256": result["candidate_index_sha256"],
            "current_manifest_sha256": result["candidate_manifest_sha256"],
            "current_chain_sha256": chain_sha,
            "entries": [*state.get("entries", []), entry],
        }
    )
    private_key = load_private_key(args.private_key.expanduser().resolve())
    pointer = pointer_for_state(new_state, private_key)
    previous_pointer = pointer_for_state(state, private_key)
    write_json(run_dir / "pending-state.json", new_state)
    write_json(run_dir / "chain-pointer.json", pointer)
    write_json(run_dir / "previous-chain-pointer.json", previous_pointer)
    prepared = {
        "schema": PREPARED_SCHEMA,
        "prepared_at": utc_now(),
        "state_root": str(root),
        "run_dir": str(run_dir),
        "handoff_dir": str(args.handoff_dir.expanduser().resolve()),
        "handoff_id": str(handoff_id),
        "candidate_index_dir": str(raw_candidate),
        "package_dir": str(package_dir),
        "release_id": release_id,
        "previous_release_id": state["current_release_id"],
        "chain_sha256": chain_sha,
        "previous_chain_sha256": state["current_chain_sha256"],
        "candidate_index_sha256": result["candidate_index_sha256"],
        "candidate_manifest_sha256": result["candidate_manifest_sha256"],
        "upload_manifest": str(upload_manifest),
        "upload_allowlist": str(upload_allowlist),
        "policy_root": policy_root,
        "delta_prefix": entry["delta_prefix"],
        "pointer_path": str(run_dir / "chain-pointer.json"),
        "previous_pointer_path": str(run_dir / "previous-chain-pointer.json"),
        "pending_state_path": str(run_dir / "pending-state.json"),
        "trusted_public_key": state["trusted_public_key"],
        "base_release_id": state["base_release_id"],
        "base_anchor_dir": state["base_anchor_dir"],
        "counts": result["counts"],
        "validation": result["validation"],
    }
    write_json(run_dir / "prepared-release.json", prepared)
    return prepared


def immutable_head(bucket: object, key: str) -> object | None:
    try:
        return bucket.head_object(key)
    except oss2.exceptions.NoSuchKey:
        return None


def put_immutable_bytes(bucket: object, key: str, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    remote = immutable_head(bucket, key)
    if remote is not None:
        if (
            int(remote.content_length) != len(payload)
            or str(remote.headers.get("x-oss-meta-sha256", "")) != digest
            or bucket.get_object(key).read() != payload
        ):
            raise PolicyIncrementError(f"OSS不可变对象冲突：{key}")
        return "existing"
    bucket.put_object(
        key,
        payload,
        headers={
            "x-oss-forbid-overwrite": "true",
            "x-oss-meta-sha256": digest,
            "x-oss-meta-source-size": str(len(payload)),
        },
    )
    confirmed = bucket.head_object(key)
    if (
        int(confirmed.content_length) != len(payload)
        or str(confirmed.headers.get("x-oss-meta-sha256", "")) != digest
    ):
        raise PolicyIncrementError(f"OSS不可变对象上传后复核失败：{key}")
    return "uploaded"


def put_immutable_file(bucket: object, key: str, path: Path) -> str:
    identity = source_identity(path)
    payload = path.read_bytes()
    if source_identity(path) != identity:
        raise PolicyIncrementError(f"读取期间文件发生变化：{path}")
    return put_immutable_bytes(bucket, key, payload)


def put_or_verify_transition(bucket: object, key: str, payload: dict[str, Any]) -> str:
    remote = immutable_head(bucket, key)
    if remote is None:
        return put_immutable_bytes(bucket, key, canonical_json_bytes(payload))
    raw = bucket.get_object(key).read()
    digest = hashlib.sha256(raw).hexdigest()
    if (
        int(remote.content_length) != len(raw)
        or str(remote.headers.get("x-oss-meta-sha256", "")) != digest
    ):
        raise PolicyIncrementError(f"OSS迁移凭证身份异常：{key}")
    try:
        existing = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise PolicyIncrementError(f"OSS迁移凭证不是有效JSON：{key}") from exc
    semantic_fields = (
        "schema",
        "reason",
        "expected_chain_sha256",
        "target_chain_sha256",
        "target_pointer_sha256",
    )
    if not isinstance(existing, dict) or any(
        existing.get(field) != payload.get(field) for field in semantic_fields
    ):
        raise PolicyIncrementError(f"OSS不可变迁移凭证冲突：{key}")
    return "existing"


def prepared_payload(path: Path) -> dict[str, Any]:
    payload = load_json(path.expanduser().resolve(), "prepared-release")
    if payload.get("schema") != PREPARED_SCHEMA:
        raise PolicyIncrementError("prepared-release schema不受支持")
    return payload


def verify_pointer_file(path: Path, public_path: Path) -> dict[str, Any]:
    payload = load_json(path, "增量链指针")
    if payload.get("schema") != POINTER_SCHEMA:
        raise PolicyIncrementError("增量链指针schema不受支持")
    public_key = load_public_key(public_path)
    if payload.get("key_id") != public_key_id(public_key):
        raise PolicyIncrementError("增量链指针key_id不匹配")
    verify_signed_document(payload, public_key)
    return payload


def command_upload_immutable(args: argparse.Namespace) -> dict[str, Any]:
    prepared = prepared_payload(args.prepared)
    bucket = build_bucket()
    public_path = Path(str(prepared["trusted_public_key"]))
    pointer = verify_pointer_file(Path(str(prepared["pointer_path"])), public_path)
    package_dir = Path(str(prepared["package_dir"]))
    verify_package(
        package_dir,
        public_path,
        str(prepared["previous_chain_sha256"]),
    )
    uploaded = existing = 0
    delta_prefix = str(prepared["delta_prefix"])
    for path in sorted(item for item in package_dir.iterdir() if item.is_file()):
        status = put_immutable_file(bucket, f"{delta_prefix}/{path.name}", path)
        uploaded += int(status == "uploaded")
        existing += int(status == "existing")
    state = load_state(Path(str(prepared["state_root"])))
    base_prefix = f"{prepared['policy_root']}/bases/{prepared['base_release_id']}"
    for path in sorted(Path(str(prepared["base_anchor_dir"])).iterdir()):
        if path.is_file():
            status = put_immutable_file(bucket, f"{base_prefix}/anchor/{path.name}", path)
            uploaded += int(status == "uploaded")
            existing += int(status == "existing")
    status = put_immutable_file(bucket, f"{base_prefix}/trusted-public.pem", public_path)
    uploaded += int(status == "uploaded")
    existing += int(status == "existing")
    history_key = f"{prepared['policy_root']}/pointers/{prepared['chain_sha256']}.json"
    status = put_immutable_bytes(bucket, history_key, canonical_json_bytes(pointer))
    uploaded += int(status == "uploaded")
    existing += int(status == "existing")
    base_pointer = verify_pointer_file(
        Path(str(prepared["previous_pointer_path"])), public_path
    )
    current_key = f"{prepared['policy_root']}/current.json"
    remote = immutable_head(bucket, current_key)
    if remote is None and not state.get("entries"):
        put_immutable_bytes(bucket, current_key, canonical_json_bytes(base_pointer))
    return {
        "uploaded": uploaded,
        "existing": existing,
        "delta_prefix": delta_prefix,
        "history_key": history_key,
    }


def remote_pointer(bucket: object, key: str, public_path: Path) -> dict[str, Any] | None:
    if immutable_head(bucket, key) is None:
        return None
    payload = json.loads(bucket.get_object(key).read())
    if not isinstance(payload, dict):
        raise PolicyIncrementError("OSS current增量链指针不是对象")
    public_key = load_public_key(public_path)
    if payload.get("key_id") != public_key_id(public_key):
        raise PolicyIncrementError("OSS current增量链指针key_id不匹配")
    verify_signed_document(payload, public_key)
    return payload


def overwrite_current_pointer(
    bucket: object,
    key: str,
    target: dict[str, Any],
    *,
    expected_chain_sha256: str,
    policy_root: str,
    reason: str,
) -> dict[str, Any]:
    current = remote_pointer(bucket, key, Path(os.environ["JIAOTANG_POLICY_TRUSTED_PUBLIC_KEY"]))
    actual = str(current.get("current_chain_sha256") or "") if current else ""
    if actual == str(target["current_chain_sha256"]):
        if current != target:
            raise PolicyIncrementError("OSS current已使用目标链摘要但指针内容不一致")
        return {"status": "unchanged", "previous": actual, "current": actual}
    if actual != expected_chain_sha256:
        raise PolicyIncrementError(
            f"OSS增量链CAS冲突：预期{expected_chain_sha256}，实际{actual or '不存在'}"
        )
    transition = {
        "schema": "jiaotang-policy-increment-transition/v1",
        "created_at": str(target.get("updated_at") or utc_now()),
        "reason": reason,
        "expected_chain_sha256": expected_chain_sha256,
        "target_chain_sha256": target["current_chain_sha256"],
        "target_pointer_sha256": hashlib.sha256(canonical_json_bytes(target)).hexdigest(),
    }
    transition_key = (
        f"{policy_root}/transitions/{expected_chain_sha256}/"
        f"{target['current_chain_sha256']}.json"
    )
    put_or_verify_transition(bucket, transition_key, transition)
    confirmed = remote_pointer(bucket, key, Path(os.environ["JIAOTANG_POLICY_TRUSTED_PUBLIC_KEY"]))
    confirmed_chain = str(confirmed.get("current_chain_sha256") or "") if confirmed else ""
    if confirmed_chain != expected_chain_sha256:
        raise PolicyIncrementError("OSS增量链指针在切换前发生并发变化")
    body = canonical_json_bytes(target)
    bucket.put_object(
        key,
        body,
        headers={
            "x-oss-meta-sha256": hashlib.sha256(body).hexdigest(),
            "x-oss-meta-chain-sha256": str(target["current_chain_sha256"]),
        },
    )
    final = remote_pointer(bucket, key, Path(os.environ["JIAOTANG_POLICY_TRUSTED_PUBLIC_KEY"]))
    if final != target:
        raise PolicyIncrementError("OSS增量链current切换后复核失败")
    return {
        "status": "switched",
        "previous": expected_chain_sha256,
        "current": target["current_chain_sha256"],
    }


def command_switch_pointer(args: argparse.Namespace, *, rollback: bool = False) -> dict[str, Any]:
    prepared = prepared_payload(args.prepared)
    public_path = Path(str(prepared["trusted_public_key"]))
    os.environ["JIAOTANG_POLICY_TRUSTED_PUBLIC_KEY"] = str(public_path)
    target_path = Path(
        str(prepared["previous_pointer_path"] if rollback else prepared["pointer_path"])
    )
    target = verify_pointer_file(target_path, public_path)
    expected = str(
        prepared["chain_sha256"] if rollback else prepared["previous_chain_sha256"]
    )
    bucket = build_bucket()
    key = f"{prepared['policy_root']}/current.json"
    result = overwrite_current_pointer(
        bucket,
        key,
        target,
        expected_chain_sha256=expected,
        policy_root=str(prepared["policy_root"]),
        reason="rollback" if rollback else "weekly-policy-release",
    )
    receipt_path = Path(str(prepared["run_dir"])) / (
        "cloud-rollback-receipt.json" if rollback else "cloud-pointer-receipt.json"
    )
    write_json(receipt_path, {"at": utc_now(), **result})
    return result


def command_verify_cloud(args: argparse.Namespace) -> dict[str, Any]:
    prepared = prepared_payload(args.prepared)
    public_path = Path(str(prepared["trusted_public_key"]))
    bucket = build_bucket()
    current = remote_pointer(
        bucket,
        f"{prepared['policy_root']}/current.json",
        public_path,
    )
    if not current or current.get("current_chain_sha256") != prepared["chain_sha256"]:
        raise PolicyIncrementError("OSS增量链current未指向本轮")
    delta_prefix = str(prepared["delta_prefix"])
    errors: list[str] = []
    for path in sorted(Path(str(prepared["package_dir"])).iterdir()):
        if not path.is_file():
            continue
        key = f"{delta_prefix}/{path.name}"
        remote = immutable_head(bucket, key)
        if remote is None:
            errors.append(f"missing:{key}")
        elif (
            int(remote.content_length) != path.stat().st_size
            or str(remote.headers.get("x-oss-meta-sha256", "")) != sha256_file(path)
        ):
            errors.append(f"mismatch:{key}")
    if errors:
        raise PolicyIncrementError(f"OSS增量包二次校验失败：{errors[:10]}")
    return {
        "status": "exact",
        "chain_sha256": prepared["chain_sha256"],
        "package_files": len([p for p in Path(str(prepared["package_dir"])).iterdir() if p.is_file()]),
    }


def command_finalize(args: argparse.Namespace) -> dict[str, Any]:
    prepared = prepared_payload(args.prepared)
    receipt = load_json(args.receipt.expanduser().resolve(), "生产部署回执")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise PolicyIncrementError("生产部署回执schema不受支持")
    required = {
        "release_id": prepared["release_id"],
        "chain_sha256": prepared["chain_sha256"],
        "candidate_index_sha256": prepared["candidate_index_sha256"],
        "candidate_manifest_sha256": prepared["candidate_manifest_sha256"],
        "server_status": "healthy",
        "cloud_status": "exact",
        "rest_status": "pass",
        "mcp_status": "pass",
    }
    mismatches = {
        key: {"expected": expected, "actual": receipt.get(key)}
        for key, expected in required.items()
        if receipt.get(key) != expected
    }
    if mismatches:
        raise PolicyIncrementError(f"生产部署回执未满足finalize门禁：{mismatches}")
    root = Path(str(prepared["state_root"]))
    current = load_state(root)
    if current["current_chain_sha256"] != prepared["previous_chain_sha256"]:
        raise PolicyIncrementError("finalize前本地链状态已变化")
    pending = load_json(Path(str(prepared["pending_state_path"])), "pending-state")
    if pending["current_chain_sha256"] != prepared["chain_sha256"]:
        raise PolicyIncrementError("pending-state链摘要不一致")
    write_json(state_path(root), pending)
    write_json(
        Path(str(prepared["run_dir"])) / "finalization.json",
        {"status": "finalized", "at": utc_now(), "receipt_sha256": sha256_file(args.receipt)},
    )
    return {"status": "finalized", "state": pending}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="政策冻结交接包的生产增量发布控制面")
    sub = result.add_subparsers(dest="command", required=True)

    initialize = sub.add_parser("initialize")
    initialize.add_argument("--baseline-index-dir", type=Path, required=True)
    initialize.add_argument("--base-release-json", type=Path, required=True)
    initialize.add_argument("--base-release-id", required=True)
    initialize.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    initialize.add_argument("--private-key", type=Path, default=DEFAULT_PRIVATE_KEY)
    initialize.add_argument("--public-key", type=Path, default=DEFAULT_PUBLIC_KEY)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--handoff-dir", type=Path, required=True)
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--knowledge-root", type=Path, default=DEFAULT_KNOWLEDGE_ROOT)
    prepare.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    prepare.add_argument("--private-key", type=Path, default=DEFAULT_PRIVATE_KEY)

    for name in ("upload-immutable", "switch-pointer", "rollback-pointer", "verify-cloud"):
        command = sub.add_parser(name)
        command.add_argument("--prepared", type=Path, required=True)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--prepared", type=Path, required=True)
    finalize.add_argument("--receipt", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "initialize":
        output = command_initialize(args)
    elif args.command == "prepare":
        output = command_prepare(args)
    elif args.command == "upload-immutable":
        output = command_upload_immutable(args)
    elif args.command == "switch-pointer":
        output = command_switch_pointer(args)
    elif args.command == "rollback-pointer":
        output = command_switch_pointer(args, rollback=True)
    elif args.command == "verify-cloud":
        output = command_verify_cloud(args)
    else:
        output = command_finalize(args)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

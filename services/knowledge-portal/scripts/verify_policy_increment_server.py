#!/usr/bin/env python3
"""Verify the authoritative OSS policy-delta pointer against the active server slot."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

APP_DIR = Path(os.environ.get("JIAOTANG_APP_DIR", "/opt/jiaotang-kb-runtime/current"))
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

try:
    from scripts.oss_auth import build_bucket
    from scripts.publish_index_to_oss import MANIFEST_SCHEMA, PRODUCTION_FILES
except ImportError:
    from oss_auth import build_bucket
    from publish_index_to_oss import MANIFEST_SCHEMA, PRODUCTION_FILES


POINTER_SCHEMA = "jiaotang-policy-increment-pointer/v1"
DEFAULT_INDEX_ROOT = Path("/srv/jiaotang/knowledge-index")
DEFAULT_PUBLIC_KEY = Path("/etc/jiaotang-kb/policy-increment-public.pem")
DEFAULT_STATUS = Path("/var/lib/jiaotang-kb/oss-index-cache-status.json")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(RuntimeError):
    pass


def canonical(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_public(path: Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise VerificationError("增量链受信公钥不是Ed25519")
    return key


def key_id(key: Ed25519PublicKey) -> str:
    payload = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(payload).hexdigest()[:24]


def verify_inline_signature(payload: dict[str, Any], key: Ed25519PublicKey) -> None:
    unsigned = dict(payload)
    try:
        signature = base64.b64decode(str(unsigned.pop("signature_base64")), validate=True)
    except Exception as error:
        raise VerificationError("current指针签名字段非法") from error
    key.verify(signature, canonical(unsigned))


def remote_json(bucket: object, key: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(bucket.get_object(key).read())
    except Exception as error:
        raise VerificationError(f"{label}读取或解析失败：{key}") from error
    if not isinstance(payload, dict):
        raise VerificationError(f"{label}必须是JSON对象")
    return payload


def release_id_from_link(path: Path) -> str | None:
    if not path.is_symlink():
        return None
    return Path(os.readlink(path)).name


def verify_local_release(
    index_root: Path,
    pointer: dict[str, Any],
    *,
    deep: bool,
) -> dict[str, Any]:
    release_id = str(pointer.get("current_release_id") or "")
    current = release_id_from_link(index_root / "current")
    if current != release_id:
        raise VerificationError(f"服务器current与OSS增量链不一致：{current} != {release_id}")
    release_dir = index_root / "releases" / release_id
    try:
        release = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    except Exception as error:
        raise VerificationError("服务器current release.json不可用") from error
    if (
        release.get("schema") != MANIFEST_SCHEMA
        or release.get("release_id") != release_id
        or release.get("file_whitelist") != list(PRODUCTION_FILES)
        or release.get("storage_mode") != "signed-policy-delta-chain-v1"
    ):
        raise VerificationError("服务器current release元数据不是受支持的政策增量release")
    files = release.get("files")
    if not isinstance(files, list):
        raise VerificationError("服务器current release缺少files")
    names = [str(row.get("name") or "") for row in files if isinstance(row, dict)]
    if names != list(PRODUCTION_FILES):
        raise VerificationError("服务器current release文件白名单不完整")
    metadata: dict[str, dict[str, Any]] = {}
    for row in files:
        assert isinstance(row, dict)
        name = str(row["name"])
        path = release_dir / name
        if (
            not path.is_file()
            or path.stat().st_size != int(row.get("size", -1))
            or not SHA256_RE.fullmatch(str(row.get("sha256") or ""))
        ):
            raise VerificationError(f"服务器current文件身份异常：{name}")
        metadata[name] = row
    expected_index = str(pointer.get("current_index_sha256") or "")
    expected_manifest = str(pointer.get("current_manifest_sha256") or "")
    if metadata["knowledge_content.sqlite3"]["sha256"] != expected_index:
        raise VerificationError("服务器release记录的SQLite摘要与链指针不一致")
    if metadata["manifest.jsonl"]["sha256"] != expected_manifest:
        raise VerificationError("服务器release记录的manifest摘要与链指针不一致")
    if deep:
        for name, row in metadata.items():
            if sha256_file(release_dir / name) != row["sha256"]:
                raise VerificationError(f"服务器current深度哈希不一致：{name}")
    overlay = release.get("incremental_overlay")
    if not isinstance(overlay, dict) or overlay.get("chain_sha256") != pointer.get(
        "current_chain_sha256"
    ):
        raise VerificationError("服务器release增量覆盖声明与链指针不一致")
    return release


def verify_latest_delta(
    bucket: object,
    pointer: dict[str, Any],
    public_key: Ed25519PublicKey,
) -> dict[str, Any]:
    entries = pointer.get("entries")
    if not isinstance(entries, list) or len(entries) != int(pointer.get("chain_length") or -1):
        raise VerificationError("current指针链条目数量不一致")
    if not entries:
        raise VerificationError("政策增量服务器验证器不接受空链")
    entry = entries[-1]
    if not isinstance(entry, dict):
        raise VerificationError("current指针末条链记录非法")
    prefix = str(entry.get("delta_prefix") or "")
    manifest_body = bucket.get_object(f"{prefix}/delta_manifest.json").read()
    signature = remote_json(bucket, f"{prefix}/delta_signature.json", "增量签名")
    manifest = json.loads(manifest_body)
    if not isinstance(manifest, dict):
        raise VerificationError("增量manifest必须是JSON对象")
    if signature.get("key_id") != key_id(public_key):
        raise VerificationError("增量包签名key_id不匹配")
    if signature.get("manifest_sha256") != sha256_bytes(manifest_body):
        raise VerificationError("增量manifest摘要不一致")
    try:
        raw_signature = base64.b64decode(str(signature["signature_base64"]), validate=True)
    except Exception as error:
        raise VerificationError("增量包签名base64非法") from error
    public_key.verify(raw_signature, manifest_body)
    previous = str(signature.get("previous_chain_sha256") or "0" * 64)
    expected_chain = sha256_bytes(
        previous.encode("ascii")
        + str(signature["manifest_sha256"]).encode("ascii")
        + raw_signature
    )
    if expected_chain != signature.get("chain_sha256"):
        raise VerificationError("增量链摘要复算不一致")
    if (
        expected_chain != pointer.get("current_chain_sha256")
        or manifest.get("candidate_index_sha256") != pointer.get("current_index_sha256")
        or manifest.get("candidate_manifest_sha256") != pointer.get("current_manifest_sha256")
        or manifest.get("payload_sha256")
        != sha256_bytes(bucket.get_object(f"{prefix}/delta_payload.json").read())
    ):
        raise VerificationError("current指针与最新增量包不一致")
    return entry


def write_status(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="验证生产服务器政策增量链")
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--trusted-public-key", type=Path, default=DEFAULT_PUBLIC_KEY)
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args()
    public_key = load_public(args.trusted_public_key)
    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    pointer_key = f"{prefix}/index/policy-increment/v1/current.json"
    bucket = build_bucket()
    pointer = remote_json(bucket, pointer_key, "政策增量current指针")
    if pointer.get("schema") != POINTER_SCHEMA or pointer.get("key_id") != key_id(public_key):
        raise VerificationError("政策增量current指针身份不受信")
    verify_inline_signature(pointer, public_key)
    entry = verify_latest_delta(bucket, pointer, public_key)
    release = verify_local_release(args.index_root, pointer, deep=args.deep)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    status = {
        "status": "正常",
        "mode": "OSS完整基线 + Ed25519政策周增量链 + 服务器双槽差异索引",
        "checked_at": now,
        "cache_updated_at": now,
        "source": "signed-policy-delta-chain",
        "current_release_id": pointer["current_release_id"],
        "previous_release_id": release.get("previous_release_id"),
        "index_sha256": pointer["current_index_sha256"],
        "manifest_sha256": pointer["current_manifest_sha256"],
        "chain_sha256": pointer["current_chain_sha256"],
        "chain_length": pointer["chain_length"],
        "handoff_id": entry.get("handoff_id"),
        "generation_consistent": True,
        "runtime_mode": "atomic-release-links",
        "cache_updated": False,
        "verification_mode": "deep" if args.deep else "signed-metadata",
    }
    write_status(args.status_file, status)
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

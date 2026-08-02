#!/usr/bin/env python3
"""Verify the signed acceptance receipt and current pointer without scanning indexes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from scripts.oss_auth import build_bucket
    from scripts.publish_index_to_oss import (
        canonical_json,
        sha256_bytes,
        verify_existing_signed_document,
    )
    from scripts.refresh_index_from_oss import (
        release_id_from_link,
        remote_bytes,
        signing_secrets,
        verify_pointer,
        verify_release,
    )
    from scripts.verify_acceptance_receipt import (
        DEFAULT_PROFILE,
        verify_signed_receipt_payload,
    )
except ImportError:  # direct script execution
    from oss_auth import build_bucket
    from publish_index_to_oss import (
        canonical_json,
        sha256_bytes,
        verify_existing_signed_document,
    )
    from refresh_index_from_oss import (
        release_id_from_link,
        remote_bytes,
        signing_secrets,
        verify_pointer,
        verify_release,
    )
    from verify_acceptance_receipt import (
        DEFAULT_PROFILE,
        verify_signed_receipt_payload,
    )


def verify_local_binding(
    index_root: Path,
    profile: Path,
    pointer: dict[str, object],
    release: dict[str, object],
    remote_manifest_body: bytes,
    receipt_body: bytes,
    required_suite: str,
) -> dict[str, object]:
    release_id = str(release.get("release_id") or "")
    current_release_id = release_id_from_link(index_root / "current")
    errors = []
    if current_release_id != release_id or pointer.get("release_id") != release_id:
        errors.append("local current, OSS current, and signed release differ")
    release_dir = index_root / "releases" / release_id
    local_manifest = release_dir / "release.json"
    if not local_manifest.is_file():
        errors.append("local current release.json is missing")
    else:
        local_manifest_sha = hashlib.sha256(local_manifest.read_bytes()).hexdigest()
        if local_manifest_sha != sha256_bytes(remote_manifest_body):
            errors.append("local release.json differs from signed OSS release")
    receipt_result = verify_signed_receipt_payload(
        receipt_body,
        profile,
        release,
        required_suite,
        str(pointer.get("acceptance_receipt_sha256") or ""),
    )
    errors.extend(str(error) for error in receipt_result.get("errors", []))
    return {
        "status": "pass" if not errors else "fail",
        "verification_mode": "signed-receipt-and-current-pointer",
        "deep_scan": False,
        "large_files_hashed": 0,
        "release_id": release_id,
        "current_release_id": current_release_id,
        "release_manifest_sha256": sha256_bytes(remote_manifest_body),
        "pointer_sha256": sha256_bytes(canonical_json(pointer)),
        "acceptance_receipt": receipt_result,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只校验签名Harness回执、OSS current指针和本机current绑定"
    )
    parser.add_argument("--index-root", type=Path)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--required-suite", default="knowledge_base")
    args = parser.parse_args()
    index_root = (
        args.index_root
        or Path(os.environ.get("JIAOTANG_INDEX_DIR", "/srv/jiaotang/knowledge-index"))
    ).expanduser().resolve()
    profile = args.profile.expanduser().resolve()
    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    pointer_key = f"{prefix}/index/current.json"
    secrets = signing_secrets()
    bucket = build_bucket()
    pointer_body = remote_bytes(bucket, pointer_key)
    pointer = verify_pointer(pointer_body, secrets)
    release_id = str(pointer["release_id"])
    expected_prefix = f"{prefix}/index/releases/{release_id}/"
    manifest_key = str(pointer.get("release_manifest_key") or "")
    signature_key = str(pointer.get("release_signature_key") or "")
    if (
        manifest_key != expected_prefix + "release.json"
        or signature_key != expected_prefix + "release.sig"
    ):
        raise RuntimeError("current pointer references an invalid release path")
    manifest_body = remote_bytes(bucket, manifest_key)
    release = verify_release(
        manifest_body,
        remote_bytes(bucket, signature_key),
        pointer,
        secrets,
    )
    receipt_digest = str(pointer.get("acceptance_receipt_sha256") or "")
    receipt_prefix = f"{prefix}/index/acceptance-receipts/{receipt_digest}/"
    receipt_key = str(pointer.get("acceptance_receipt_key") or "")
    receipt_signature_key = str(
        pointer.get("acceptance_receipt_signature_key") or ""
    )
    if (
        not re.fullmatch(r"[0-9a-f]{64}", receipt_digest)
        or receipt_key != receipt_prefix + "acceptance-receipt.json"
        or receipt_signature_key != receipt_prefix + "acceptance-receipt.sig"
    ):
        raise RuntimeError(
            "current pointer lacks a signed acceptance receipt; "
            "run one index release migration"
        )
    receipt_body = remote_bytes(bucket, receipt_key)
    receipt_signature_body = remote_bytes(bucket, receipt_signature_key)
    if sha256_bytes(receipt_body) != receipt_digest:
        raise RuntimeError("acceptance receipt digest differs from current pointer")
    verify_existing_signed_document(
        receipt_body,
        receipt_signature_body,
        secrets,
    )
    result = verify_local_binding(
        index_root,
        profile,
        pointer,
        release,
        manifest_body,
        receipt_body,
        args.required_suite,
    )
    result["pointer_sha256"] = sha256_bytes(pointer_body)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

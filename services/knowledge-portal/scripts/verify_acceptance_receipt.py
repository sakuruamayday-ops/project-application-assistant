#!/usr/bin/env python3
"""Fail closed unless an Acceptance Harness receipt matches current inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = (
    BASE_DIR / "references" / "acceptance-harness" / "knowledge-base.json"
)
EVIDENCE_SOURCES = {
    "index_builder_sha256": BASE_DIR
    / "scripts"
    / "build_knowledge_content_index.py",
    "inventory_builder_sha256": BASE_DIR
    / "scripts"
    / "build_knowledge_inventory_from_manifest.py",
    "allowlist_builder_sha256": BASE_DIR
    / "scripts"
    / "build_cloud_upload_allowlist.py",
    "policy_version_builder_sha256": BASE_DIR
    / "scripts"
    / "build_policy_version_links.py",
    "harness_runner_sha256": BASE_DIR
    / "scripts"
    / "run_acceptance_harness.py",
    "harness_engine_sha256": BASE_DIR / "app" / "acceptance_harness.py",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_evidence(profile: Path, index_root: Path) -> dict[str, str]:
    paths = {
        "profile_sha256": profile,
        "manifest_sha256": index_root / "manifest.jsonl",
        "content_index_sha256": index_root / "knowledge_content.sqlite3",
        "inventory_index_sha256": index_root / "knowledge_inventory.sqlite3",
        "policy_versions_sha256": index_root / "policy_versions.sqlite3",
        "upload_allowlist_sha256": index_root / "upload_allowlist.csv",
        **EVIDENCE_SOURCES,
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("receipt input missing: " + ", ".join(missing))
    return {name: sha256_file(path) for name, path in paths.items()}


def verify_receipt(
    receipt_path: Path,
    profile: Path,
    index_root: Path,
    required_suite: str,
) -> dict[str, object]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    actual_evidence = receipt.get("target_evidence")
    if not isinstance(actual_evidence, dict):
        actual_evidence = {}
    expected = expected_evidence(profile, index_root)
    mismatches = {
        name: {
            "receipt": actual_evidence.get(name),
            "current": digest,
        }
        for name, digest in expected.items()
        if actual_evidence.get(name) != digest
    }
    requested_suites = receipt.get("requested_suites") or []
    errors = []
    if receipt.get("receipt_schema") != "jiaotang-acceptance-receipt/v1":
        errors.append("unsupported receipt schema")
    if receipt.get("status") != "pass" or receipt.get("release_allowed") is not True:
        errors.append("acceptance receipt did not allow release")
    if required_suite and required_suite not in requested_suites:
        errors.append(f"required suite missing: {required_suite}")
    if mismatches:
        errors.append("receipt inputs changed")
    return {
        "status": "pass" if not errors else "fail",
        "receipt": str(receipt_path),
        "profile_id": receipt.get("profile_id"),
        "generated_at": receipt.get("generated_at"),
        "required_suite": required_suite,
        "evidence": expected,
        "mismatches": mismatches,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证 Harness 收据与当前知识库输入完全一致"
    )
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--required-suite", default="knowledge_base")
    args = parser.parse_args()
    result = verify_receipt(
        args.receipt.expanduser().resolve(),
        args.profile.expanduser().resolve(),
        args.index_root.expanduser().resolve(),
        args.required_suite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

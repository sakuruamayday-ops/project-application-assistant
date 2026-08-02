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
INDEX_EVIDENCE_FILES = {
    "manifest_sha256": "manifest.jsonl",
    "content_index_sha256": "knowledge_content.sqlite3",
    "inventory_index_sha256": "knowledge_inventory.sqlite3",
    "policy_versions_sha256": "policy_versions.sqlite3",
    "upload_allowlist_sha256": "upload_allowlist.csv",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_static_evidence(profile: Path) -> dict[str, str]:
    paths = {
        "profile_sha256": profile,
        **EVIDENCE_SOURCES,
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("receipt input missing: " + ", ".join(missing))
    return {name: sha256_file(path) for name, path in paths.items()}


def expected_evidence(profile: Path, index_root: Path) -> dict[str, str]:
    paths = {
        name: index_root / filename
        for name, filename in INDEX_EVIDENCE_FILES.items()
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("receipt input missing: " + ", ".join(missing))
    return {
        **expected_static_evidence(profile),
        **{name: sha256_file(path) for name, path in paths.items()},
    }


def receipt_contract_errors(
    receipt: dict[str, object],
    required_suite: str,
) -> list[str]:
    requested_suites = receipt.get("requested_suites") or []
    errors = []
    if receipt.get("receipt_schema") != "jiaotang-acceptance-receipt/v1":
        errors.append("unsupported receipt schema")
    if receipt.get("status") != "pass" or receipt.get("release_allowed") is not True:
        errors.append("acceptance receipt did not allow release")
    if required_suite and required_suite not in requested_suites:
        errors.append(f"required suite missing: {required_suite}")
    return errors


def verify_receipt_against_release(
    receipt: dict[str, object],
    profile: Path,
    release: dict[str, object],
    required_suite: str,
) -> dict[str, object]:
    """Compare receipt evidence with release metadata without hashing index files."""

    actual_evidence = receipt.get("target_evidence")
    if not isinstance(actual_evidence, dict):
        actual_evidence = {}
    rows = release.get("files")
    files = (
        {
            str(row.get("name") or ""): row
            for row in rows
            if isinstance(row, dict)
        }
        if isinstance(rows, list)
        else {}
    )
    expected = expected_static_evidence(profile)
    errors = receipt_contract_errors(receipt, required_suite)
    for evidence_name, filename in INDEX_EVIDENCE_FILES.items():
        row = files.get(filename, {})
        digest = str(row.get("sha256") or "")
        expected[evidence_name] = digest
        if not digest:
            errors.append(f"signed release evidence missing: {filename}")
    mismatches = {
        name: {
            "receipt": actual_evidence.get(name),
            "signed_release": digest,
        }
        for name, digest in expected.items()
        if actual_evidence.get(name) != digest
    }
    if mismatches:
        errors.append("receipt inputs differ from signed release")
    return {
        "status": "pass" if not errors else "fail",
        "profile_id": receipt.get("profile_id"),
        "generated_at": receipt.get("generated_at"),
        "required_suite": required_suite,
        "evidence": expected,
        "mismatches": mismatches,
        "errors": errors,
        "verification_mode": "signed-metadata",
        "large_files_hashed": 0,
    }


def verify_signed_receipt_payload(
    receipt_body: bytes,
    profile: Path,
    release: dict[str, object],
    required_suite: str,
    expected_receipt_sha256: str,
) -> dict[str, object]:
    receipt = json.loads(receipt_body)
    if not isinstance(receipt, dict):
        raise ValueError("acceptance receipt must be a JSON object")
    result = verify_receipt_against_release(
        receipt,
        profile,
        release,
        required_suite,
    )
    if hashlib.sha256(receipt_body).hexdigest() != expected_receipt_sha256:
        result["errors"].append("acceptance receipt digest differs from signed pointer")
        result["status"] = "fail"
    return result


def verify_signed_receipt(
    receipt_path: Path,
    profile: Path,
    release: dict[str, object],
    required_suite: str,
) -> dict[str, object]:
    """Compatibility wrapper for receipts embedded in a signed release manifest."""

    receipt_body = receipt_path.read_bytes()
    rows = release.get("files")
    receipt_digest = ""
    if isinstance(rows, list):
        receipt_digest = next(
            (
                str(row.get("sha256") or "")
                for row in rows
                if isinstance(row, dict)
                and row.get("name") == "acceptance-harness.json"
            ),
            "",
        )
    result = verify_signed_receipt_payload(
        receipt_body,
        profile,
        release,
        required_suite,
        receipt_digest,
    )
    result["receipt"] = str(receipt_path)
    if not receipt_digest:
        result["errors"].append("acceptance receipt is not bound to signed release")
        result["status"] = "fail"
    return result


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
    errors = receipt_contract_errors(receipt, required_suite)
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

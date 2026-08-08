#!/usr/bin/env python3
"""Reconcile immutable index releases and content-addressed OSS knowledge objects.

This module is intentionally read-only.  It is used as a hard pre-switch gate by
``publish_index_to_oss.py`` and can also write the complete deletion candidate
plan for a separately authorised cleanup transaction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import oss2

try:
    from scripts.oss_auth import build_bucket
except ImportError:  # direct script execution
    from oss_auth import build_bucket


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PLAN_SCHEMA = "jiaotang-oss-retention-plan/v2"


def canonical_json(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def calculate_plan_sha256(plan: dict[str, Any]) -> str:
    """Return a stable identity for the exact cleanup target set.

    Observation time and execution status are audit metadata, not part of the
    authorised target set.  Excluding them keeps repeated read-only
    reconciliation of unchanged OSS state anchored to the same SHA-256.
    """

    identity = {
        key: value
        for key, value in plan.items()
        if key not in {"generated_at", "permanent_delete_applied", "plan_sha256"}
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def knowledge_object_key(prefix: str, digest: str) -> str:
    return f"{prefix}/knowledge/objects/{digest[:2]}/{digest}"


def load_allowlist_rows(
    rows: Iterable[dict[str, str]],
    *,
    prefix: str,
    source: str,
) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("object_storage_allowed") or "").lower() != "true":
            continue
        digest = str(row.get("sha256") or "")
        if not SHA256_PATTERN.fullmatch(digest):
            raise RuntimeError(f"{source}包含非法SHA-256：{digest!r}")
        size = int(row.get("size_bytes") or 0)
        key = knowledge_object_key(prefix, digest)
        existing = expected.get(key)
        if existing and int(existing["size_bytes"]) != size:
            raise RuntimeError(f"同一SHA-256在{source}中声明了不同大小：{digest}")
        item = expected.setdefault(
            key,
            {
                "object_key": key,
                "sha256": digest,
                "size_bytes": size,
                "paths": [],
                "sources": [],
            },
        )
        relative_path = str(row.get("relative_path") or "")
        if relative_path and relative_path not in item["paths"]:
            item["paths"].append(relative_path)
        if source not in item["sources"]:
            item["sources"].append(source)
    return expected


def load_allowlist(path: Path, *, prefix: str) -> dict[str, dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return load_allowlist_rows(
            csv.DictReader(source),
            prefix=prefix,
            source=str(path),
        )


def load_remote_allowlist(
    bucket: object,
    object_key: str,
    *,
    prefix: str,
) -> dict[str, dict[str, Any]]:
    body = bucket.get_object(object_key).read().decode("utf-8-sig")
    return load_allowlist_rows(
        csv.DictReader(io.StringIO(body)),
        prefix=prefix,
        source=object_key,
    )


def list_current_objects(bucket: object, object_prefix: str) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for item in oss2.ObjectIteratorV2(bucket, prefix=object_prefix):
        key = str(item.key)
        objects[key] = {
            "object_key": key,
            "size_bytes": int(item.size or 0),
            "last_modified_epoch": int(item.last_modified or 0),
        }
    return objects


def merge_expected(
    *collections: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for collection in collections:
        for key, row in collection.items():
            existing = merged.get(key)
            if existing and int(existing["size_bytes"]) != int(row["size_bytes"]):
                raise RuntimeError(f"保留白名单对同一对象声明了不同大小：{key}")
            if existing is None:
                merged[key] = {
                    **row,
                    "paths": list(row.get("paths", [])),
                    "sources": list(row.get("sources", [])),
                }
                continue
            for field in ("paths", "sources"):
                for value in row.get(field, []):
                    if value not in existing[field]:
                        existing[field].append(value)
    return merged


def reconcile_knowledge_objects(
    current_expected: dict[str, dict[str, Any]],
    retained_expected: dict[str, dict[str, Any]],
    remote_objects: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    current_keys = set(current_expected)
    retained_keys = set(retained_expected)
    remote_keys = set(remote_objects)
    missing_current = sorted(current_keys - remote_keys)
    size_mismatch = sorted(
        key
        for key in current_keys & remote_keys
        if int(current_expected[key]["size_bytes"])
        != int(remote_objects[key]["size_bytes"])
    )
    orphan_keys = sorted(remote_keys - retained_keys)
    return {
        "current_expected_count": len(current_keys),
        "retained_expected_count": len(retained_keys),
        "remote_object_count": len(remote_keys),
        "missing_current": [current_expected[key] for key in missing_current],
        "missing_current_count": len(missing_current),
        "missing_current_bytes": sum(
            int(current_expected[key]["size_bytes"]) for key in missing_current
        ),
        "size_mismatches": [
            {
                **current_expected[key],
                "remote_size_bytes": int(remote_objects[key]["size_bytes"]),
            }
            for key in size_mismatch
        ],
        "size_mismatch_count": len(size_mismatch),
        "orphans": [remote_objects[key] for key in orphan_keys],
        "orphan_count": len(orphan_keys),
        "orphan_bytes": sum(
            int(remote_objects[key]["size_bytes"]) for key in orphan_keys
        ),
    }


def verify_current_allowlist_complete(
    bucket: object,
    allowlist_path: Path,
    *,
    prefix: str,
) -> dict[str, Any]:
    expected = load_allowlist(allowlist_path, prefix=prefix)
    remote = list_current_objects(bucket, f"{prefix}/knowledge/objects/")
    report = reconcile_knowledge_objects(expected, expected, remote)
    if report["missing_current_count"] or report["size_mismatch_count"]:
        missing = ", ".join(
            str(row["object_key"])
            for row in report["missing_current"][:5]
        )
        mismatched = ", ".join(
            str(row["object_key"])
            for row in report["size_mismatches"][:5]
        )
        raise RuntimeError(
            "OSS知识原件完整性门禁失败："
            f"缺失{report['missing_current_count']}，"
            f"大小不一致{report['size_mismatch_count']}；"
            f"missing=[{missing}] mismatch=[{mismatched}]"
        )
    return {
        key: report[key]
        for key in (
            "current_expected_count",
            "remote_object_count",
            "missing_current_count",
            "missing_current_bytes",
            "size_mismatch_count",
        )
    }


def pointer_payload(bucket: object, prefix: str) -> dict[str, Any]:
    payload = json.loads(bucket.get_object(f"{prefix}/index/current.json").read())
    if not isinstance(payload, dict):
        raise RuntimeError("OSS current指针不是JSON对象")
    return payload


def allowlist_for_release(
    bucket: object,
    prefix: str,
    release_id: str,
) -> dict[str, dict[str, Any]]:
    if not release_id:
        return {}
    return load_remote_allowlist(
        bucket,
        f"{prefix}/index/releases/{release_id}/upload_allowlist.csv",
        prefix=prefix,
    )


def load_manifest_history(
    bucket: object,
    *,
    prefix: str,
    release_ids: Iterable[str],
    target_digests: set[str],
    retained_release_ids: set[str],
) -> tuple[dict[str, dict[str, set[str]]], dict[str, str]]:
    history: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"release_ids": set(), "paths": set()}
    )
    retained_paths: dict[str, str] = {}
    for release_id in sorted(set(release_ids)):
        key = f"{prefix}/index/releases/{release_id}/manifest.jsonl"
        body = bucket.get_object(key).read().decode("utf-8")
        for line in body.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            digest = str(row.get("sha256") or "")
            relative_path = str(row.get("relative_path") or "")
            if release_id in retained_release_ids and relative_path and digest:
                retained_paths[relative_path] = digest
            if digest not in target_digests:
                continue
            history[digest]["release_ids"].add(release_id)
            if relative_path:
                history[digest]["paths"].add(relative_path)
    return history, retained_paths


def list_candidate_versions(
    bucket: object,
    candidate_keys: set[str],
) -> list[dict[str, Any]]:
    if not candidate_keys:
        return []
    rows: list[dict[str, Any]] = []
    key_marker = ""
    versionid_marker = ""
    while True:
        result = bucket.list_object_versions(
            key_marker=key_marker,
            versionid_marker=versionid_marker,
            max_keys=1000,
        )
        for version in result.versions:
            key = str(version.key)
            if key not in candidate_keys:
                continue
            rows.append(
                {
                    "object_key": key,
                    "version_id": str(version.versionid),
                    "record_type": "object_version",
                    "is_latest": bool(getattr(version, "is_latest", False)),
                    "size_bytes": int(version.size or 0),
                    "last_modified_epoch": int(version.last_modified or 0),
                    "reason": "精确版本永久删除清单",
                }
            )
        for marker in result.delete_marker:
            key = str(marker.key)
            if key not in candidate_keys:
                continue
            rows.append(
                {
                    "object_key": key,
                    "version_id": str(marker.versionid),
                    "record_type": "delete_marker",
                    "is_latest": bool(getattr(marker, "is_latest", False)),
                    "size_bytes": 0,
                    "last_modified_epoch": int(marker.last_modified or 0),
                    "reason": "精确版本永久删除清单",
                }
            )
        if not result.is_truncated:
            break
        key_marker = str(result.next_key_marker or "")
        versionid_marker = str(result.next_versionid_marker or "")
        if not key_marker and not versionid_marker:
            raise RuntimeError("OSS版本清单仍有下一页，但未返回分页标记")
    return sorted(rows, key=lambda row: (row["object_key"], row["version_id"]))


def build_retention_plan(
    bucket: object,
    *,
    prefix: str,
    include_history: bool = False,
    include_version_ids: bool = False,
) -> dict[str, Any]:
    pointer = pointer_payload(bucket, prefix)
    current_release = str(pointer.get("release_id") or "")
    previous_release = str(pointer.get("previous_release_id") or "")
    if not current_release or not previous_release or current_release == previous_release:
        raise RuntimeError("OSS current指针必须同时声明不同的current和previous release")
    current_expected = allowlist_for_release(bucket, prefix, current_release)
    previous_expected = allowlist_for_release(bucket, prefix, previous_release)
    retained_expected = merge_expected(current_expected, previous_expected)
    knowledge_objects = list_current_objects(
        bucket,
        f"{prefix}/knowledge/objects/",
    )
    knowledge = reconcile_knowledge_objects(
        current_expected,
        retained_expected,
        knowledge_objects,
    )

    release_root = f"{prefix}/index/releases/"
    release_objects = list_current_objects(bucket, release_root)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in release_objects.values():
        remainder = str(row["object_key"])[len(release_root) :]
        release_id = remainder.split("/", 1)[0]
        if release_id:
            grouped[release_id].append(row)
    retained_release_ids = {current_release, previous_release}
    stale_release_ids = sorted(set(grouped) - retained_release_ids)
    release_candidates = [
        {
            **row,
            "release_id": release_id,
            "reason": "不被current或previous指针引用的历史索引release",
        }
        for release_id in stale_release_ids
        for row in sorted(grouped[release_id], key=lambda item: item["object_key"])
    ]
    knowledge_candidates = [
        {
            **row,
            "reason": "不被current或previous对象存储白名单引用",
        }
        for row in knowledge["orphans"]
    ]
    if include_history and knowledge_candidates:
        orphan_digests = {
            str(row["object_key"]).rsplit("/", 1)[-1]
            for row in knowledge_candidates
        }
        history, retained_paths = load_manifest_history(
            bucket,
            prefix=prefix,
            release_ids=grouped,
            target_digests=orphan_digests,
            retained_release_ids=retained_release_ids,
        )
        for row in knowledge_candidates:
            digest = str(row["object_key"]).rsplit("/", 1)[-1]
            evidence = history.get(digest, {"release_ids": set(), "paths": set()})
            paths = sorted(evidence["paths"])
            replacements = sorted(
                f"{path} -> {retained_paths[path]}"
                for path in paths
                if path in retained_paths and retained_paths[path] != digest
            )
            row["historical_release_ids"] = sorted(evidence["release_ids"])
            row["historical_paths"] = paths
            row["retained_path_replacements"] = replacements
            row["evidence"] = "OSS历史release manifest与当前/上一版白名单联合对账"
    candidate_keys = {
        str(row["object_key"])
        for row in (*release_candidates, *knowledge_candidates)
    }
    permanent_delete_versions = (
        list_candidate_versions(bucket, candidate_keys)
        if include_version_ids
        else []
    )
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "generated_at": utc_now(),
        "bucket": str(getattr(bucket, "bucket_name", "") or ""),
        "prefix": prefix,
        "pointer_sha256": hashlib.sha256(
            canonical_json(pointer)
        ).hexdigest(),
        "current_release_id": current_release,
        "previous_release_id": previous_release,
        "retained_release_ids": sorted(retained_release_ids),
        "stale_release_ids": stale_release_ids,
        "current_knowledge_missing": knowledge["missing_current"],
        "current_knowledge_missing_count": knowledge["missing_current_count"],
        "current_knowledge_size_mismatches": knowledge["size_mismatches"],
        "index_release_delete_candidates": release_candidates,
        "index_release_candidate_count": len(release_candidates),
        "index_release_candidate_bytes": sum(
            int(row["size_bytes"]) for row in release_candidates
        ),
        "knowledge_delete_candidates": knowledge_candidates,
        "knowledge_candidate_count": len(knowledge_candidates),
        "knowledge_candidate_bytes": sum(
            int(row["size_bytes"]) for row in knowledge_candidates
        ),
        "permanent_delete_versions": permanent_delete_versions,
        "permanent_delete_version_count": len(permanent_delete_versions),
        "permanent_delete_version_bytes": sum(
            int(row["size_bytes"]) for row in permanent_delete_versions
        ),
        "history_included": include_history,
        "version_ids_included": include_version_ids,
        "permanent_delete_applied": False,
    }
    plan["plan_sha256"] = calculate_plan_sha256(plan)
    return plan


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jsonl":
        with path.open("w", encoding="utf-8") as target:
            for row in rows:
                target.write(json.dumps(row, ensure_ascii=False) + "\n")
        return
    fieldnames = sorted({key for row in rows for key in row}) or ["object_key"]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        " | ".join(str(item) for item in value)
                        if isinstance(value, list)
                        else value
                    )
                    for key, value in row.items()
                }
            )


def write_plan(output_dir: Path, plan: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "oss_retention_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for stem, rows in (
        ("oss_index_release_delete_candidates", plan["index_release_delete_candidates"]),
        ("oss_knowledge_delete_candidates", plan["knowledge_delete_candidates"]),
        ("oss_current_knowledge_missing", plan["current_knowledge_missing"]),
        ("oss_permanent_delete_versions", plan["permanent_delete_versions"]),
    ):
        write_rows(output_dir / f"{stem}.csv", rows)
        write_rows(output_dir / f"{stem}.jsonl", rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="核对OSS当前/上一版并输出完整两套保留清理计划"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-current-complete", action="store_true")
    parser.add_argument("--include-history", action="store_true")
    parser.add_argument("--include-version-ids", action="store_true")
    args = parser.parse_args()
    bucket = build_bucket()
    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    plan = build_retention_plan(
        bucket,
        prefix=prefix,
        include_history=args.include_history,
        include_version_ids=args.include_version_ids,
    )
    write_plan(args.output_dir, plan)
    print(
        json.dumps(
            {
                key: plan[key]
                for key in (
                    "plan_sha256",
                    "current_release_id",
                    "previous_release_id",
                    "current_knowledge_missing_count",
                    "index_release_candidate_count",
                    "index_release_candidate_bytes",
                    "knowledge_candidate_count",
                    "knowledge_candidate_bytes",
                    "permanent_delete_version_count",
                    "permanent_delete_version_bytes",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.require_current_complete and (
        plan["current_knowledge_missing_count"]
        or plan["current_knowledge_size_mismatches"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

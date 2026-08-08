from __future__ import annotations

import csv
from pathlib import Path

import pytest

import scripts.oss_reconciliation as module


def allowed(key: str, size: int) -> dict[str, object]:
    digest = key.rsplit("/", 1)[-1]
    return {
        "object_key": key,
        "sha256": digest,
        "size_bytes": size,
        "paths": [f"资料/{digest[:8]}.pdf"],
        "sources": ["fixture"],
    }


def remote(key: str, size: int) -> dict[str, object]:
    return {
        "object_key": key,
        "size_bytes": size,
        "last_modified_epoch": 0,
    }


def test_reconcile_uses_current_and_previous_union_for_orphans() -> None:
    prefix = "production"
    current_key = module.knowledge_object_key(prefix, "a" * 64)
    previous_key = module.knowledge_object_key(prefix, "b" * 64)
    stale_key = module.knowledge_object_key(prefix, "c" * 64)
    current = {current_key: allowed(current_key, 10)}
    previous = {previous_key: allowed(previous_key, 20)}
    retained = module.merge_expected(current, previous)
    objects = {
        current_key: remote(current_key, 10),
        previous_key: remote(previous_key, 20),
        stale_key: remote(stale_key, 30),
    }

    report = module.reconcile_knowledge_objects(current, retained, objects)

    assert report["missing_current_count"] == 0
    assert report["orphan_count"] == 1
    assert report["orphan_bytes"] == 30
    assert report["orphans"][0]["object_key"] == stale_key


def test_current_completeness_gate_blocks_missing_and_size_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    allowlist = tmp_path / "upload_allowlist.csv"
    with allowlist.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=(
                "relative_path",
                "sha256",
                "size_bytes",
                "object_storage_allowed",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "relative_path": "资料/缺失.pdf",
                "sha256": "d" * 64,
                "size_bytes": 40,
                "object_storage_allowed": "true",
            }
        )
        writer.writerow(
            {
                "relative_path": "资料/大小异常.pdf",
                "sha256": "e" * 64,
                "size_bytes": 50,
                "object_storage_allowed": "true",
            }
        )
    mismatch_key = module.knowledge_object_key("production", "e" * 64)
    monkeypatch.setattr(
        module,
        "list_current_objects",
        lambda *_args, **_kwargs: {mismatch_key: remote(mismatch_key, 51)},
    )

    with pytest.raises(RuntimeError, match="缺失1，大小不一致1"):
        module.verify_current_allowlist_complete(
            object(),
            allowlist,
            prefix="production",
        )


def test_current_completeness_gate_passes_without_downloading_objects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    allowlist = tmp_path / "upload_allowlist.csv"
    allowlist.write_text(
        "relative_path,sha256,size_bytes,object_storage_allowed\n"
        f"资料/完整.pdf,{'f' * 64},60,true\n",
        encoding="utf-8",
    )
    key = module.knowledge_object_key("production", "f" * 64)
    monkeypatch.setattr(
        module,
        "list_current_objects",
        lambda *_args, **_kwargs: {key: remote(key, 60)},
    )

    report = module.verify_current_allowlist_complete(
        object(),
        allowlist,
        prefix="production",
    )

    assert report["missing_current_count"] == 0
    assert report["size_mismatch_count"] == 0


def test_direct_index_publish_checks_knowledge_before_pointer_switch() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "publish_index_to_oss.py"
    ).read_text(encoding="utf-8")

    gate = source.index("knowledge_completeness = verify_current_allowlist_complete(")
    upload = source.index("status = put_immutable_file(")
    switch = source.index("switch_status = switch_pointer_cas(")

    assert gate < upload < switch


def test_plan_sha_is_stable_across_observation_time_and_execution_state() -> None:
    plan = {
        "schema": module.PLAN_SCHEMA,
        "generated_at": "2026-08-08T00:00:00+00:00",
        "bucket": "fixture",
        "pointer_sha256": "a" * 64,
        "permanent_delete_versions": [
            {"object_key": "production/stale", "version_id": "v1", "size_bytes": 7}
        ],
        "permanent_delete_applied": False,
    }
    expected = module.calculate_plan_sha256(plan)

    plan["generated_at"] = "2026-08-09T00:00:00+00:00"
    plan["permanent_delete_applied"] = True
    plan["plan_sha256"] = "ignored"

    assert module.calculate_plan_sha256(plan) == expected


def test_plan_sha_changes_when_exact_version_target_changes() -> None:
    plan = {
        "schema": module.PLAN_SCHEMA,
        "generated_at": "2026-08-08T00:00:00+00:00",
        "bucket": "fixture",
        "pointer_sha256": "a" * 64,
        "permanent_delete_versions": [
            {"object_key": "production/stale", "version_id": "v1", "size_bytes": 7}
        ],
        "permanent_delete_applied": False,
    }
    original = module.calculate_plan_sha256(plan)
    plan["permanent_delete_versions"][0]["version_id"] = "v2"

    assert module.calculate_plan_sha256(plan) != original

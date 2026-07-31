from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.check_oss_governance import SECRET_NAMES, evaluate
from scripts.oss_auth import build_auth
from scripts.validate_operational_health import (
    parse_timestamp,
    read_valid_status_with_age,
    validate_fresh_status,
)


def test_status_ttl_rejects_stale_index_status(tmp_path: Path) -> None:
    path = tmp_path / "index-status.json"
    old = datetime.now(timezone.utc) - timedelta(days=3)
    path.write_text(
        json.dumps(
            {
                "status": "正常",
                "completed_at": old.strftime("%Y%m%dT%H%M%SZ"),
            }
        )
    )
    with pytest.raises(RuntimeError, match="状态过期"):
        validate_fresh_status(
            path,
            label="索引缓存",
            timestamp_field="completed_at",
            max_age_seconds=48 * 3600,
            accepted_statuses={"正常"},
            now=datetime.now(timezone.utc),
        )


def test_stale_but_well_formed_status_can_be_degraded_to_warning(
    tmp_path: Path,
) -> None:
    path = tmp_path / "index-status.json"
    old = datetime.now(timezone.utc) - timedelta(days=3)
    path.write_text(
        json.dumps(
            {
                "status": "正常",
                "checked_at": old.isoformat().replace("+00:00", "Z"),
            }
        )
    )
    payload, age = read_valid_status_with_age(
        path,
        label="索引缓存",
        timestamp_field="checked_at",
        accepted_statuses={"正常"},
        now=datetime.now(timezone.utc),
    )
    assert payload["status"] == "正常"
    assert age > 48 * 3600


def test_governance_gate_rejects_portal_credential_leak() -> None:
    checks = {
        "auth_mode": "sts",
        "versioning": "Enabled",
        "encryption": "AES256",
        "access_logging": True,
        "inventory": True,
        "cross_region_replication": True,
    }
    errors, warnings = evaluate(
        checks,
        app_environment_keys={"JIAOTANG_PUBLIC_HOST", *SECRET_NAMES},
    )
    assert any("门户主进程环境" in error for error in errors)
    assert not warnings


def test_compact_and_iso_timestamps_are_supported() -> None:
    assert parse_timestamp("20260731T010203Z").tzinfo == timezone.utc
    assert parse_timestamp("2026-07-31T01:02:03Z").tzinfo is not None


def test_oss_auth_modes_do_not_silently_fall_back_to_static_keys() -> None:
    static = build_auth(
        {
            "JIAOTANG_OSS_AUTH_MODE": "static",
            "JIAOTANG_OSS_ACCESS_KEY_ID": "id",
            "JIAOTANG_OSS_ACCESS_KEY_SECRET": "secret",
        }
    )
    assert static is not None
    with pytest.raises(RuntimeError, match="SECURITY_TOKEN"):
        build_auth(
            {
                "JIAOTANG_OSS_AUTH_MODE": "sts",
                "JIAOTANG_OSS_ACCESS_KEY_ID": "id",
                "JIAOTANG_OSS_ACCESS_KEY_SECRET": "secret",
            }
        )
    with pytest.raises(RuntimeError, match="RAM_ROLE_AUTH_HOST"):
        build_auth({"JIAOTANG_OSS_AUTH_MODE": "ram-role"})


def test_explicit_empty_oss_environment_never_inherits_process_secrets(
    monkeypatch,
) -> None:
    monkeypatch.setenv("JIAOTANG_OSS_ACCESS_KEY_ID", "ambient-id")
    monkeypatch.setenv("JIAOTANG_OSS_ACCESS_KEY_SECRET", "ambient-secret")
    with pytest.raises(RuntimeError, match="ACCESS_KEY_ID"):
        build_auth({})

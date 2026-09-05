from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "application-writing" / "scripts" / "portable_skill_runtime.py"
SPEC = importlib.util.spec_from_file_location("portable_skill_runtime_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def stub_verified_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RUNTIME, "run_install_check", lambda _root: {"status": "pass"})
    monkeypatch.setattr(
        RUNTIME,
        "verify_embedded_signature",
        lambda _root: {
            "status": "verified",
            "public_key_fingerprint": RUNTIME.OFFICIAL_PUBLISHER_FINGERPRINT,
            "trust_model": "pinned-official-publisher",
        },
    )
    monkeypatch.setattr(
        RUNTIME,
        "check_runtime_requirements",
        lambda _manifest: {"status": "pass", "missing_required": []},
    )


def test_prepare_fails_when_existing_trust_record_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_verified_runtime(monkeypatch)
    monkeypatch.setattr(
        RUNTIME,
        "load_profile",
        lambda _path, skill: {
            **RUNTIME.empty_profile(skill),
            "trusted_publisher_fingerprint": "SHA256:conflicting-publisher",
        },
    )

    with pytest.raises(RUNTIME.PublisherTrustMismatch):
        RUNTIME.prepare(
            tmp_path / "skill",
            {"skill_name": "example", "release_tag": "V1"},
            tmp_path / "profile" / "profile.json",
            tmp_path / "profile" / "backups",
        )


def test_prepare_limits_only_auxiliary_preference_storage_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_verified_runtime(monkeypatch)
    monkeypatch.setattr(
        RUNTIME,
        "load_profile",
        lambda _path, _skill: (_ for _ in ()).throw(OSError("read-only profile")),
    )

    result = RUNTIME.prepare(
        tmp_path / "skill",
        {"skill_name": "example", "release_tag": "V1"},
        tmp_path / "profile" / "profile.json",
        tmp_path / "profile" / "backups",
    )

    assert result["status"] == "limited"
    assert result["signature_check"]["status"] == "verified"
    assert result["preference_check"]["status"] == "unavailable"
    assert result["limited_reasons"] == ["preference-storage-unavailable"]
    assert result["active_preferences"] == []


def test_prepare_writes_only_to_the_supplied_isolated_profile_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_verified_runtime(monkeypatch)
    profile = tmp_path / "isolated" / "example" / "profile.json"
    result = RUNTIME.prepare(
        tmp_path / "skill",
        {"skill_name": "example", "release_tag": "V1"},
        profile,
        profile.parent / "backups",
    )

    assert result["status"] == "pass"
    assert Path(result["profile_path"]) == profile
    assert profile.is_file()
    assert not (tmp_path / "profile.json").exists()

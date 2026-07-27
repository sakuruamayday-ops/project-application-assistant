from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "controlled_release.py"
SPEC = importlib.util.spec_from_file_location("controlled_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_normalize_version_uses_one_public_version_model() -> None:
    assert MODULE.normalize_version("V1.2") == ("1.2", "1.2.0", "V1.2")
    assert MODULE.normalize_version("1.2.0") == ("1.2", "1.2.0", "V1.2")
    assert MODULE.normalize_version("1.2.3") == ("1.2.3", "1.2.3", "V1.2.3")
    assert MODULE.normalize_version("V1.2.3") == ("1.2.3", "1.2.3", "V1.2.3")
    with pytest.raises(ValueError):
        MODULE.normalize_version("1.2.3.4")


def test_prepare_assets_contains_only_release_files(tmp_path) -> None:
    generic = tmp_path / "generic.zip"
    workbuddy = tmp_path / "workbuddy.zip"
    gate = tmp_path / "gate.json"
    for path in (generic, workbuddy, gate):
        path.write_text(path.name, encoding="utf-8")

    assets = MODULE.prepare_ascii_assets(
        tmp_path / "assets",
        "V1.3",
        generic,
        workbuddy,
        gate,
    )

    assert [path.name for path in assets] == [
        "jiaotang-skills-V1.3.zip",
        "jiaotang-skills-V1.3-WorkBuddy.zip",
        "jiaotang-skills-V1.3-release-gate.json",
    ]


def test_release_action_blocks_one_step_and_requires_exact_confirmation() -> None:
    assert MODULE.release_action(
        stage=False, promote=False, execute=False, confirm_text=""
    ) == "preflight"
    assert MODULE.release_action(
        stage=True, promote=False, execute=False, confirm_text=""
    ) == "stage"
    with pytest.raises(RuntimeError, match="一步直发已停用"):
        MODULE.release_action(
            stage=False, promote=False, execute=True, confirm_text=""
        )
    with pytest.raises(RuntimeError, match="缺少独立确认"):
        MODULE.release_action(
            stage=False, promote=True, execute=False, confirm_text=""
        )
    assert MODULE.release_action(
        stage=False,
        promote=True,
        execute=False,
        confirm_text="确认正式发布",
    ) == "promote"


def test_promote_cannot_create_a_missing_prerelease(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "asset.zip"
    notes = tmp_path / "notes.md"
    asset.write_bytes(b"asset")
    notes.write_text("V1.4", encoding="utf-8")
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="release not found",
        ),
    )

    with pytest.raises(RuntimeError, match="尚未进入正式发布中"):
        MODULE.ensure_prerelease(
            "owner/repository",
            "V1.4",
            "abc123",
            notes,
            [asset],
            create_if_missing=False,
        )

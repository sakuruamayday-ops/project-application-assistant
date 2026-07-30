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
    assert MODULE.normalize_version("1.2.3.4") == (
        "1.2.3.4",
        "1.2.3.4",
        "V1.2.3.4",
    )


def test_prepare_assets_contains_only_release_files(tmp_path) -> None:
    generic = tmp_path / "generic.zip"
    workbuddy = tmp_path / "workbuddy.zip"
    gate = tmp_path / "gate.json"
    for path in (generic, workbuddy, gate):
        path.write_text(path.name, encoding="utf-8")

    assets = MODULE.prepare_ascii_assets(
        tmp_path / "assets",
        "V1.3",
        {"generic": generic, "workbuddy": workbuddy},
        gate,
    )

    assert [path.name for path in assets] == [
        "jiaotang-skills-V1.3.zip",
        "jiaotang-skills-V1.3-WorkBuddy.zip",
        "jiaotang-skills-V1.3-release-gate.json",
    ]


def test_prepare_assets_includes_word_manual_and_companion_audit(tmp_path) -> None:
    generic = tmp_path / "generic.zip"
    gate = tmp_path / "gate.json"
    manual = tmp_path / "manual.docx"
    companion = tmp_path / "companion.json"
    for path in (generic, gate, manual, companion):
        path.write_text(path.name, encoding="utf-8")

    assets = MODULE.prepare_ascii_assets(
        tmp_path / "assets",
        "V1.3.1.1",
        {"generic": generic},
        gate,
        {"manual": manual, "companion": companion},
    )

    assert [path.name for path in assets] == [
        "jiaotang-skills-V1.3.1.1.zip",
        "jiaotang-skills-V1.3.1.1-release-gate.json",
        "jiaotang-user-manual-V1.3.1.1.docx",
        "jiaotang-release-companions-V1.3.1.1.json",
    ]


def test_prepare_assets_allows_one_or_two_release_targets(tmp_path) -> None:
    packages = {}
    for target in ("generic", "workbuddy"):
        package = tmp_path / f"{target}.zip"
        package.write_text(target, encoding="utf-8")
        packages[target] = package
    gate = tmp_path / "gate.json"
    gate.write_text("gate", encoding="utf-8")

    assets = MODULE.prepare_ascii_assets(
        tmp_path / "assets",
        "V1.3.1.1",
        packages,
        gate,
    )
    assert [path.name for path in assets] == [
        "jiaotang-skills-V1.3.1.1.zip",
        "jiaotang-skills-V1.3.1.1-WorkBuddy.zip",
        "jiaotang-skills-V1.3.1.1-release-gate.json",
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


def test_local_skill_deployment_gate_is_fail_closed(
    tmp_path, monkeypatch
) -> None:
    captured = {}

    def pass_gate(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(
            returncode=0,
            stdout='{"status":"pass","report":"audit.json"}',
            stderr="",
        )

    monkeypatch.setattr(MODULE.subprocess, "run", pass_gate)
    result = MODULE.run_local_skill_deployment_gate(
        development_root=tmp_path / "development",
        generic_package=tmp_path / "generic.zip",
        install_root=tmp_path / "installed",
        config_dir=tmp_path / "config",
        audit_dir=tmp_path / "audit",
    )
    assert result["status"] == "pass"
    assert "--release-archive" in captured["command"]
    assert "--install-root" in captured["command"]

    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2,
            stdout="",
            stderr='{"status":"fail","error":"hash mismatch"}',
        ),
    )
    with pytest.raises(RuntimeError, match="hash mismatch"):
        MODULE.run_local_skill_deployment_gate(
            development_root=tmp_path / "development",
            generic_package=tmp_path / "generic.zip",
            install_root=tmp_path / "installed",
            config_dir=tmp_path / "config",
            audit_dir=tmp_path / "audit",
        )


def test_controlled_release_requires_generic_package(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        MODULE.sys,
        "argv",
        [
            "controlled_release.py",
            "--version",
            "1.4.0",
            "--workbuddy-package",
            str(tmp_path / "workbuddy.zip"),
            "--gate-report",
            str(tmp_path / "gate.json"),
            "--release-notes",
            str(tmp_path / "notes.md"),
        ],
    )
    with pytest.raises(SystemExit) as raised:
        MODULE.main()
    assert raised.value.code == 2
    assert "--generic-package" in capsys.readouterr().err

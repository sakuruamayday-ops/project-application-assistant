from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "controlled_release.py"
SPEC = importlib.util.spec_from_file_location("controlled_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_release_json_serializes_nested_paths(tmp_path: Path) -> None:
    payload = {
        "status": "preflight-pass",
        "gate_attestation": {
            "signature": tmp_path / "release-gates.json.sig",
        },
    }

    rendered = json.loads(MODULE.release_json(payload))

    assert rendered["gate_attestation"]["signature"] == str(
        tmp_path / "release-gates.json.sig"
    )


def test_remote_release_commands_use_current_runtime_slot() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert MODULE.REMOTE_RELEASE_ROOT == "/opt/jiaotang-kb-runtime/current"
    assert source.count("REMOTE_RELEASE_ROOT") == 7
    assert "/opt/jiaotang-kb/.venv/bin/python" not in source


def test_companion_delivery_uses_absolute_recoverable_workspace() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Path(companion_workspace.name)" not in source
    assert "companion_builder.deliver(\n                ROOT,\n                companion_workspace," in source


def fake_gate_attestation(
    gate: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signature = gate.with_name(gate.name + ".sig")
    metadata = gate.with_name(gate.name + ".signature.json")
    public_key = gate.with_name(gate.stem + "-publisher-ed25519.pub")
    for path in (signature, metadata, public_key):
        path.write_text(path.name, encoding="utf-8")
    monkeypatch.setattr(
        MODULE,
        "verify_gate_attestation",
        lambda _path: {
            "status": "verified",
            "signature": signature,
            "metadata": metadata,
            "public_key": public_key,
        },
    )


def test_normalize_version_uses_one_public_version_model() -> None:
    assert MODULE.normalize_version("V1.2") == ("1.2", "1.2.0", "V1.2")
    assert MODULE.normalize_version("1.2.0") == (
        "1.2.0",
        "1.2.0",
        "V1.2.0",
    )
    assert MODULE.normalize_version("1.2.3") == ("1.2.3", "1.2.3", "V1.2.3")
    assert MODULE.normalize_version("V1.2.3") == ("1.2.3", "1.2.3", "V1.2.3")
    assert MODULE.normalize_version("1.2.3.4") == (
        "1.2.3.4",
        "1.2.3.4",
        "V1.2.3.4",
    )


def test_prepare_assets_contains_only_release_files(
    tmp_path,
    monkeypatch,
) -> None:
    generic = tmp_path / "generic.zip"
    workbuddy = tmp_path / "workbuddy.zip"
    gate = tmp_path / "gate.json"
    for path in (generic, workbuddy, gate):
        path.write_text(path.name, encoding="utf-8")
    fake_gate_attestation(gate, monkeypatch)

    assets = MODULE.prepare_ascii_assets(
        tmp_path / "assets",
        "V1.3",
        {"generic": generic, "workbuddy": workbuddy},
        gate,
    )

    assert [path.name for path in assets] == [
        "jiaotang-skills-V1.3.zip",
        "jiaotang-skills-V1.3-WorkBuddy.zip",
        "gate.json",
        "gate.json.sig",
        "gate.json.signature.json",
        "gate-publisher-ed25519.pub",
    ]


def test_prepare_assets_includes_word_manual_and_companion_audit(
    tmp_path,
    monkeypatch,
) -> None:
    generic = tmp_path / "generic.zip"
    gate = tmp_path / "gate.json"
    manual = tmp_path / "manual.docx"
    companion = tmp_path / "companion.json"
    for path in (generic, gate, manual, companion):
        path.write_text(path.name, encoding="utf-8")
    fake_gate_attestation(gate, monkeypatch)

    assets = MODULE.prepare_ascii_assets(
        tmp_path / "assets",
        "V1.3.1.1",
        {"generic": generic},
        gate,
        {"manual": manual, "companion": companion},
    )

    assert [path.name for path in assets] == [
        "jiaotang-skills-V1.3.1.1.zip",
        "gate.json",
        "gate.json.sig",
        "gate.json.signature.json",
        "gate-publisher-ed25519.pub",
        "jiaotang-user-manual-V1.3.1.1.docx",
        "jiaotang-release-companions-V1.3.1.1.json",
    ]


def test_prepare_assets_allows_one_or_two_release_targets(
    tmp_path,
    monkeypatch,
) -> None:
    packages = {}
    for target in ("generic", "workbuddy"):
        package = tmp_path / f"{target}.zip"
        package.write_text(target, encoding="utf-8")
        packages[target] = package
    gate = tmp_path / "gate.json"
    gate.write_text("gate", encoding="utf-8")
    fake_gate_attestation(gate, monkeypatch)

    assets = MODULE.prepare_ascii_assets(
        tmp_path / "assets",
        "V1.3.1.1",
        packages,
        gate,
    )
    assert [path.name for path in assets] == [
        "jiaotang-skills-V1.3.1.1.zip",
        "jiaotang-skills-V1.3.1.1-WorkBuddy.zip",
        "gate.json",
        "gate.json.sig",
        "gate.json.signature.json",
        "gate-publisher-ed25519.pub",
    ]


def test_release_action_blocks_one_step_and_requires_exact_confirmation() -> None:
    assert MODULE.release_action(
        stage=False,
        promote=False,
        monitor=False,
        execute=False,
        confirm_text="",
    ) == "preflight"
    assert MODULE.release_action(
        stage=True,
        promote=False,
        monitor=False,
        execute=False,
        confirm_text="",
    ) == "stage"
    assert MODULE.release_action(
        stage=False,
        promote=False,
        monitor=True,
        execute=False,
        confirm_text="",
    ) == "monitor"
    with pytest.raises(RuntimeError, match="一步直发已停用"):
        MODULE.release_action(
            stage=False,
            promote=False,
            monitor=False,
            execute=True,
            confirm_text="",
        )
    with pytest.raises(RuntimeError, match="缺少独立确认"):
        MODULE.release_action(
            stage=False,
            promote=True,
            monitor=False,
            execute=False,
            confirm_text="",
        )
    assert MODULE.release_action(
        stage=False,
        promote=True,
        monitor=False,
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


def test_isolated_skill_acceptance_gate_is_fail_closed(
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
    result = MODULE.run_isolated_skill_acceptance_gate(
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
        MODULE.run_isolated_skill_acceptance_gate(
            development_root=tmp_path / "development",
            generic_package=tmp_path / "generic.zip",
            install_root=tmp_path / "installed",
            config_dir=tmp_path / "config",
            audit_dir=tmp_path / "audit",
        )


def test_release_installation_acceptance_uses_isolated_persistent_root(
    tmp_path,
) -> None:
    active_skills = Path.home() / ".codex" / "skills"
    acceptance_root = MODULE.create_isolated_skill_acceptance_root(
        tmp_path / "audit"
    )

    assert acceptance_root.parent == (
        tmp_path / "audit" / "isolated-installation-acceptance"
    )
    assert acceptance_root != active_skills
    assert acceptance_root.is_dir()


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


def test_transaction_manifest_binds_all_three_release_participants(
    tmp_path,
) -> None:
    generic = tmp_path / "generic.zip"
    workbuddy = tmp_path / "workbuddy.zip"
    release_notes = tmp_path / "notes.md"
    generic.write_bytes(b"generic")
    workbuddy.write_bytes(b"workbuddy")
    release_notes.write_text("notes", encoding="utf-8")
    validation = {
        "short_version": "1.4.1",
        "semantic_version": "1.4.1",
        "tag": "V1.4.1",
        "skill_total": 49,
        "artifacts": {
            "generic": {"sha256": MODULE.sha256(generic)},
            "workbuddy": {"sha256": MODULE.sha256(workbuddy)},
        },
    }
    manifest = MODULE.build_release_transaction_manifest(
        repository="owner/repository",
        commit="abc123",
        validation=validation,
        release_assets=[release_notes, workbuddy, generic],
        publisher_fingerprint="SHA256:publisher",
    )
    repeated = MODULE.build_release_transaction_manifest(
        repository="owner/repository",
        commit="abc123",
        validation=validation,
        release_assets=[generic, release_notes, workbuddy],
        publisher_fingerprint="SHA256:publisher",
    )

    assert manifest == repeated
    assert set(manifest["participants"]) == {
        "github",
        "portal",
        "installation",
    }
    assert (
        manifest["participants"]["portal"]["package_sha256"]["generic"]
        == MODULE.sha256(generic)
    )
    assert manifest["lease_policy"]["single_writer"] is True
    assert (
        manifest["lease_policy"]["non_holder_mode"]
        == "read-only-monitor"
    )


def test_release_lease_checkpoint_is_owner_scoped_and_secret(tmp_path) -> None:
    path_a = MODULE.lease_checkpoint_path(
        config_dir=tmp_path,
        tag="V1.4.1",
        holder_id="thread-a",
    )
    path_b = MODULE.lease_checkpoint_path(
        config_dir=tmp_path,
        tag="V1.4.1",
        holder_id="thread-b",
    )
    assert path_a != path_b

    credential = MODULE.load_or_create_lease_credential(
        path=path_a,
        holder_id="thread-a",
        transaction_sha256="a" * 64,
        create=True,
    )
    assert credential["holder_id"] == "thread-a"
    assert len(credential["lease_token"]) >= 32
    assert stat.S_IMODE(path_a.stat().st_mode) == 0o600

    with pytest.raises(RuntimeError, match="凭证与当前签名事务不一致"):
        MODULE.load_or_create_lease_credential(
            path=path_a,
            holder_id="thread-b",
            transaction_sha256="a" * 64,
            create=False,
        )

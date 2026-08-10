from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "controlled_release.py"
SPEC = importlib.util.spec_from_file_location("controlled_release_test", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def fixture_inputs(tmp_path: Path):
    root = tmp_path / "repo"
    skills = root / "skills"
    skills.mkdir(parents=True)
    suite = {
        "release": {
            "tag": "V1.4.3",
            "version": "1.4.3",
            "summary": "安全发布",
            "changes": ["绑定来源"],
        },
        "skills": ["sample"],
    }
    manifest_path = skills / "suite-manifest.json"
    manifest_path.write_text(json.dumps(suite), encoding="utf-8")
    (root / "pyproject.toml").write_text(
        'version = "1.4.3"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("V1.4.3\n", encoding="utf-8")
    notes = tmp_path / "notes.md"
    notes.write_text(
        "V1.4.3\n安全发布\n绑定来源\n",
        encoding="utf-8",
    )
    generic = tmp_path / "generic.zip"
    workbuddy = tmp_path / "workbuddy.zip"
    for path, target in ((generic, "generic"), (workbuddy, "workbuddy")):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"target": target}))
    packages = {"generic": generic, "workbuddy": workbuddy}
    provenance = {
        "git_commit": "abc123",
        "git_tree": "tree123",
        "dirty": False,
        "tracked_source_sha256": "source-digest",
        "tracked_files": 3,
        "suite_manifest_sha256": MODULE.sha256(manifest_path),
        "release_manager_sha256": {"package.py": "0" * 64},
        "toolchain": {"python": {"version": "3.test"}},
    }
    gate = {
        "status": "pass",
        "failed": [],
        "passed": 2,
        "gate_count": 2,
        "source_provenance": provenance,
        "final_artifacts_complete": True,
        "final_artifacts": {
            target: {"sha256": MODULE.sha256(path)}
            for target, path in packages.items()
        },
    }
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    return root, packages, gate_path, notes, gate


def install_fakes(monkeypatch: pytest.MonkeyPatch, packages: dict[str, Path]):
    artifacts = {
        target: {"sha256": MODULE.sha256(path)}
        for target, path in packages.items()
    }
    monkeypatch.setattr(
        MODULE,
        "load_portal_publisher",
        lambda _root: SimpleNamespace(
            validate_release_packages=lambda _packages, _version: {
                "targets": list(_packages),
                "artifacts": artifacts,
            }
        ),
    )
    monkeypatch.setattr(
        MODULE,
        "tracked_source_digest",
        lambda _root: ("source-digest", 3),
    )
    monkeypatch.setattr(
        MODULE,
        "verify_gate_attestation",
        lambda _path: {
            "status": "verified",
            "publisher_fingerprint": MODULE.OFFICIAL_PUBLISHER_FINGERPRINT,
        },
    )
    monkeypatch.setattr(
        MODULE,
        "validate_release_provenance_environment",
        lambda _provenance: None,
    )
    monkeypatch.setattr(
        MODULE,
        "run",
        lambda command, **_kwargs: (
            "tree123" if command[-1] == "HEAD^{tree}" else ""
        ),
    )


def test_gate_provenance_matches_commit_source_and_final_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root, packages, gate, notes, _payload = fixture_inputs(tmp_path)
    install_fakes(monkeypatch, packages)
    result = MODULE.validate_inputs(
        root,
        "1.4.3",
        packages,
        gate,
        notes,
        "abc123",
    )
    assert result["source_provenance"]["git_commit"] == "abc123"
    assert result["artifacts"]["generic"]["sha256"] == MODULE.sha256(
        packages["generic"]
    )


def test_tracked_source_digest_uses_explicit_repository_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "tracked.txt").write_text("content", encoding="utf-8")
    seen: list[list[str]] = []

    def fake_run(command, **_kwargs):
        seen.append(command)
        return "tracked.txt\0"

    monkeypatch.setattr(MODULE, "run", fake_run)
    digest, count = MODULE.tracked_source_digest(repository)
    assert count == 1
    assert digest
    assert seen == [
        ["git", "-C", str(repository), "ls-files", "-z"]
    ]


def test_default_branch_validation_uses_repository_root_from_any_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    outside = tmp_path / "outside"
    outside.mkdir()
    seen: list[list[str]] = []

    def fake_run(command, **_kwargs):
        seen.append(command)
        if command[-4:] == ["config", "--local", "--get", "jiaotang.deployWorktree"]:
            return str(MODULE.ROOT)
        if command[-2:] == ["branch", "--show-current"]:
            return "main"
        if command[-2:] == ["rev-parse", "HEAD"]:
            return "abc123"
        if command[-2:] == ["rev-parse", "origin/main"]:
            return "abc123"
        return ""

    monkeypatch.chdir(outside)
    monkeypatch.setattr(MODULE, "run", fake_run)
    monkeypatch.setattr(
        MODULE,
        "json_command",
        lambda _command: {"defaultBranchRef": {"name": "main"}},
    )

    assert MODULE.validate_clean_default_branch("owner/repository") == "abc123"
    git_commands = [command for command in seen if command[0] == "git"]
    assert git_commands
    assert all(
        command[:3] == ["git", "-C", str(MODULE.ROOT)]
        for command in git_commands
    )


def test_unsigned_handwritten_gate_report_is_rejected(tmp_path: Path):
    gate = tmp_path / "release-gates-V1.4.3.json"
    gate.write_text(
        json.dumps(
            {
                "status": "pass",
                "failed": [],
                "passed": 1,
                "gate_count": 1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="签名元数据"):
        MODULE.verify_gate_attestation(gate)


def test_release_manager_hashes_are_recomputed_not_just_nonempty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manager = tmp_path / "manager"
    scripts = manager / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "package.py").write_text("print('trusted')\n", encoding="utf-8")
    monkeypatch.setenv("JIAOTANG_RELEASE_MANAGER_ROOT", str(manager))
    provenance = {
        "release_manager_sha256": {"package.py": "f" * 64},
        "toolchain": {},
    }
    with pytest.raises(RuntimeError, match="发布管理器"):
        MODULE.validate_release_provenance_environment(provenance)


@pytest.mark.parametrize("mutation", ["commit", "artifact"])
def test_gate_provenance_rejects_replay_or_package_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
):
    root, packages, gate_path, notes, gate = fixture_inputs(tmp_path)
    install_fakes(monkeypatch, packages)
    if mutation == "commit":
        gate["source_provenance"]["git_commit"] = "old-commit"
    else:
        gate["final_artifacts"]["generic"]["sha256"] = "f" * 64
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    with pytest.raises(RuntimeError, match="不一致"):
        MODULE.validate_inputs(
            root,
            "1.4.3",
            packages,
            gate_path,
            notes,
            "abc123",
        )

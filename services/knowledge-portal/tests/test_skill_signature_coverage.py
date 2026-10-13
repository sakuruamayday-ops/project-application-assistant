from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_skill_signature_coverage.py"
SPEC = importlib.util.spec_from_file_location("verify_skill_signature_coverage", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_current_suite_has_complete_verified_signature_coverage():
    skills_root = Path(__file__).resolve().parents[3] / "skills"
    result = MODULE.validate_signature_coverage(skills_root)
    assert result["status"] == "pass", result["errors"]
    expected = len(json.loads((skills_root / "suite-manifest.json").read_text(encoding="utf-8"))["skills"])
    assert result["signature_count"] == result["skill_total"] == expected
    assert result["verified_count"] == result["skill_total"]


def test_missing_signature_blocks_deployment(tmp_path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "unsigned-skill"
    skill_dir.mkdir(parents=True)
    (skills_root / "suite-manifest.json").write_text(
        json.dumps({"release": {"tag": "V1.1"}, "skills": ["unsigned-skill"]}),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("---\nname: unsigned-skill\n---\n", encoding="utf-8")

    result = MODULE.validate_signature_coverage(skills_root)

    assert result["status"] == "fail"
    assert result["signature_count"] == 0
    assert any("签名数量 0 与技能总数 1 不一致" in error for error in result["errors"])


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_invalid_signature_is_rejected_and_own_verification_files_are_recoverable(tmp_path, monkeypatch, platform):
    skills_root = Path(__file__).resolve().parents[3] / "skills"
    skill_name = json.loads((skills_root / "suite-manifest.json").read_text())["skills"][0]
    skill_dir = tmp_path / "tampered-skill"
    skill_dir.mkdir()
    for name in MODULE.SIGNATURE_FILES:
        shutil.copy2(skills_root / skill_name / name, skill_dir / name)
    (skill_dir / "release-manifest.json").write_text('{"tampered":true}\n')
    metadata = json.loads((skill_dir / "release-signature.json").read_text())
    fake_home = tmp_path / "home"
    monkeypatch.setattr(MODULE.Path, "home", lambda: fake_home)
    monkeypatch.setattr(MODULE.sys, "platform", platform)
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_home / ".local/share"))

    assert MODULE.verify_ed25519(skill_dir, metadata) == "发布清单 Ed25519 验签失败"

    trash = fake_home / ".Trash" if platform == "darwin" else fake_home / ".local/share/Trash/files"
    retained = list(trash.iterdir())
    assert len(retained) == 1
    assert (retained[0] / "allowed_signers").read_text().startswith("publisher ")
    if platform != "darwin":
        assert (trash.parent / "info" / (retained[0].name + ".trashinfo")).is_file()


def test_gate_result_can_be_persisted_for_admin_dashboard(tmp_path):
    skills_root = Path(__file__).resolve().parents[3] / "skills"
    output = tmp_path / "skill-deploy-gate-status.json"
    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--skills-root", str(skills_root), "--output", str(output), "--deployment-id", "test-20260726", "--scope", "production"],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert process.returncode == 0
    assert payload["status"] == "pass"
    assert payload["deployment_id"] == "test-20260726"
    assert payload["scope"] == "production"
    expected = len(json.loads((skills_root / "suite-manifest.json").read_text(encoding="utf-8"))["skills"])
    assert payload["verified_count"] == payload["skill_total"] == expected

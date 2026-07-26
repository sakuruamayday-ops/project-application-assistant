from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_skill_signature_coverage.py"
SPEC = importlib.util.spec_from_file_location("verify_skill_signature_coverage", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_current_suite_has_complete_verified_signature_coverage():
    skills_root = Path(__file__).resolve().parents[3] / "skills"
    result = MODULE.validate_signature_coverage(skills_root)
    assert result["status"] == "pass", result["errors"]
    assert result["signature_count"] == result["skill_total"] == 56
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
    assert payload["verified_count"] == payload["skill_total"] == 56

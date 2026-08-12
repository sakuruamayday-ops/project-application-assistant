from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_local_formal_skill_drift.py"


def run_audit(skills_root: Path, local_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skills-root",
            str(skills_root),
            "--local-root",
            str(local_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def write_fixture(root: Path) -> Path:
    skills = root / "skills"
    skills.mkdir()
    (skills / "suite-manifest.json").write_text(
        json.dumps({"skills": ["enterprise-profile", "gongchuang-humanizer-zh"]}),
        encoding="utf-8",
    )
    (skills / "local-skill-reconciliation.json").write_text(
        json.dumps(
            {
                "entries": {
                    "jiaotang-enterprise-verification": {
                        "status": "retained_local_extension",
                        "formal_target": "enterprise-profile",
                        "reason": "test",
                    },
                    "jiaotang-humanizer-zh": {
                        "status": "merged_into",
                        "formal_target": "gongchuang-humanizer-zh",
                        "reason": "test",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return skills


def test_audit_accepts_registered_formal_and_local_extensions(tmp_path: Path) -> None:
    skills = write_fixture(tmp_path)
    local = tmp_path / "local"
    (local / "jiaotang-humanizer-zh").mkdir(parents=True)
    (local / "jiaotang-enterprise-verification").mkdir()
    result = run_audit(skills, local)
    assert result.returncode == 0, result.stdout + result.stderr


def test_audit_rejects_unregistered_local_jiaotang_skill(tmp_path: Path) -> None:
    skills = write_fixture(tmp_path)
    local = tmp_path / "local"
    (local / "jiaotang-unknown").mkdir(parents=True)
    result = run_audit(skills, local)
    assert result.returncode == 2
    assert "jiaotang-unknown" in result.stdout

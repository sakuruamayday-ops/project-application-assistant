from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_local_formal_skill_drift.py"


def run_audit(skills_root: Path, *local_roots: Path) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--skills-root",
        str(skills_root),
    ]
    for local_root in local_roots:
        command.extend(["--local-root", str(local_root)])
    return subprocess.run(command, check=False, capture_output=True, text=True)


def write_skill(root: Path, name: str) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")


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
                        "source": "local",
                        "owner": "owner",
                        "package_policy": "exclude_from_suite",
                    },
                    "jiaotang-humanizer-zh": {
                        "status": "merged_into",
                        "formal_target": "gongchuang-humanizer-zh",
                        "reason": "test",
                        "source": "local",
                        "owner": "owner",
                        "package_policy": "exclude_from_suite",
                    },
                    "openai-docs": {
                        "status": "system_skill",
                        "formal_target": None,
                        "reason": "host system skill",
                        "source": "system",
                        "owner": "host",
                        "package_policy": "exclude_from_suite",
                    },
                    "skill-release-manager": {
                        "status": "administrator_tool",
                        "formal_target": None,
                        "reason": "publisher only",
                        "source": "administrator",
                        "owner": "publisher",
                        "package_policy": "exclude_from_suite",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return skills


def test_audit_accepts_full_inventory_classification(tmp_path: Path) -> None:
    skills = write_fixture(tmp_path)
    codex = tmp_path / "codex"
    agents = tmp_path / "agents"
    system = tmp_path / "system"
    for name in ("enterprise-profile", "gongchuang-humanizer-zh", "jiaotang-humanizer-zh", "skill-release-manager"):
        write_skill(codex, name)
    write_skill(agents, "jiaotang-enterprise-verification")
    write_skill(system, "openai-docs")
    result = run_audit(skills, codex, agents, system)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["package_input"] == "suite-manifest.json:skills"
    assert payload["discovered_skill_count"] == 6


def test_audit_rejects_unregistered_skill_regardless_of_prefix(tmp_path: Path) -> None:
    skills = write_fixture(tmp_path)
    local = tmp_path / "local"
    for name in ("enterprise-profile", "gongchuang-humanizer-zh", "unknown-vendor-skill"):
        write_skill(local, name)
    result = run_audit(skills, local)
    assert result.returncode == 2
    assert "unknown-vendor-skill" in result.stdout


def test_audit_rejects_missing_formal_skill(tmp_path: Path) -> None:
    skills = write_fixture(tmp_path)
    local = tmp_path / "local"
    write_skill(local, "enterprise-profile")
    result = run_audit(skills, local)
    assert result.returncode == 2
    assert "gongchuang-humanizer-zh" in result.stdout


def test_audit_rejects_nonformal_classification_for_manifest_skill(tmp_path: Path) -> None:
    skills = write_fixture(tmp_path)
    ledger = json.loads((skills / "local-skill-reconciliation.json").read_text())
    ledger["entries"]["enterprise-profile"] = {
        "status": "external_capability",
        "formal_target": None,
        "reason": "invalid",
        "source": "test",
        "owner": "test",
        "package_policy": "exclude_from_suite",
    }
    (skills / "local-skill-reconciliation.json").write_text(json.dumps(ledger))
    local = tmp_path / "local"
    write_skill(local, "enterprise-profile")
    write_skill(local, "gongchuang-humanizer-zh")
    result = run_audit(skills, local)
    assert result.returncode == 2
    assert "manifest skill cannot be duplicated" in result.stdout

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
RELEASE_MANAGER = Path("/Users/zsh/.codex/skills/skill-release-manager")


def run_validator(relative_script: str, payload: dict, tmp_path: Path):
    document = tmp_path / "payload.json"
    document.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SKILLS / relative_script), str(document)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_feasibility_validator_accepts_traceable_result(tmp_path):
    payload = {
        "project_context": {
            "project_name": "测试项目",
            "region": "浙江省",
            "year": 2026,
            "application_type": "new",
            "policy_status": "current",
        },
        "overall_conclusion": "eligible",
        "hard_gates": [
            {
                "rule_id": "H1",
                "source": "当期通知",
                "status": "passed",
                "evidence_state": "verified",
            }
        ],
        "scoring": {},
        "calculations": [],
        "uncertainties": [],
        "evidence_gaps": [],
        "actions": [],
    }
    result = run_validator(
        "project-feasibility/scripts/validate_feasibility_assessment.py",
        payload,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_feasibility_validator_blocks_unverified_pass(tmp_path):
    payload = {
        "project_context": {
            "project_name": "测试项目",
            "region": "浙江省",
            "year": 2026,
            "application_type": "new",
            "policy_status": "current",
        },
        "overall_conclusion": "eligible",
        "hard_gates": [
            {
                "rule_id": "H1",
                "source": "企业自述",
                "status": "passed",
                "evidence_state": "claimed",
            }
        ],
        "scoring": {},
        "calculations": [],
        "uncertainties": [],
        "evidence_gaps": [],
        "actions": [],
    }
    result = run_validator(
        "project-feasibility/scripts/validate_feasibility_assessment.py",
        payload,
        tmp_path,
    )
    assert result.returncode != 0
    assert "证据不足" in result.stdout


def test_financial_validator_requires_formula_and_sources(tmp_path):
    payload = {
        "identity": {"company_name": "测试有限公司"},
        "scope": {
            "period": "2025",
            "currency": "CNY",
            "unit": "元",
            "consolidation_scope": "合并",
        },
        "sources": [{"id": "S1", "type": "audit"}],
        "facts": [{"name": "营业收入", "status": "verified", "source_ids": ["S1"]}],
        "metrics": [
            {
                "metric": "资产负债率",
                "formula": "负债/资产",
                "inputs": {"负债": 1, "资产": 2},
                "unit": "%",
                "result": 50,
                "status": "computed",
                "source_ids": ["S1"],
            }
        ],
        "conflicts": [],
        "quality": "verified",
    }
    result = run_validator(
        "financial-verification/scripts/validate_financial_assessment.py",
        payload,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_sme_validator_requires_all_four_judgments(tmp_path):
    item = {
        "decision": "retain",
        "evidence_state": "verified",
        "object": "主导产品",
        "reason": "证据闭环",
        "actions": ["保持一致"],
    }
    payload = {
        "application_context": {
            "project_level": "specialized-sme",
            "region": "浙江省",
            "year": 2026,
            "application_type": "new",
            "form_version": "2026",
            "version_status": "confirmed",
            "policy_status": "current",
        },
        "overall_conclusion": "conditional",
        "four_judgments": {
            "leading_product": item,
            "bottleneck": item,
            "gap_filling": item,
            "import_substitution": item,
        },
        "hard_gates": [],
        "evaluation": {},
        "evidence_gaps": [],
        "risks": [],
        "actions": [],
    }
    result = run_validator(
        "sme-development-projects/scripts/validate_sme_assessment.py",
        payload,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_policy_freshness_current_manifest_passes():
    result = subprocess.run(
        [
            sys.executable,
            str(RELEASE_MANAGER / "scripts" / "validate_policy_freshness.py"),
            "--skills-root",
            str(SKILLS),
            "--as-of",
            "2026-07-27",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_policy_freshness_blocks_after_review_date():
    result = subprocess.run(
        [
            sys.executable,
            str(RELEASE_MANAGER / "scripts" / "validate_policy_freshness.py"),
            "--skills-root",
            str(SKILLS),
            "--as-of",
            "2026-11-01",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "超过下次复核日期" in result.stdout


def load_collection_module():
    path = RELEASE_MANAGER / "scripts" / "package_skill_collection.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("package_skill_collection_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_release_gate_failure_blocks(tmp_path):
    module = load_collection_module()
    skills = tmp_path / "skills"
    skills.mkdir()
    source = skills / "source.txt"
    source.write_text("policy", encoding="utf-8")
    import hashlib

    manifest = {
        "policy_freshness_manifest": "policy-freshness-manifest.json",
        "release_gates": [
            {
                "name": "forced-failure",
                "command": ["{python}", "-c", "raise SystemExit(7)"],
                "timeout_seconds": 10,
            }
        ],
    }
    (skills / "policy-freshness-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "as_of_timezone": "Asia/Shanghai",
                "records": [
                    {
                        "id": "test",
                        "path": "source.txt",
                        "verified_at": "2026-07-24",
                        "effective_from": "2026-01-01",
                        "effective_until": None,
                        "next_review_at": "2099-01-01",
                        "source_locator": "test",
                        "source_sha256": hashlib.sha256(b"policy").hexdigest(),
                        "block_after_next_review": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = module.run_release_gates(tmp_path, skills, manifest)
    assert report["status"] == "fail"
    assert "forced-failure" in report["failed"]

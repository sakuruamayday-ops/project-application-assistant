import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
RELEASE_MANAGER = Path(
    os.environ.get(
        "JIAOTANG_RELEASE_MANAGER_ROOT",
        Path.home() / ".codex/skills/skill-release-manager",
    )
)
POLICY_FRESHNESS_SCRIPT = (
    RELEASE_MANAGER / "scripts" / "validate_policy_freshness.py"
)
COLLECTION_SCRIPT = (
    RELEASE_MANAGER / "scripts" / "package_skill_collection.py"
)
requires_policy_freshness_host = pytest.mark.skipif(
    not POLICY_FRESHNESS_SCRIPT.is_file(),
    reason="requires the separately installed policy-freshness host gate",
)
requires_collection_host = pytest.mark.skipif(
    not COLLECTION_SCRIPT.is_file(),
    reason="requires the separately installed release collection host gate",
)


def run_validator(relative_script: str, payload: dict, tmp_path: Path):
    document = tmp_path / "payload.json"
    document.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SKILLS / relative_script), str(document)],
        check=False,
        capture_output=True,
        text=True,
    )


def load_script(relative_script: str):
    path = SKILLS / relative_script
    specification = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(specification)
    assert specification.loader is not None
    specification.loader.exec_module(module)
    return module


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


def test_feasibility_validator_recomputes_formula_semantics(tmp_path):
    payload = {
        "project_context": {
            "project_name": "测试项目",
            "region": "浙江省",
            "year": 2026,
            "application_type": "new",
            "policy_status": "current",
        },
        "overall_conclusion": "eligible",
        "hard_gates": [{
            "rule_id": "H1",
            "source": "当期通知",
            "status": "passed",
            "evidence_state": "verified",
        }],
        "scoring": {},
        "calculations": [{
            "formula": "revenue / employees",
            "inputs": {"revenue": 1000, "employees": 10},
            "unit": "万元/人",
            "result": 999999,
            "review_status": "verified",
        }],
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
    assert "结果与公式不一致" in result.stdout


def test_feasibility_validator_accepts_three_year_growth_formula(tmp_path):
    payload = {
        "project_context": {
            "project_name": "高新技术企业认定",
            "region": "浙江省",
            "year": 2026,
            "application_type": "new",
            "policy_status": "current",
        },
        "overall_conclusion": "eligible",
        "hard_gates": [{
            "rule_id": "H1",
            "source": "当期通知",
            "status": "passed",
            "evidence_state": "verified",
        }],
        "scoring": {},
        "calculations": [{
            "formula": "0.5 * (y2 / y1 + y3 / y2) - 1",
            "inputs": {"y1": 2800, "y2": 5200, "y3": 7900},
            "unit": "%",
            "result": 68.81868131868131,
            "review_status": "verified",
        }],
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


def test_hightech_growth_uses_all_three_years_and_scores_18_to_20():
    module = load_script(
        "high-tech-enterprise-preassessment/scripts/compare_scenarios.py"
    )
    result = module.analyze_scenario(
        {
            "name": "2026申报",
            "revenue": [2800, 5200, 7900],
            "net_assets": [1800, 3100, 4700],
            "scores": {"ip": 0, "conversion": 0, "organization": 0},
        }
    )

    assert result["growth"]["revenue"]["rate"] == pytest.approx(0.688187, abs=1e-6)
    assert result["growth"]["net_assets"]["rate"] == pytest.approx(0.619176, abs=1e-6)
    assert result["growth"]["revenue"]["score_range"] == [9, 10]
    assert result["growth"]["net_assets"]["score_range"] == [9, 10]
    assert result["totals"]["conservative"] == 18
    assert result["totals"]["target"] == 20


@pytest.mark.parametrize("third,expected", [
    ("110", [3, 4]), ("109.999999999999999999", [1, 2]),
    ("130", [5, 6]), ("129.999999999999999999", [3, 4]),
    ("150", [7, 8]), ("149.999999999999999999", [5, 6]),
    ("170", [9, 10]), ("169.999999999999999999", [7, 8]),
])
def test_hightech_growth_compares_exact_decimal_thresholds(tmp_path, third, expected):
    path = tmp_path / "growth.json"
    path.write_text(
        '{"scenarios":[{"revenue":[100,100,' + third + '],'
        '"net_assets":[100,100,' + third + '],'
        '"scores":{"ip":20.5,"conversion":20,"organization":15}}]}',
        encoding="utf-8",
    )
    result = subprocess.run([
        sys.executable, str(ROOT / "skills/high-tech-enterprise-preassessment/scripts/compare_scenarios.py"),
        str(path),
    ], check=True, capture_output=True, text=True)
    scenario = json.loads(result.stdout)["scenarios"][0]
    for field in ("revenue", "net_assets"):
        assert scenario["growth"][field]["score_range"] == expected


@pytest.mark.parametrize("score,expected", [(70.9, "不建议"), (71, "临界"), (74.9, "临界"), (75, "原则上")])
def test_hightech_recommendation_receipt_matches_actual_internal_thresholds(score, expected):
    module = load_script("high-tech-enterprise-preassessment/scripts/compare_scenarios.py")
    result = module.analyze_scenario({
        "revenue": [100, 100, 100], "net_assets": [100, 100, 100],
        "scores": {"ip": 30, "conversion": 30, "organization": score - 60},
    })
    assert result["readiness"].startswith(expected)
    thresholds = result["internal_recommendation_thresholds"]
    assert thresholds["borderline_integer_score_range"] == [71, 74]
    assert thresholds["borderline_max_exclusive"] == thresholds["buffer_min_inclusive"] == 75
    assert "不是官方认定门槛" in thresholds["basis"]


def test_hightech_fifteen_percent_does_not_drop_a_band():
    module = load_script("high-tech-enterprise-preassessment/scripts/compare_scenarios.py")
    result = module.analyze_scenario({
        "revenue": [100, 115, 132.25], "net_assets": [100, 120, 144],
        "scores": {"ip": 20, "conversion": 20, "organization": 15},
    })
    assert result["growth"]["revenue"]["rate"] == 0.15
    assert result["growth"]["revenue"]["score_range"] == [5, 6]


def test_hightech_component_scores_sum_instead_of_reusing_stale_subtotals():
    module = load_script("high-tech-enterprise-preassessment/scripts/compare_scenarios.py")
    result = module.analyze_scenario({
        "revenue": [1200, 1500, 1800], "net_assets": [600, 690, 793.5],
        "scores": {
            "ip": {"target": 28, "components": [
                {"target": 8, "conservative": 5, "stress": 4},
                {"target": 8, "conservative": 8, "stress": 7},
                {"target": 8, "conservative": 7, "stress": 6},
                {"target": 6, "conservative": 4, "stress": 3},
            ]},
            "conversion": {"target": 12, "conservative": 7, "stress": 5},
            "organization": {"components": [
                {"target": 6, "conservative": 3, "stress": 2},
                {"target": 4, "conservative": 2, "stress": 1},
                {"target": 4, "conservative": 3, "stress": 2},
                {"target": 3, "conservative": 3, "stress": 2},
            ]},
        },
    })
    assert result["nonfinancial_scores"]["ip"] == {"target": 30, "conservative": 24, "stress": 20}
    assert result["nonfinancial_scores"]["organization"] == {"target": 17, "conservative": 11, "stress": 7}
    assert result["totals"] == {"target": 71, "conservative": 52, "stress": 42}


@pytest.mark.parametrize("components", [[], [{"target": 2, "conservative": 3, "stress": 1}],
    [{"target": 31, "conservative": 20, "stress": 10}],
    [{"target": "NaN", "conservative": 2, "stress": 1}],
    [{"target": "unknown", "conservative": 2, "stress": 1}],
])
def test_hightech_component_scores_reject_invalid_real_input(components):
    module = load_script("high-tech-enterprise-preassessment/scripts/compare_scenarios.py")
    with pytest.raises(ValueError):
        module.normalize_scores({"ip": {"components": components}, "conversion": 7, "organization": 9})


def test_hightech_component_decimal_sum_is_exact():
    module = load_script("high-tech-enterprise-preassessment/scripts/compare_scenarios.py")
    result = module.normalize_scores({"ip": {"components": [
        {"target": "0.1", "conservative": "0.1", "stress": 0},
        {"target": "0.2", "conservative": "0.2", "stress": 0},
    ]}, "conversion": 7, "organization": 9})
    assert result["ip"]["target"] == 0.3


@pytest.mark.parametrize("payload", [{}, {"scenarios": [{}]}, {
    "scenarios": [{"revenue": [1, 2, 3], "net_assets": [1, 2, 3], "scores": {}}],
}])
def test_hightech_invalid_input_returns_complete_repair_example(tmp_path, payload):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run([
        sys.executable, str(SKILLS / "high-tech-enterprise-preassessment/scripts/compare_scenarios.py"),
        str(source),
    ], capture_output=True, text=True)
    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    example = error["input_example"]["scenarios"][0]
    assert set(example) == {"name", "revenue", "net_assets", "scores"}
    assert set(example["scores"]) == {"ip", "conversion", "organization"}
    module = load_script("high-tech-enterprise-preassessment/scripts/compare_scenarios.py")
    assert module.analyze_scenario(example)["growth"]["revenue"]["percentage"] == "10.00%"


def test_hightech_signed_operation_returns_single_json_and_display_percentages(tmp_path):
    registry = json.loads((SKILLS / "client-runtime-operations.json").read_text(encoding="utf-8"))
    operation = next(row for row in registry["operations"]
                     if row["id"] == "high-tech-enterprise-preassessment.calculate-scenarios")
    source = tmp_path / "scenarios.json"
    source.write_text(json.dumps({"scenarios": [{
        "name": "2026申报", "revenue": [1200, 1500, 1800],
        "net_assets": [600, 690, 793.5],
        "scores": {"ip": 22, "conversion": 7, "organization": 9},
    }]}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SKILLS / operation["script"]), str(source)],
                            check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == operation["stdout_json_schema_version"]
    scenario = payload["scenarios"][0]
    assert scenario["growth"]["revenue"]["percentage"] == "22.50%"
    assert scenario["growth"]["net_assets"]["percentage"] == "15.00%"
    assert scenario["totals"]["conservative"] == 48


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
        "evaluation": {
            "quality_score": {
                "status": "pending-platform-evaluation",
                "value": None,
            }
        },
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


def test_sme_skill_documents_the_signed_validator_contract():
    skill_text = (
        SKILLS / "sme-development-projects" / "SKILL.md"
    ).read_text(encoding="utf-8")
    operation_registry = json.loads(
        (SKILLS / "client-runtime-operations.json").read_text(encoding="utf-8")
    )
    operation = next(
        item
        for item in operation_registry["operations"]
        if item["id"] == "sme-development-projects.validate-assessment"
    )

    assert '"assessment":"<工作区内结果.json>"' in skill_text
    assert "一次构造、一次调用" in operation["description"]
    assert "不创建无关探针或反复猜测枚举" in skill_text
    assert "未通过校验不得交付正式结论" in skill_text
    for token in (
        "application_context",
        "overall_conclusion",
        "four_judgments",
        "leading_product",
        "bottleneck",
        "gap_filling",
        "import_substitution",
        "hard_gates",
        "evaluation",
        "quality_score",
        "evidence_gaps",
        "risks",
        "actions",
        "eligible",
        "conditional",
        "ineligible",
        "undetermined",
        "retain",
        "replace",
        "retain-after-evidence",
        "verified",
        "computed",
        "claimed",
        "missing",
        "conflicting",
        "verified-platform-score",
        "pending-platform-evaluation",
    ):
        assert token in skill_text


def test_sme_validator_rejects_legacy_estimated_score(tmp_path):
    item = {
        "decision": "retain",
        "evidence_state": "claimed",
        "object": "主导产品",
        "reason": "材料叙事闭环",
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
        "overall_conclusion": "eligible",
        "four_judgments": {
            "leading_product": item,
            "bottleneck": item,
            "gap_filling": item,
            "import_substitution": item,
        },
        "hard_gates": [],
        "evaluation": {
            "estimated_score": 88,
            "quality_score": {
                "status": "pending-platform-evaluation",
                "value": None,
            },
        },
        "evidence_gaps": [],
        "risks": [],
        "actions": [],
    }
    result = run_validator(
        "sme-development-projects/scripts/validate_sme_assessment.py",
        payload,
        tmp_path,
    )
    assert result.returncode != 0
    assert "已停用的估分字段" in result.stdout
    assert "总体结论不得为eligible" in result.stdout


@requires_policy_freshness_host
def test_policy_freshness_current_manifest_passes():
    result = subprocess.run(
        [
            sys.executable,
            str(POLICY_FRESHNESS_SCRIPT),
            "--skills-root",
            str(SKILLS),
            "--as-of",
            "2026-10-04",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@requires_policy_freshness_host
def test_policy_freshness_blocks_after_review_date():
    result = subprocess.run(
        [
            sys.executable,
            str(POLICY_FRESHNESS_SCRIPT),
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
    path = COLLECTION_SCRIPT
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("package_skill_collection_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


@requires_collection_host
def test_release_gate_failure_blocks(tmp_path):
    module = load_collection_module()
    skills = tmp_path / "skills"
    skills.mkdir()
    source = skills / "source.txt"
    source.write_text("policy", encoding="utf-8")
    (skills / "suite-manifest.json").write_text(
        json.dumps({"schema_version": 1}),
        encoding="utf-8",
    )
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
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    report = module.run_release_gates(tmp_path, skills, manifest)
    assert report["status"] == "fail"
    assert "forced-failure" in report["failed"]

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALCULATOR = (
    ROOT / "skills/manufacturing-tax-risk-analysis/scripts/calculate_metrics.py"
)
VALIDATOR = ROOT / "skills/financial-verification/scripts/validate_financial_facts.py"


def load_calculator():
    spec = importlib.util.spec_from_file_location("calculate_metrics", CALCULATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def complete_year():
    module = load_calculator()
    return {name: 100.0 for name in module.REQUIRED}


def test_calculator_emits_reusable_financial_facts(tmp_path):
    source = tmp_path / "input.json"
    output = tmp_path / "facts.json"
    year = complete_year()
    year["inventory"] = None
    source.write_text(
        json.dumps(
            {
                "company": {
                    "name": "示例制造企业有限公司",
                    "unified_social_credit_code": "91330100TEST",
                },
                "basis": {
                    "currency": "CNY",
                    "unit": "yuan",
                    "consolidation_scope": "consolidated",
                },
                "years": {"2025": year},
                "evidence": {"2025": {"revenue": {"source": "审计报告", "page": 8}}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    subprocess.run([sys.executable, str(CALCULATOR), str(source), str(output)], check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "enterprise-financial-facts/v1"
    assert payload["company"]["unified_social_credit_code"] == "91330100TEST"
    assert payload["periods"]["2025"]["metrics"]["quick_ratio"] is None
    assert payload["periods"]["2025"]["quality"]["status"] == "unverified"
    assert payload["periods"]["2025"]["evidence"]["revenue"]["page"] == 8
    subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            str(output),
            "--company",
            "示例制造企业有限公司",
        ],
        check=True,
    )


def test_cross_skill_financial_reuse_is_declared():
    expected = {
        "skills/manufacturing-tax-risk-analysis/SKILL.md": "enterprise-financial-facts/v1",
        "skills/financial-verification/SKILL.md": "validate_financial_facts.py",
        "skills/project-feasibility/SKILL.md": "artifacts/enterprise-financial-facts.v1.json",
        "skills/project-task-router/SKILL.md": "enterprise-financial-facts/v1",
        "skills/project-application-assistant/SKILL.md": "enterprise-financial-facts/v1",
        "skills/sme-development-projects/SKILL.md": "enterprise-financial-facts/v1",
    }
    for relative, snippet in expected.items():
        assert snippet in (ROOT / relative).read_text(encoding="utf-8")


def test_delegation_protocol_is_platform_neutral():
    path = (
        ROOT
        / "skills/first-run-configuration/references/capability-delegation-protocol.md"
    )
    text = path.read_text(encoding="utf-8")
    assert "当前执行器不可达" in text
    assert "Coze" not in text
    assert "扣子" not in text

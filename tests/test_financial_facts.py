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


def test_calculator_emits_case_28_material_cross_period_findings(tmp_path):
    source = tmp_path / "input.json"
    facts_output = tmp_path / "facts.json"
    metrics_output = tmp_path / "metrics.json"
    years = {}
    rows = {
        "2023": (18000000, 14000000, 6000000, 8000000, 1800000, 2000000),
        "2024": (24000000, 18000000, 8000000, 10000000, 3000000, 3000000),
        "2025": (30000000, 20000000, 8000000, 9000000, 4500000, 5400000),
    }
    for year, (revenue, assets, liabilities, equity, research, receivables) in rows.items():
        record = {name: None for name in load_calculator().REQUIRED}
        record.update(
            {
                "revenue": revenue,
                "assets": assets,
                "liabilities": liabilities,
                "equity": equity,
                "research_expense": research,
                "receivables": receivables,
                "current_assets": 10000000,
                "current_liabilities": 5000000,
                "inventory": 2000000,
                "net_profit": 1000000,
            }
        )
        years[year] = record
    source.write_text(
        json.dumps(
            {
                "company": {"name": "共创测试制造企业"},
                "basis": {"currency": "CNY", "unit": "yuan"},
                "years": years,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run = subprocess.run(
        [
            sys.executable,
            str(CALCULATOR),
            str(source),
            str(facts_output),
            "--metrics-output",
            str(metrics_output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(run.stdout)
    assert receipt["schema_version"] == "manufacturing-tax-risk-calculation-operation/v1"
    assert "25.00%" in receipt["validation_values"]
    assert "25%" in receipt["validation_values"]
    assert "11.11%" in receipt["validation_values"]
    assert "44%" in receipt["validation_values"]
    assert "1,800.00万元" in receipt["validation_values"]
    assert "18,000,000.00元" in receipt["validation_values"]
    metrics = json.loads(metrics_output.read_text(encoding="utf-8"))
    assert metrics["schema"] == "manufacturing-tax-risk-metrics/v1"
    facts = json.loads(facts_output.read_text(encoding="utf-8"))
    assert facts["periods"]["2023"]["metrics"]["receivables_to_revenue"] == 2 / 18
    assert facts["periods"]["2025"]["metrics"]["receivables_to_revenue"] == 0.18
    report = {row["indicator"]: row["result"] for row in metrics["report_rows"]}
    assert report["2024年营业收入同比增长率"] == "33.33%"
    assert report["2025年营业收入同比增长率"] == "25.00%"
    assert report["2025年应收账款同比增长率"] == "80.00%"
    assert report["2025年研发费用率"] == "15.00%"
    assert report["2025年资产负债表恒等式差额"] == "3,000,000.00元（300.00万元）"
    assert "缺少营业成本、期初存货，无法计算" in report["2025年存货周转天数"]


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

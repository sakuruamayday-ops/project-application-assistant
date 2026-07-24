import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "tests/high-risk-script-matrix.json"


def load_python_module(relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_high_risk_matrix_has_existing_scripts_and_tests() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert matrix["schema_version"] == 1
    assert matrix["scripts"]
    for item in matrix["scripts"]:
        assert item["risk"] == "high"
        assert item["reason"].strip()
        script_path = ROOT / item["path"]
        test_file = ROOT / item["test"].split("::", 1)[0]
        assert script_path.is_file()
        assert test_file.is_file()


def test_sme_score_core_validation_and_industry_mapping() -> None:
    core = ROOT / "skills/sme-score-preassessment/scripts/score_core.mjs"
    javascript = f"""
      import {{ validateInput, resolveIndustry }} from {json.dumps(core.as_uri())};
      const metrics = {{
        revenue: [100, 120, 150],
        operating_cost: [60, 70, 80],
        selling_expense: [5, 6, 7],
        admin_expense: [8, 9, 10],
        total_profit: [10, 12, 15],
        total_assets: [200, 220, 250],
        total_liabilities: [80, 90, 100],
        average_employees: [20, 22, 25],
      }};
      validateInput({{
        company_name: "示例企业有限公司",
        latest_year: 2025,
        project_level: "省级专精特新中小企业",
      }}, metrics);
      const mapped = resolveIndustry({{
        industries: [
          {{ code: "C34", name: "通用设备制造业", keywords: ["装备", "机械"] }},
          {{ code: "C39", name: "计算机通信和其他电子设备制造业", keywords: ["芯片"] }},
        ],
      }}, {{ main_product: "智能机械装备", industry_hint: "" }}, {{}});
      if (mapped.code !== "C34") throw new Error("行业映射错误");
      let blocked = false;
      try {{
        validateInput({{
          company_name: "",
          latest_year: 2025,
          project_level: "",
        }}, metrics);
      }} catch (error) {{
        blocked = error.message.includes("企业完整名称为空")
          && error.message.includes("评估版本未确认");
      }}
      if (!blocked) throw new Error("无效输入未被阻断");
    """
    subprocess.run(
        ["node", "--input-type=module", "--eval", javascript],
        check=True,
        capture_output=True,
        text=True,
    )


def test_financial_assessment_validator() -> None:
    validator = load_python_module(
        "skills/financial-verification/scripts/validate_financial_assessment.py"
    )
    valid = {
        "identity": {"company_name": "示例企业有限公司"},
        "scope": {
            "period": "2025",
            "currency": "CNY",
            "unit": "yuan",
            "consolidation_scope": "consolidated",
        },
        "sources": [{"id": "audit-2025"}],
        "facts": [
            {
                "status": "verified",
                "source_ids": ["audit-2025"],
            }
        ],
        "metrics": [
            {
                "metric": "gross_margin",
                "formula": "gross_profit/revenue",
                "inputs": ["gross_profit", "revenue"],
                "unit": "%",
                "result": 0.3,
                "status": "computed",
                "source_ids": ["audit-2025"],
            }
        ],
        "conflicts": [],
        "quality": {"status": "verified"},
    }
    assert validator.validate(valid) == []
    invalid = json.loads(json.dumps(valid))
    invalid["metrics"][0].pop("source_ids")
    assert "metrics[0]计算结果缺少来源" in validator.validate(invalid)


def test_retrieval_gold_standard_has_three_cases_per_alias() -> None:
    builder = load_python_module(
        "skills/project-matching/scripts/build_retrieval_gold_standard.py"
    )
    cases = builder.build_cases()
    grouped: dict[tuple[str, str], set[str]] = {}
    for case in cases:
        rule_id = case["id"].split(":", 1)[0]
        grouped.setdefault((rule_id, case["alias"]), set()).add(case["kind"])
    assert grouped
    assert all(
        kinds == {"positive", "cross-project", "stale"}
        for kinds in grouped.values()
    )


def test_standard_draft_audit() -> None:
    auditor = load_python_module(
        "skills/standard-drafting/scripts/audit_standard_draft.py"
    )
    valid = """# 1 范围
本文件规定了产品要求。

# 2 规范性引用文件
GB/T 1.1

# 3 技术要求
产品应符合设计要求。

# 4 试验方法
按规定方法进行验证。
"""
    assert auditor.audit(valid)["findings"] == []
    invalid = """# 1 范围
产品必须符合要求。

# 3 技术要求
产品应满足要求。
"""
    codes = {item["code"] for item in auditor.audit(invalid)["findings"]}
    assert {"missing-section", "must-wording", "missing-verification"} <= codes

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "green-development-projects"
VALIDATOR = SKILL / "scripts" / "validate_green_factory_ledger.py"


def base_ledger() -> dict:
    return {
        "policy": {
            "region": "示例地区",
            "level": "provincial",
            "target_year": 2026,
            "guide_title": "已核验评价导则",
            "guide_version": "current-test",
            "verified_on": "2026-09-02",
            "status": "current",
            "evaluation_mode": "current_application",
            "ledger_scope": "partial",
            "core_max_score": 100,
            "bonus_max_score": 10,
            "recommendation_threshold": 90,
        },
        "factory": {
            "organization_boundary": "测试法人边界",
            "production_boundary": "测试生产边界",
            "reporting_period": "2025",
            "allowed_denominator_units": ["万片", "万元工业增加值"],
        },
        "evidence": [
            {
                "id": "E-BASIC",
                "attachment_ref": "5.1.1",
                "title": "主体材料",
                "status": "verified",
                "supports": ["B1"],
            },
            {
                "id": "E-CORE",
                "attachment_ref": "5.2.1",
                "title": "基础设施材料",
                "status": "verified",
                "supports": ["C1"],
            },
            {
                "id": "E-BONUS",
                "attachment_ref": "5.8.1",
                "title": "亩均评价结果",
                "status": "verified",
                "supports": ["A1"],
            },
        ],
        "basic_requirements": [
            {"id": "B1", "status": "pass", "evidence_ids": ["E-BASIC"]}
        ],
        "score_rows": [
            {
                "id": "C1",
                "section": "core",
                "category": "基础设施",
                "requirement_type": "mandatory",
                "status": "pass",
                "max_raw_score": 8,
                "claimed_raw_score": 8,
                "weight": 0.2,
                "claimed_weighted_score": 1.6,
                "allowed_raw_scores": [0, 8],
                "evidence_ids": ["E-CORE"],
                "metric_ids": [],
            },
            {
                "id": "A1",
                "section": "bonus",
                "category": "综合绩效",
                "requirement_type": "optional",
                "status": "pass",
                "max_raw_score": 12,
                "claimed_raw_score": 6,
                "weight": 0.2,
                "claimed_weighted_score": 1.2,
                "allowed_raw_scores": [0, 6, 12],
                "evidence_ids": ["E-BONUS"],
                "metric_ids": [],
            },
        ],
        "metrics": [],
        "summary": {
            "basic_requirements_met": True,
            "core_score": 1.6,
            "bonus_score": 1.2,
            "total_score": 2.8,
            "recommendation": "conditional",
        },
    }


def run_validator(payload: dict, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "green-factory-ledger.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_green_factory_ledger_accepts_traceable_partial_review(tmp_path):
    result = run_validator(base_ledger(), tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["totals"]["total_score"] == 2.8
    assert payload["warnings"] == ["当前为部分台账，未校验评分表理论满分覆盖"]


def test_green_factory_reference_example_is_validator_compatible(tmp_path):
    reference = (SKILL / "references" / "green-factory-self-evaluation.md").read_text(
        encoding="utf-8"
    )
    match = re.search(r"```json\n(.*?)\n```", reference, re.S)
    assert match is not None
    result = run_validator(json.loads(match.group(1)), tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_green_factory_ledger_rejects_positive_score_without_verified_evidence(tmp_path):
    payload = base_ledger()
    payload["evidence"][2]["status"] = "unverified"
    result = run_validator(payload, tmp_path)
    assert result.returncode != 0
    assert "取得正向得分但证据未核验:E-BONUS" in result.stdout


def test_green_factory_ledger_rejects_score_outside_current_rule_steps(tmp_path):
    payload = base_ledger()
    payload["score_rows"][1]["claimed_raw_score"] = 5
    payload["score_rows"][1]["claimed_weighted_score"] = 1
    payload["summary"]["bonus_score"] = 1
    payload["summary"]["total_score"] = 2.6
    result = run_validator(payload, tmp_path)
    assert result.returncode != 0
    assert "原始分不属于当期规则允许集合" in result.stdout


def test_green_factory_ledger_rejects_product_unit_drift(tmp_path):
    payload = base_ledger()
    payload["evidence"].append(
        {
            "id": "E-METRIC",
            "attachment_ref": "5.7.1",
            "title": "碳排放和产量底稿",
            "status": "verified",
            "supports": ["M1"],
        }
    )
    payload["metrics"].append(
        {
            "id": "M1",
            "metric": "单位产品碳排放",
            "boundary": "测试生产边界",
            "period": "2025",
            "unit": "tCO2/万套",
            "denominator_unit": "万套",
            "source_ids": ["E-METRIC"],
            "supports": [],
            "value": 4.9798,
            "calculation": {
                "kind": "ratio",
                "numerator": 2080.31,
                "denominator": 417.75,
                "multiplier": 1,
            },
        }
    )
    result = run_validator(payload, tmp_path)
    assert result.returncode != 0
    assert "分母单位未在工厂边界卡锁定:万套" in result.stdout


def test_green_factory_ledger_recomputes_ratio_metrics(tmp_path):
    payload = base_ledger()
    payload["evidence"].append(
        {
            "id": "E-METRIC",
            "attachment_ref": "5.7.1",
            "title": "碳排放和产量底稿",
            "status": "verified",
            "supports": ["M1"],
        }
    )
    payload["metrics"].append(
        {
            "id": "M1",
            "metric": "单位产品碳排放",
            "boundary": "测试生产边界",
            "period": "2025",
            "unit": "tCO2/万片",
            "denominator_unit": "万片",
            "source_ids": ["E-METRIC"],
            "supports": [],
            "value": 999,
            "calculation": {
                "kind": "ratio",
                "numerator": 2080.31,
                "denominator": 417.75,
                "multiplier": 1,
            },
        }
    )
    result = run_validator(payload, tmp_path)
    assert result.returncode != 0
    assert "结果与比值公式不一致" in result.stdout


def test_green_factory_ledger_blocks_recommendation_when_basic_gate_unknown(tmp_path):
    payload = base_ledger()
    payload["basic_requirements"][0]["status"] = "unknown"
    payload["summary"]["basic_requirements_met"] = False
    payload["summary"]["recommendation"] = "recommendable"
    payload["policy"]["recommendation_threshold"] = 2
    result = run_validator(payload, tmp_path)
    assert result.returncode != 0
    assert "基本要求未全部通过时不得形成推荐结论" in result.stdout


def test_green_factory_skill_has_version_score_and_attachment_gates():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL / "references" / "green-factory-self-evaluation.md").read_text(
        encoding="utf-8"
    )
    metrics_reference = (SKILL / "references" / "green-metrics-boundaries.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "国家绿色工厂、省级绿色低碳工厂、市级或区县绿色工厂、零碳或近零碳工厂不是同一项目",
        "确认得分只使用已核验证据",
        "scripts/validate_green_factory_ledger.py",
    ):
        assert phrase in skill_text
    for phrase in (
        "政策版本未知或评分证据未闭合时，不得写“可以推荐”",
        "附件编号在内容定稿后生成，不从其他企业报告复制",
        "确认分",
        "条件分",
    ):
        assert phrase in reference
    assert "行业协会咨询" in metrics_reference


def test_green_factory_skill_contains_no_customer_sample_identifiers():
    texts = [
        path.read_text(encoding="utf-8")
        for path in (
            SKILL / "SKILL.md",
            SKILL / "references" / "green-metrics-boundaries.md",
            SKILL / "references" / "green-factory-self-evaluation.md",
            ROOT / "tests" / "test_green_factory_skill.py",
        )
    ]
    combined = "\n".join(texts)
    assert re.search(r"杭州[\u4e00-\u9fff]{2,20}有限公司", combined) is None
    assert re.search(r"1[3-9]\d{9}", combined) is None

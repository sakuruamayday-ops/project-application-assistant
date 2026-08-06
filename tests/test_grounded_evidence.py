import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "evidence-ledger" / "scripts" / "grounded_evidence.py"
EXAMPLES = ROOT / "skills" / "evidence-ledger" / "examples"
SPEC = importlib.util.spec_from_file_location("grounded_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_basic_legacy_ledger_remains_compatible():
    payload = {
        "records": [
            {
                "id": "F1",
                "subject": "企业",
                "claim": "企业成立于2020年",
                "type": "fact",
                "source": "企业资料",
                "retrieved_at": "2026-08-05",
                "location": "基本信息",
                "status": "verified",
            }
        ]
    }
    basic = MODULE.validate_payload(payload)
    strict = MODULE.validate_payload(payload, strict_grounded=True)
    assert basic["status"] == "pass"
    assert strict["status"] == "fail"
    assert any("sources来源登记表" in item for item in strict["errors"])


def test_basic_chinese_excerpt_does_not_depend_on_space_word_count():
    payload = load_example("normal-grounded-report.json")
    payload["records"][0]["evidence_excerpt"] = "申报单位须提交市场说明。"
    result = MODULE.validate_payload(payload, strict_grounded=True)
    assert result["status"] == "pass"


def test_basic_chat_supports_inline_and_preceding_sources():
    payload = load_example("normal-grounded-report.json")
    inline = MODULE.render_document(payload, mode="chat", source_position="inline")
    preceding = MODULE.render_document(payload, mode="chat", source_position="before")
    assert "[现行项目申报通知](https://example.gov.cn/policy/current)" in inline
    assert "《企业产品销售底稿.xlsx》" in inline
    assert preceding.startswith("### 数据来源范围")
    assert preceding.index("https://example.gov.cn/policy/current") < preceding.index("### 结论")


def test_boundary_report_lists_full_web_source_at_end_and_only_kb_filename():
    payload = load_example("normal-grounded-report.json")
    rendered = MODULE.render_document(payload, mode="report", source_position="end")
    body, sources = rendered.split("## 数据来源", 1)
    assert "https://" not in body
    assert "[1][2]" in body
    assert "示例主管部门" in sources
    assert "https://example.gov.cn/policy/current" in sources
    assert "企业产品销售底稿.xlsx" in sources
    assert "client-dossier" not in rendered
    assert "excerpt_hash" not in rendered


def test_reference_only_sources_never_render_as_retrieved_or_user_files():
    payload = load_example("reference-only-market-share.json")
    result = MODULE.validate_payload(
        payload,
        strict_grounded=True,
        allow_restricted_market_share=True,
    )
    rendered = MODULE.render_document(payload, mode="report", source_position="end")
    assert result["status"] == "pass"
    assert "工作簿登记链接" in rendered
    assert "未访问，原文未取得" in rendered
    assert "检索日期 2026-08-06" not in rendered
    assert "工作簿登记企业陈述" in rendered


def test_reference_only_source_cannot_support_verified_fact():
    payload = load_example("normal-grounded-report.json")
    payload["sources"][0].update(
        {
            "access_status": "reference_only",
            "registered_at": "2026-08-06",
            "registered_via": "S2",
        }
    )
    payload["sources"][0].pop("retrieved_at", None)
    result = MODULE.validate_payload(payload, strict_grounded=True)
    assert result["status"] == "fail"
    assert any("已核验记录不得直接依赖仅登记" in item for item in result["errors"])


def test_market_share_enterprise_statement_can_be_a_without_becoming_external_proof():
    payload = load_example("market-share-enterprise-statement.json")
    result = MODULE.evaluate_market_share(payload)
    assert result["status"] == "pass"
    assert result["grade"] == "A"
    assert result["verified_value_percent"] == "10"
    assert result["source_lineage"]["coefficient:F-APP"] == ["S3"]
    rendered = MODULE.render_document(payload, mode="report", source_position="end")
    assert "企业陈述：主导产品应用场景拆分说明" in rendered


def test_refuse_market_share_with_boundary_mismatch_and_missing_coefficient_source():
    payload = load_example("refuse-unsupported-market-share.json")
    result = MODULE.evaluate_market_share(payload)
    strict = MODULE.validate_payload(payload, strict_grounded=True, require_market_share=True)
    assert result["status"] == "fail"
    assert result["grade"] == "D"
    assert result["rank_usable"] is False
    assert strict["status"] == "fail"
    assert "不得对外使用精确占有率或排名" in result["use_restriction"]


def test_d_grade_value_is_reproduced_not_verified_and_requires_explicit_disclosure():
    payload = load_example("market-share-enterprise-statement.json")
    for record in payload["records"]:
        record["status"] = "unverified"
    payload["document"]["blocks"][0]["text"] = (
        "按工作簿登记值可复现10%，证据等级为D级；该精确占有率不得对外使用，"
        "排名未核验且不作排名结论。"
    )
    market = MODULE.evaluate_market_share(payload)
    strict = MODULE.validate_payload(payload, strict_grounded=True)
    restricted = MODULE.validate_payload(
        payload,
        strict_grounded=True,
        allow_restricted_market_share=True,
    )
    assert market["grade"] == "D"
    assert market["calculated_value_percent"] == "10"
    assert market["verified_value_percent"] is None
    assert market["reproduced_value_percent"] == "10"
    assert strict["status"] == "fail"
    assert restricted["status"] == "pass"


def test_restricted_d_grade_report_still_fails_without_ranking_boundary():
    payload = load_example("market-share-enterprise-statement.json")
    for record in payload["records"]:
        record["status"] = "unverified"
    payload["document"]["blocks"][0]["text"] = "证据等级为D级，该精确占有率不得对外使用。"
    result = MODULE.validate_payload(
        payload,
        strict_grounded=True,
        allow_restricted_market_share=True,
    )
    assert result["status"] == "fail"
    assert any("排名边界" in item for item in result["errors"])


def test_refuse_to_render_unsupported_rank_even_when_it_appears_in_body():
    payload = load_example("market-share-enterprise-statement.json")
    payload["market_share"]["rank_claim"] = {"text": "国内前三", "source_records": []}
    payload["document"]["blocks"][0]["text"] += "，并位居国内前三。"
    result = MODULE.validate_payload(payload, strict_grounded=True, require_market_share=True)
    assert result["status"] == "fail"
    assert any("无独立已核验来源的排名" in item for item in result["errors"])


def test_refuse_knowledge_base_file_name_that_contains_an_internal_path():
    payload = load_example("normal-grounded-report.json")
    payload["sources"][1]["file_name"] = "internal/client-dossier/企业产品销售底稿.xlsx"
    result = MODULE.validate_payload(payload, strict_grounded=True)
    assert result["status"] == "fail"
    assert any("file_name只能是文件名" in item for item in result["errors"])


def test_complex_calculation_and_inference_recursively_collect_each_source_once():
    payload = load_example("normal-grounded-report.json")
    payload["records"].append(
        {
            "id": "C1",
            "subject": "材料覆盖",
            "claim": "两类关键资料均已取得",
            "type": "calculation",
            "source": [],
            "retrieved_at": "2026-08-05",
            "location": "derived",
            "status": "verified",
            "formula": "count(F1,F2)",
            "inputs": ["F1", "F2"],
        }
    )
    payload["records"].append(
        {
            "id": "I2",
            "subject": "写作门槛",
            "claim": "资料覆盖允许进入草稿阶段",
            "type": "inference",
            "source": [],
            "retrieved_at": "2026-08-05",
            "location": "derived",
            "status": "verified",
            "supports": ["C1", "F1"],
            "limits": "不代表市场数据已经闭合",
        }
    )
    payload["document"]["blocks"] = [
        {"text": "资料覆盖允许进入草稿阶段。", "claim_ids": ["I2"]}
    ]
    assert MODULE.resolve_source_lineage("I2", MODULE._record_map(payload)) == ["S1", "S2"]
    result = MODULE.validate_payload(payload, strict_grounded=True)
    rendered = MODULE.render_document(payload, mode="report", source_position="end")
    assert result["status"] == "pass"
    assert rendered.count("https://example.gov.cn/policy/current") == 1
    assert rendered.count("企业产品销售底稿.xlsx") == 1

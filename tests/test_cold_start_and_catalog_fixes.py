from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "_core"))
sys.path.insert(0, str(ROOT / "skills" / "gov-project-checkup" / "scripts"))

import quality_gate  # noqa: E402
import search_catalogs  # noqa: E402


def test_catalog_search_downweights_generic_suffix_and_flags_low_confidence() -> None:
    refs = ROOT / "skills" / "gov-project-checkup" / "references"
    res = search_catalogs.search_catalogs("金属表面无酸除鳞成套装备", refs, limit=5)

    # Generic suffix "成套装备" must NOT push unrelated "竹质建材" or "泡罩包装" into top results
    top_found_items = [x["item"] for x in res["industry_foundation"][:3]]
    assert not any("竹质建材" in item for item in top_found_items)
    assert not any("泡罩包装" in item for item in top_found_items)

    # Low-confidence guardrail must explicitly warn instead of silently pretending a high match
    found_summary = res["search_summary"]["industry_foundation"]
    assert found_summary["match_confidence"] in {"low", "medium"}
    if found_summary["match_confidence"] == "low":
        assert "warning" in found_summary

    # Specific real leaf query must still achieve high confidence
    res_hi = search_catalogs.search_catalogs("高性能内窥镜光学元件", refs, limit=5)
    assert res_hi["search_summary"]["industry_foundation"]["match_confidence"] == "high"
    assert "内窥镜" in res_hi["industry_foundation"][0]["item"]


def test_quality_gate_allows_related_listed_affiliate_but_blocks_real_contamination() -> None:
    # Legitimate related-party disclosure must NOT be flagged as cross-enterprise contamination
    ok_text = (
        "示例装备科技有限公司成立于2014年，专注绿色金属表面无酸除鳞成套装备研发。"
        "公司与A股上市公司示例实业股份有限公司受同一实际控制人控制，独立核算并规范披露关联交易。"
    )
    res_ok = quality_gate.audit_formal_text(ok_text, expected_company="示例装备科技有限公司")
    assert res_ok["ok"] is True, res_ok
    assert any("示例实业股份有限公司" in x for x in res_ok.get("external_entity_mentions", []))

    # Unattributed foreign declarant must STILL be hard-blocked
    bad_text = (
        "申报单位：串户科技股份有限公司。公司专注塑料包装研发制造。"
    )
    res_bad = quality_gate.audit_formal_text(bad_text, expected_company="示例装备科技有限公司")
    assert res_bad["ok"] is False
    assert any(e["rule"] == "cross_enterprise_contamination" for e in res_bad["errors"])

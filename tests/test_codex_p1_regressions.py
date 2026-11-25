"""Adversarial regression suite reproducing every Codex jt-audit P1 finding and verifying permanent fixes."""
from __future__ import annotations

import json
import math
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

from docx import Document

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"
sys.path.insert(0, str(SKILLS / "_core"))

import doc_io  # noqa: E402
import fact_ledger  # noqa: E402
import kb_local  # noqa: E402
import quality_gate  # noqa: E402


def test_codex_p1_region_collision_nanchang_xihu():
    r = kb_local.resolve_region_scope("江西省南昌市西湖区")
    assert r["province"] == "江西省"
    assert r["city"] == "南昌市"
    assert r["district"] == "西湖区"
    assert "浙江省" not in r["scopes"] and "杭州市" not in r["scopes"]


def test_codex_p1_blackboard_deep_schema_and_nested_secret(tmp_path: Path):
    bb = fact_ledger.empty_blackboard("测试有限公司", "")
    bb["lockedProduct"] = ["invalid_list_not_dict"]
    errs = fact_ledger.validate_blackboard(bb)
    assert any("lockedProduct" in e for e in errs)

    bb2 = fact_ledger.empty_blackboard("测试有限公司", "")
    bb2["financialFacts"]["nested"] = {"password": "my_secret_value"}
    errs2 = fact_ledger.validate_blackboard(bb2)
    assert any("敏感凭据" in e for e in errs2)


def test_codex_p1_patent_15y_design_and_no_empty_number():
    # Post-2021-06-01 design patent has 15-year statutory term (valid in 2033, expired after 2036-07-01)
    assert fact_ledger.validate_patent_item(
        {"patent_no": "ZL202130123456.7", "type": "外观设计", "filing_date": "2021-07-01"},
        as_of=date(2033, 1, 1),
    ) == []
    # Empty patent number MUST be rejected
    errs_empty = fact_ledger.validate_patent_item({"patent_no": "", "type": "发明专利"})
    assert errs_empty


def test_codex_p1_rewrite_sign_and_calc_nonfinite():
    # -5万元 -> 5万元 sign flip MUST be blocked
    r = quality_gate.audit_rewrite_fidelity("净利润为-5万元，研发投入10万元。", "净利润为5万元，研发投入10万元。")
    assert r["ok"] is False

    # Infinity / NaN claimed value MUST be blocked
    c_inf = quality_gate.verify_calculation_claim("10 + 5", float("inf"))
    assert c_inf["ok"] is False


def test_codex_p1_docx_diff_detects_in_place_table_number_change(tmp_path: Path):
    def _mk(p: Path, amt: str):
        d = Document()
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "项目", "金额"
        t.cell(1, 0).text, t.cell(1, 1).text = "设备采购", amt
        d.save(p)

    d1, d2 = tmp_path / "t1.docx", tmp_path / "t2.docx"
    _mk(d1, "120万元")
    _mk(d2, "210万元")
    diff = doc_io.diff_docx_versions(d1, d2)
    assert diff["summary"]["modified_table_rows"] >= 1
    assert diff["summary"]["numeric_changes"] >= 1


def test_codex_p1_empty_checkup_and_2026_sme_rules(tmp_path: Path):
    cli = SKILLS / "gov-project-checkup/scripts/run_checkup.py"
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    p_ht = subprocess.run([sys.executable, str(cli), "hightech", "--input", str(empty), "--strict"], capture_output=True, text=True)
    assert p_ht.returncode == 2

    # 2026 SME: 73% debt ratio passes (<=75%), but duplicate or <4 I-class patents fails!
    sme_dup = tmp_path / "sme_dup.json"
    sme_dup.write_text(json.dumps({
        "target_tier": "little_giant",
        "balance_sheet": {"total_assets": 10000, "total_liabilities": 7300, "total_equity": 2700},
        "latest_revenue": 15000,
        "latest_rd_expense": 600,
        "rd_expenses_2y": [500, 600],  # 1100 < 1200!
        "patents": [
            {"patent_no": "ZL202310123456.1", "type": "发明专利", "filing_date": "2023-01-01"},
            {"patent_no": "ZL202310123456.1", "type": "发明专利", "filing_date": "2023-01-01"},
        ],
    }), encoding="utf-8")
    p_sme = subprocess.run([sys.executable, str(cli), "sme", "--input", str(sme_dup), "--strict"], capture_output=True, text=True)
    assert p_sme.returncode == 2
    out = json.loads(p_sme.stdout)
    assert out["gates"]["debt_to_asset_ratio"]["pass"] is True  # 73% <= 75%!
    assert out["gates"]["rd_2y_total"]["pass"] is False  # 1100 < 1200!


def test_codex_p1_zero_table_hightech_docx_blocked(tmp_path: Path):
    cli = SKILLS / "hightech-application-writer/scripts/audit_application_docx.py"
    doc = Document()
    doc.add_paragraph("只有一行普通正文，没有任何表格。")
    p_doc = tmp_path / "empty_tables.docx"
    doc.save(p_doc)
    p = subprocess.run([sys.executable, str(cli), str(p_doc), "--strict"], capture_output=True, text=True)
    assert p.returncode == 2


def test_codex_p1_sme_assessment_hard_gate_and_score_linkage(tmp_path: Path):
    cli = SKILLS / "sme-giant-writer/scripts/validate_sme_assessment.py"
    bad = tmp_path / "bad_sme.json"
    bad.write_text(json.dumps({
        "application_context": {
            "project_level": "小巨人", "region": "浙江省", "year": 2026,
            "application_type": "新申报", "form_version": "2026版",
            "version_status": "confirmed", "policy_status": "current",
        },
        "overall_conclusion": "eligible",
        "four_judgments": {
            k: {"decision": "retain", "evidence_state": "verified", "object": "产品", "reason": "充分", "actions": ["继续"]}
            for k in ("leading_product", "bottleneck", "gap_filling", "import_substitution")
        },
        "hard_gates": {"debt_ratio": "fail"},
        "evaluation": {"quality_score": {"status": "verified-platform-score", "value": 0, "source": "平台"}},
        "evidence_gaps": [], "risks": [], "actions": [],
    }), encoding="utf-8")
    p = subprocess.run([sys.executable, str(cli), str(bad), "--strict"], capture_output=True, text=True)
    assert p.returncode == 2


def test_codex_p1_grant_empty_dup_and_169_tier(tmp_path: Path):
    cli = SKILLS / "general-grant-writer/scripts/validate_grant_deliverable.py"
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    for track in ("institute", "agriculture", "talent", "feasibility"):
        assert subprocess.run([sys.executable, str(cli), "--track", track, "--input", str(empty)], capture_output=True).returncode == 2

    # 169号文: <5000万 requires >=5% & >=100万
    inst_low = tmp_path / "inst_low.json"
    inst_low.write_text(json.dumps({
        "tier": "provincial_institute", "latest_revenue": 3000, "latest_rd_expense": 100,
        "rd_staff_count": 35, "rd_equipment_original_value": 600, "rd_venue_area_m2": 600,
    }), encoding="utf-8")
    assert subprocess.run([sys.executable, str(cli), "--track", "institute", "--input", str(inst_low)], capture_output=True).returncode == 2

    # Subsidy duplicate row & invalid date blocked
    sub_dup = tmp_path / "sub_dup.json"
    sub_dup.write_text(json.dumps({"investments": [
        {"asset_name": "机A", "contract_amount": 100, "invoice_amount": 100, "paid_amount": 100, "invoice_no": "INV1", "asset_card_no": "C1", "invoice_date": "bad-date"},
        {"asset_name": "机A重复", "contract_amount": 100, "invoice_amount": 100, "paid_amount": 100, "invoice_no": "INV1", "asset_card_no": "C1", "invoice_date": "2025-05-01"},
    ]}), encoding="utf-8")
    assert subprocess.run([sys.executable, str(cli), "--track", "subsidy", "--input", str(sub_dup)], capture_output=True).returncode == 2

    # Green non-numeric value blocked
    g_str = tmp_path / "g_str.json"
    g_str.write_text(json.dumps({"metrics": [{"name": "能耗", "value": "待补", "unit": "%"}]}), encoding="utf-8")
    assert subprocess.run([sys.executable, str(cli), "--track", "green", "--input", str(g_str)], capture_output=True).returncode == 2


def test_codex_p1_standard_due_diligence_and_company_law(tmp_path: Path):
    # Standard: repeated "无" filler & normative ref only in 参考文献 MUST fail!
    std_cli = SKILLS / "standard-drafting/scripts/audit_standard_draft.py"
    std_f = tmp_path / "trick_std.md"
    std_f.write_text(
        "# 1 范围\n本文件规定测试产品。\n# 2 规范性引用文件\nGB/T 1038 透气性\n# 3 要求\n产品应符合要求。\n"
        "# 4 试验方法\n无无无无无无无无无无无无无无无无无无无无无无无无无无无无无无无无。\n# 参考文献\n[1] GB/T 1038\n",
        encoding="utf-8",
    )
    p_std = subprocess.run([sys.executable, str(std_cli), str(std_f), "--json", "--strict"], capture_output=True, text=True)
    assert p_std.returncode == 2
    codes = {f["code"] for f in json.loads(p_std.stdout)["findings"]}
    assert {"empty-verification-section", "uncited-normative-reference"}.issubset(codes)

    # Due diligence: invalid section key "2" rejected (not silently dropped!)
    dd_cli = SKILLS / "enterprise-due-diligence/scripts/build_standard_html.py"
    dd_in = tmp_path / "bad_sec.json"
    dd_in.write_text(json.dumps({"company": {"name": "测试公司"}, "sections": {"2": {}}}, ensure_ascii=False), encoding="utf-8")
    assert subprocess.run([sys.executable, str(dd_cli), "--input", str(dd_in), "--output", str(tmp_path / "out.html")], capture_output=True).returncode == 2

    # Company law: exact 5-year anniversary (2024-07-31 -> 2029-07-31, NOT 2029-07-28) & jsc 2027-06-30
    law_cli = SKILLS / "enterprise-due-diligence/scripts/check_company_law.py"
    p_ann = subprocess.run([
        sys.executable, str(law_cli), "paid-in",
        "--founded", "2024-07-31", "--subscribed-deadline", "2029-07-31",
        "--registered-wan", "100", "--paid-in-wan", "0", "--strict",
    ], capture_output=True, text=True)
    assert p_ann.returncode == 0
    assert json.loads(p_ann.stdout)["statutory_max_paidin_deadline"] == "2029-07-31"

    p_jsc = subprocess.run([
        sys.executable, str(law_cli), "paid-in",
        "--company-type", "jsc",
        "--founded", "2020-01-01", "--subscribed-deadline", "2030-01-01",
        "--registered-wan", "500", "--paid-in-wan", "100", "--strict",
    ], capture_output=True, text=True)
    assert p_jsc.returncode == 2
    assert json.loads(p_jsc.stdout)["statutory_max_paidin_deadline"] == "2027-06-30"


def test_anti_blocking_workflow_balances(tmp_path: Path):
    # 1. Legitimate client/supplier/peer mentions must NOT falsely block as contamination, while subject-position contamination still blocks!
    ok_ctx = quality_gate.audit_formal_text(
        "本企业为杭州测试科技有限公司，主导产品稳定配套客户浙江先正达包装有限公司，并采购安徽科亿智能科技股份有限公司检测设备，对标同行业领军企业上海紫江企业集团股份有限公司。",
        expected_company="杭州测试科技有限公司",
    )
    assert ok_ctx["ok"] is True, ok_ctx["errors"]
    assert len(ok_ctx.get("external_entity_mentions", [])) == 3

    bad_ctx = quality_gate.audit_formal_text(
        "本项目由宁波误粘串户有限公司组织实施。",
        expected_company="杭州测试科技有限公司",
    )
    assert bad_ctx["ok"] is False

    # 2. Partial checkup (missing balance sheet + pending patent ZL no) works in default mode (exit 0, partial_pass) while --strict still blocks!
    check_cli = SKILLS / "gov-project-checkup/scripts/run_checkup.py"
    partial_ht = tmp_path / "partial_ht.json"
    partial_ht.write_text(json.dumps({
        "founded_date": "2018-01-01",
        "patents": [{"patent_no": "IP01", "type": "发明专利"}],
        "total_employees": 100, "tech_employees": 20,
        "latest_revenue": 4000, "hightech_product_revenue": 3200,
        "revenue_3y": 10000, "rd_expense_3y": 600, "domestic_rd_expense_3y": 600,
    }), encoding="utf-8")
    p_part = subprocess.run([sys.executable, str(check_cli), "hightech", "--input", str(partial_ht)], capture_output=True, text=True)
    assert p_part.returncode == 0
    out_p = json.loads(p_part.stdout)
    assert out_p["status"] == "partial_pass" and out_p["missing_inputs"] and out_p["warnings"]

    p_strict = subprocess.run([sys.executable, str(check_cli), "hightech", "--input", str(partial_ht), "--strict"], capture_output=True, text=True)
    assert p_strict.returncode == 2

    # 3. Grant validator --mode draft reports missing_fields without blocking while strict mode blocks
    grant_cli = SKILLS / "general-grant-writer/scripts/validate_grant_deliverable.py"
    part_inst = tmp_path / "part_inst.json"
    part_inst.write_text(json.dumps({"tier": "provincial_institute", "latest_revenue": 10000, "latest_rd_expense": 550}), encoding="utf-8")
    p_draft = subprocess.run([sys.executable, str(grant_cli), "--track", "institute", "--mode", "draft", "--input", str(part_inst)], capture_output=True, text=True)
    assert p_draft.returncode == 0
    assert json.loads(p_draft.stdout)["missing_fields"]
    p_gstrict = subprocess.run([sys.executable, str(grant_cli), "--track", "institute", "--mode", "strict", "--input", str(part_inst)], capture_output=True, text=True)
    assert p_gstrict.returncode == 2


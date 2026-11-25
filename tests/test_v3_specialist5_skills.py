from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"


# ---------- #6 patent-docx-reviewer ----------


def test_patent_docx_reviewer_scope_impact_and_occurrence(tmp_path: Path):
    sys.path.insert(0, str(SKILLS / "patent-docx-reviewer" / "scripts"))
    import review_adder  # noqa: E402
    from docx import Document

    src = tmp_path / "pat.docx"
    dst = tmp_path / "pat_out.docx"
    d = Document()
    d.add_paragraph("一种加密模块，所述加密模块包含第一加密模块和第二加密模块。")
    d.save(src)

    # Missing 保护范围影响 fails when require_scope_impact=True
    try:
        review_adder.add_comments(
            src, dst,
            [{"highlight_text": "加密模块", "occurrence": 1, "occurrence_in_paragraph": 2, "comment": "测试批注"}],
            require_scope_impact=True,
        )
        assert False, "expected ValueError for missing 保护范围影响"
    except ValueError as exc:
        assert "保护范围影响" in str(exc)

    # Valid with occurrence_in_paragraph=2 & 保护范围影响 succeeds
    res = review_adder.add_comments(
        src, dst,
        [{"highlight_text": "加密模块", "occurrence": 1, "occurrence_in_paragraph": 2, "comment": "限定不清", "保护范围影响": "可能导致保护范围不清楚"}],
        require_scope_impact=True,
    )
    assert res["applied"] == 1 and dst.is_file()


# ---------- #7 patent-strategy-assistant ----------


def test_patent_strategy_fixes_use_unicode_hyphen_and_cross_category():
    sys.path.insert(0, str(SKILLS / "patent-strategy-assistant" / "scripts"))
    import build_ipc_evidence_chain as chain  # noqa: E402

    claims = (
        "1. 一种应用层数据加密方法，其特征在于，包括：建立国密SM2握手通道；对应用报文执行SM4分片加密。\n"
        "2. 根据权利要求1所述的方法，其特征在于，还包括弱网断链重连校验。\n"
        "3. 根据权利要求1或2所述的方法，其特征在于，还包括动态密钥轮换。\n"
        "4. 一种应用层数据加密装置，其特征在于，用于执行权利要求1\u20113任一项所述的方法。\n"
    )
    graph = chain.build_claim_reference_graph(claims)
    by_no = {n["claim_number"]: n for n in graph["nodes"]}
    assert by_no[1]["protection_object"] == "method"  # NOT 'use'!
    assert by_no[4]["referenced_claims"] == [1, 2, 3]  # U+2011 non-breaking hyphen expanded!

    tree = chain.build_independent_claim_feature_tree(claims)
    c4 = next(c for c in tree if c["claim_number"] == 4)
    assert c4["referenced_claims"] == [1, 2, 3]
    assert {f["source_claim"] for f in c4["inherited_features"]} == {1, 2, 3}


# ---------- #8 standard-drafting ----------


def test_standard_drafting_catches_uncited_ref_blank_test_and_placeholder(tmp_path: Path):
    cli = SKILLS / "standard-drafting" / "scripts" / "audit_standard_draft.py"
    bad = tmp_path / "bad_std.md"
    bad.write_text(
        "# 1 范围\n本文件规定了高阻隔膜的技术要求。\n\n"
        "# 2 规范性引用文件\nGB/T 1038 塑料薄膜透气性试验方法\nGB/T 99999 从未引用的幽灵标准\n\n"
        "# 3 技术要求\n产品透氧量应不大于0.5，外观应平整，【合成】待定。\n\n"
        "# 4 试验方法\n略。\n",
        encoding="utf-8",
    )
    p = subprocess.run([sys.executable, str(cli), str(bad), "--json", "--strict"], capture_output=True, text=True)
    assert p.returncode == 2
    rep = json.loads(p.stdout)
    codes = {f["code"] for f in rep["findings"]}
    assert {"uncited-normative-reference", "empty-verification-section", "placeholder"}.issubset(codes)
    assert all("line" in f for f in rep["findings"])


# ---------- #9 enterprise-due-diligence ----------


def test_enterprise_due_diligence_uscc_and_company_law(tmp_path: Path):
    html_cli = SKILLS / "enterprise-due-diligence" / "scripts" / "build_standard_html.py"
    law_cli = SKILLS / "enterprise-due-diligence" / "scripts" / "check_company_law.py"

    bad_in = tmp_path / "bad_ent.json"
    bad_in.write_text(
        json.dumps({"company": {"name": "杭州测试有限公司", "credit_code": "91330108MA27X1234Z"}, "sections": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    p_uscc = subprocess.run([sys.executable, str(html_cli), "--input", str(bad_in), "--output", str(tmp_path / "out.html")], capture_output=True, text=True)
    assert p_uscc.returncode == 2
    assert "校验失败" in p_uscc.stdout

    # Company Law 2027-06-30 transition check (legacy company subscribed until 2045 -> fails --strict)
    p_law = subprocess.run(
        [
            sys.executable, str(law_cli), "paid-in",
            "--founded", "2018-06-01",
            "--subscribed-deadline", "2045-12-31",
            "--registered-wan", "5000",
            "--paid-in-wan", "1000",
            "--strict",
        ],
        capture_output=True, text=True,
    )
    assert p_law.returncode == 2
    law_out = json.loads(p_law.stdout)
    assert law_out["transition_adjust_deadline"] == "2027-06-30"
    assert law_out["needs_adjustment"] is True


# ---------- #10 manufacturing-tax-risk ----------


def test_manufacturing_tax_risk_cross_company_blocker_and_high_rd(tmp_path: Path):
    sys.path.insert(0, str(SKILLS / "manufacturing-tax-risk" / "scripts"))
    import calculate_metrics as cm  # noqa: E402
    import generate_report_html as gen  # noqa: E402

    # R&D ratio > 100% (150%) does NOT crash
    res = cm.calc({
        "revenue": 1000, "cost": 600, "profit_before_tax": -500, "net_profit": -500,
        "assets": 2000, "assets_open": 1800, "liabilities": 800, "equity": 1200, "equity_open": 1100,
        "current_assets": 1000, "current_liabilities": 400, "cash": 300,
        "receivables": 200, "receivables_open": 150, "other_receivables": 10,
        "inventory": 100, "inventory_open": 80, "advances_from_customers": 20, "short_term_loans": 100,
        "operating_cash_flow": -200, "capex_cash": 100, "taxes_paid": 20, "sales_cash": 900,
        "research_expense": 1500, "interest_expense": 10, "income_tax_expense": 0,
    })
    assert res["research_to_revenue"] == 1.5

    # Cross-company contamination MUST raise ValueError (never advisory warning!)
    try:
        gen.validate(
            {"company": "杭州A制造有限公司", "report_date": "2026-11-24", "risk_level": "中", "one_line_conclusion": "测试"},
            {"schema": gen.METRICS_SCHEMA, "company": "宁波B串户有限公司", "report_rows": []},
        )
        assert False, "expected ValueError on cross-company contamination"
    except ValueError as exc:
        assert "跨企业串户硬拦截" in str(exc)

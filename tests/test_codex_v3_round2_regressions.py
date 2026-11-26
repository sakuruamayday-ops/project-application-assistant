"""
Comprehensive Round-2 Codex Regression Suite covering all 19 P1 findings from dbaaf88 re-audit:
  1. V3 Ed25519 signing chain (suite-manifest.json + 10 skill manifests + build_standard_package + tamper/rollback)
  2. All 10 ZIPs have unified scripts/_core/fact_ledger.py
  3. kb_local: name+credit_code conflict guard, no silent credit_code fallback, RAG source permission filter, 金华市义乌市 parsing
  4. fact_ledger: strict read==write schema validation (estimatedMetrics: null, revision type, refresh_token), patent check-digit dedup, concurrent locked updates
  5. quality_gate & review_application: declarant-first subject check, 购自乙方 external context, unbound blackboard pause, Chinese 负 sign, metric swap, non-finite AST literals/intermediates
  6. doc_io: tail added table rows with money, -120 -> 120 signed numeric_changes, row-10 Excel header skipping 行次
  7. run_checkup: pending_certificate -> partial_pass, numerator>denominator strict block, 2026 Little Giant exact unrounded 75%/1200万/3%/no-6%/4-autonomous-IP, policy --strict jurisdiction filter
  8. hightech audit: --require-complete-form standalone strict exit, mandatory RD/PS rows, cross-year check without breakdown table, credit_code blackboard check, fill_rd spec collision guard
  9. sme-giant-writer: empty/null hard_gates block eligible, provincial SME 50-point floor passes 55
 10. general-grant-writer: 169号文 exact unrounded tiers (3000/149.9 fails, 1亿/300万 key fails, 1.5亿/250万 inst passes), draft partial_pass, subsidy window & cross-card invoice cap, feasibility ambiguity block
 11. patent-docx-reviewer: CLI default scope_impact enforcement + rendering into Word XML, skip aborts before overwriting existing target
 12. standard-drafting: excludes 注/示例 and 资料性附录, catches dated year mismatch & filler repetition
 13. enterprise-due-diligence: duplicate JSON section key rejected, check_company_law --strict requires --company-type
 14. manufacturing-tax-risk: credit_code/period/balance-sheet reconciliation blocks formal ok, input path protection, paired output atomic rollback
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import openpyxl
import pytest
from docx import Document

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "skills" / "_core"
SRC_DIR = REPO_ROOT / "src"
for p in (str(CORE_DIR), str(SRC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import doc_io  # noqa: E402
import fact_ledger  # noqa: E402
import kb_local  # noqa: E402
import quality_gate  # noqa: E402
from project_assistant.skill_integrity import (  # noqa: E402
    trusted_publisher_fingerprint,
    verify_skill_directory,
)


def _run(cmd: list[str], cwd: Path = REPO_ROOT, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=90)


# 1. Signing chain, trust anchor, build_standard_package, tamper detection & rollback
@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen unavailable")
def test_v3_signing_chain_and_tamper_rollback(tmp_path: Path):
    skills_root = REPO_ROOT / "skills"
    fp = trusted_publisher_fingerprint(skills_root)
    assert fp.startswith("SHA256:")
    suite = json.loads((skills_root / "suite-manifest.json").read_text(encoding="utf-8"))
    assert len(suite["skills"]) == 10
    ev_dir = tmp_path / "ev"
    for sk in suite["skills"]:
        res = verify_skill_directory(
            skills_root / sk,
            evidence_dir=ev_dir,
            label=f"test-{sk}",
            require_signature=True,
            expected_public_fingerprint=fp,
        )
        assert res["status"] == "pass"

    # Build standard archive into tmp_path and verify it succeeds cleanly
    pkg = tmp_path / "v3-suite.zip"
    proc = _run([sys.executable, str(REPO_ROOT / "scripts" / "build_standard_package.py"), "--output", str(pkg)])
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert pkg.is_file()

    # Simulate upgrade -> tamper -> verify fails -> rollback restores valid verified install
    install_copy = tmp_path / "installed" / "standard-drafting"
    backup_copy = tmp_path / "backup" / "standard-drafting"
    shutil.copytree(skills_root / "standard-drafting", install_copy)
    shutil.copytree(install_copy, backup_copy)
    (install_copy / "SKILL.md").write_text("TAMPERED", encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_skill_directory(install_copy, evidence_dir=ev_dir, label="tampered", require_signature=True, expected_public_fingerprint=fp)
    shutil.rmtree(install_copy)
    shutil.copytree(backup_copy, install_copy)
    restored = verify_skill_directory(install_copy, evidence_dir=ev_dir, label="restored", require_signature=True, expected_public_fingerprint=fp)
    assert restored["status"] == "pass"


# 2. kb_local: county-level city parsing, identity conflict guard, RAG permission filter
def test_kb_local_region_conflict_and_rag_permission(tmp_path: Path, monkeypatch):
    r1 = kb_local.resolve_region_scope("浙江省金华市义乌市")
    assert r1["province"] == "浙江省"
    assert r1["city"] == "金华市"
    assert r1["district"] == "义乌市"
    assert r1["scopes"] == ["国家", "浙江省", "金华市", "义乌市"]

    r2 = kb_local.resolve_region_scope("江西省南昌市西湖区")
    assert (r2["province"], r2["city"], r2["district"]) == ("江西省", "南昌市", "西湖区")

    # Build synthetic local sqlite DB with Company A and Company B
    db = tmp_path / "test.db"
    with sqlite3.connect(db) as con:
        con.executescript("""
            CREATE TABLE enterprise (id INTEGER PRIMARY KEY, name TEXT, unified_social_credit_code TEXT, province TEXT, city TEXT, county TEXT, founded_date TEXT, registered_capital TEXT, industry_l1 TEXT, industry_l2 TEXT, industry_l3 TEXT, company_intro TEXT);
            CREATE TABLE enterprise_financial (enterprise_id INTEGER, fiscal_year INTEGER, metric TEXT, value_text TEXT, unit TEXT, amount_yuan REAL);
            CREATE TABLE recognition (enterprise_id INTEGER, project_name TEXT, recognition_year INTEGER, batch TEXT, result TEXT, product_name TEXT, primary_source_title TEXT, published_date TEXT, evidence_status TEXT);
            CREATE TABLE project (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE application (enterprise_id INTEGER, enterprise_name TEXT, project_id INTEGER, application_year INTEGER, file_path TEXT);
            INSERT INTO enterprise VALUES (1, '甲方科技有限公司', '91330100MA0000011X', '浙江省', '杭州市', '余杭区', '2018-01-01', '1000万', '', '', '', '');
            INSERT INTO enterprise VALUES (2, '乙方新材料有限公司', '91330100MA0000022Y', '浙江省', '杭州市', '滨江区', '2019-01-01', '2000万', '', '', '', '');
            INSERT INTO enterprise_financial VALUES (2, 2025, 'revenue', '8000万', '万元', 80000000);
        """)
    # Name A + Credit Code B -> conflict, zero financials!
    res_conflict = kb_local.query_enterprise("甲方科技有限公司", db_path=db, credit_code="91330100MA0000022Y")
    assert res_conflict["found"] is False and res_conflict.get("subject_conflict") is True
    assert "financials" not in res_conflict

    # Unknown Credit Code + Name A -> NO silent fallback to Name A!
    res_unknown = kb_local.query_enterprise("甲方科技有限公司", db_path=db, credit_code="91330100MA9999999Z")
    assert res_unknown["found"] is False and res_unknown.get("credit_code_not_found") is True

    # RAG restricted source filter BEFORE excerpt return
    fake_rag = tmp_path / "rag.sh"
    fake_rag.write_text(
        "#!/bin/sh\n"
        'cat <<EOF\n'
        '{"results":[{"title":"小巨人政策","source":"internal","access_level":"restricted","excerpt":"正常公开词句不含隐私关键词"},{"title":"2026小巨人公开办法","source":"miit","access_level":"public","excerpt":"小巨人研发费用1200万元"}]}\n'
        'EOF\n',
        encoding="utf-8",
    )
    fake_rag.chmod(0o755)
    monkeypatch.setattr(kb_local, "RAG_QUERY_SH", fake_rag)
    rag_out = kb_local.search_local_rag("小巨人", limit=5)
    assert rag_out["count"] == 1
    assert rag_out["dropped"]["restricted"] == 1
    assert rag_out["results"][0]["title"] == "2026小巨人公开办法"


# 3. fact_ledger: strict read==write deep validation, patent check-digit dedup, concurrent locked updates
def test_fact_ledger_deep_schema_dedup_and_concurrency(tmp_path: Path):
    assert fact_ledger.normalize_patent_key({"patent_no": "ZL202010123456.7"}) == fact_ledger.normalize_patent_key({"patent_no": "CN202010123456"})

    bb = fact_ledger.empty_blackboard("测试并发有限公司", "91330100MA27X1234A")
    bad_null = {**bb, "estimatedMetrics": None}
    assert fact_ledger.validate_blackboard(bad_null)
    bad_rev = {**bb, "lockedProduct": {**bb["lockedProduct"], "revision": "not-int"}}
    assert fact_ledger.validate_blackboard(bad_rev)
    bad_tok = {**bb, "checkupSnapshots": {"nested": {"refresh_token": "tok_abcdef123456"}}}
    assert fact_ledger.validate_blackboard(bad_tok)

    # Strict read rejects corrupted blackboard written on disk
    p = fact_ledger.blackboard_path(tmp_path, "测试并发有限公司", "91330100MA27X1234A")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bad_null, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        fact_ledger.load_blackboard(tmp_path, "测试并发有限公司", "91330100MA27X1234A", strict=True)
    p.unlink()

    # Concurrent locked updates must NOT clobber each other
    def _w1():
        def _m(doc):
            time.sleep(0.05)
            doc["financialFacts"]["rev_2025"] = 12000
        fact_ledger.update_blackboard(tmp_path, "测试并发有限公司", "", _m, strict=True)

    def _w2():
        def _m(doc):
            time.sleep(0.05)
            doc["checkupSnapshots"]["sme"] = "pass"
        fact_ledger.update_blackboard(tmp_path, "测试并发有限公司", "", _m, strict=True)

    t1, t2 = threading.Thread(target=_w1), threading.Thread(target=_w2)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    loaded, _ = fact_ledger.load_blackboard(tmp_path, "测试并发有限公司", "", strict=True)
    assert loaded is not None
    assert loaded["financialFacts"]["rev_2025"] == 12000
    assert loaded["checkupSnapshots"]["sme"] == "pass"


# 4. quality_gate & review_application: declarant-first, 购自乙方, unbound blackboard, 负5万元, swap, inf
def test_quality_gate_subject_rewrite_and_calc(tmp_path: Path):
    # Declarant is B while sentence mentions client A -> MUST BLOCK
    bad_decl = quality_gate.audit_formal_text("申报单位：乙方科技有限公司，核心客户为甲方科技有限公司。", expected_company="甲方科技有限公司")
    assert not bad_decl["ok"]

    # Legitimate supplier "设备购自乙方科技有限公司" -> MUST PASS and record external mention
    ok_sup = quality_gate.audit_formal_text("申报单位：甲方科技有限公司，关键涂布设备购自乙方科技有限公司。", expected_company="甲方科技有限公司")
    assert ok_sup["ok"]
    assert "乙方科技有限公司" in ok_sup.get("external_entity_mentions", [])

    # Chinese negative sign & metric swap MUST BLOCK
    assert not quality_gate.audit_rewrite_fidelity("2025年净利润为负5万元。", "2025年净利润为5万元。")["ok"]
    assert not quality_gate.audit_rewrite_fidelity("研发费100万元，设备费200万元。", "研发费200万元，设备费100万元。")["ok"]

    # Non-finite literal/intermediate in formula MUST BLOCK
    assert not quality_gate.verify_calculation_claim("1e309 - 1e309", 0.0)["ok"]
    assert not quality_gate.verify_calculation_claim("1 / 1e309", 0.0)["ok"]

    # review_application: omitting --company with unbound text MUST pause/block blackboard reconciliation
    txt = tmp_path / "no_subject.txt"
    txt.write_text("项目技术指标达到0.5g/m2·24h，满足食品级阻隔包装要求。", encoding="utf-8")
    bb_file = tmp_path / "bb.json"
    bb_file.write_text(json.dumps(fact_ledger.empty_blackboard("甲方科技有限公司")), encoding="utf-8")
    proc = _run([
        sys.executable,
        str(REPO_ROOT / "skills/application-reviewer/scripts/review_application.py"),
        "check-consistency", str(txt), "--blackboard", str(bb_file),
    ])
    assert proc.returncode == 2
    assert any(e["rule"] == "blackboard_subject_unbound" for e in json.loads(proc.stdout)["errors"])


# 5. doc_io: tail added table row + signed -120 -> 120 + row-10 Excel header
def test_doc_io_table_diff_and_row10_excel(tmp_path: Path):
    d1, d2 = tmp_path / "v1.docx", tmp_path / "v2.docx"
    doc1 = Document()
    t1 = doc1.add_table(rows=2, cols=2)
    t1.cell(0, 0).text, t1.cell(0, 1).text = "项目", "金额"
    t1.cell(1, 0).text, t1.cell(1, 1).text = "净利润", "-120万元"
    doc1.save(d1)

    doc2 = Document()
    t2 = doc2.add_table(rows=3, cols=2)
    t2.cell(0, 0).text, t2.cell(0, 1).text = "项目", "金额"
    t2.cell(1, 0).text, t2.cell(1, 1).text = "净利润", "120万元"
    t2.cell(2, 0).text, t2.cell(2, 1).text = "工程款", "80万元"
    doc2.save(d2)

    diff = doc_io.diff_docx_versions(d1, d2)
    assert diff["summary"]["added_table_rows"] == 1
    assert diff["summary"]["modified_table_rows"] == 1
    assert diff["summary"]["numeric_changes"] >= 2

    # Excel with header on row 10 and 行次 column
    xlsx = tmp_path / "fin.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(9):
        ws.append(["", "", ""])
    ws.append(["项目", "行次", "2025年金额"])
    ws.append(["营业收入", 1, 120])
    wb.save(xlsx)
    extracted = doc_io.read_financial_excel_tolerant(xlsx)
    assert [it["value"] for it in extracted["items"]] == [120.0]


# 6. run_checkup: pending_cert partial_pass, numerator>denominator, 2026 SME exact tiers, policy jurisdiction strict
def test_checkup_hightech_sme_and_policy_strict(tmp_path: Path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "skills/gov-project-checkup/scripts"))
    import run_checkup  # noqa: E402

    # Pending patent certificate only -> partial_pass (not pass!)
    ht_pending = {
        "founded_date": "2020-01-01",
        "balance_sheet": {"total_assets": 1000, "total_liabilities": 400, "total_equity": 600},
        "patents": [{"type": "发明", "patent_no": ""}],
        "total_employees": 100, "tech_employees": 20,
        "latest_revenue": 6000, "hightech_product_revenue": 4500,
        "revenue_3y": 15000, "rd_expense_3y": 900, "domestic_rd_expense_3y": 900,
    }
    res_p = run_checkup.check_hightech(ht_pending, strict=False)
    assert res_p["status"] == "partial_pass"
    assert run_checkup.check_hightech(ht_pending, strict=True)["status"] == "fail"

    # Numerator > denominator MUST FAIL even if ratio >= threshold
    ht_impossible = {
        **ht_pending,
        "patents": [{"type": "发明", "patent_no": "ZL202110123456.7"}],
        "tech_employees": 120,
        "hightech_product_revenue": 7000,
        "domestic_rd_expense_3y": 1000,
    }
    res_imp = run_checkup.check_hightech(ht_impossible, strict=True)
    assert res_imp["status"] == "fail" and len(res_imp["errors"]) >= 3

    # 2026 Little Giant exact rules:
    # (a) 75.004% fails raw precision
    # (b) 9000万 revenue + 2y R&D [350, 350]=700万 fails (<1200万)
    # (c) 9000万 revenue + 2y R&D [600, 600]=1200万 (>3%/yr, NO bogus 6% requirement!) + 4 valid own IP -> PASSES!
    # (d) Caller passing min_i_class_ip=1 cannot bypass 4-IP rule; transferred IP rejected
    own_4_ips = [{"type": "发明", "patent_no": f"ZL20211012345{i}.7"} for i in range(4)]
    lg_pass = {
        "target_tier": "little_giant",
        "balance_sheet": {"total_assets": 10000, "total_liabilities": 7000, "total_equity": 3000},
        "latest_revenue": 9000,
        "annual_revenues": [7000, 8000, 9000],
        "rd_expenses_2y": [600, 600],
        "patents": own_4_ips,
    }
    assert run_checkup.check_sme(lg_pass, strict=True)["status"] == "pass"

    lg_dar_fail = {**lg_pass, "balance_sheet": {"total_assets": 100000, "total_liabilities": 75004, "total_equity": 24996}}
    assert run_checkup.check_sme(lg_dar_fail, strict=True)["status"] == "fail"

    lg_rd_fail = {**lg_pass, "rd_expenses_2y": [350, 350]}
    assert run_checkup.check_sme(lg_rd_fail, strict=True)["status"] == "fail"

    lg_bypass_fail = {**lg_pass, "min_i_class_ip": 1, "patents": own_4_ips[:1]}
    assert run_checkup.check_sme(lg_bypass_fail, strict=True)["status"] == "fail"

    lg_transfer_fail = {**lg_pass, "patents": [{**p, "acquisition": "受让", "transfer_date": "2022-01-01"} for p in own_4_ips]}
    assert run_checkup.check_sme(lg_transfer_fail, strict=True)["status"] == "fail"

    # Policy --strict rejects cross-region Jiangxi hits when Zhejiang Hangzhou requested
    fake_rag = tmp_path / "rag_jx.sh"
    fake_rag.write_text(
        '#!/bin/sh\necho \'{"results":[{"title":"江西省南昌市高企补贴政策","region":"江西省南昌市","validity_status":"valid","excerpt":"高企补贴"}]}\'\n',
        encoding="utf-8",
    )
    fake_rag.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "LOCAL_KB_RAG_QUERY": str(fake_rag)}
    p_pol = _run(
        [sys.executable, str(REPO_ROOT / "skills/gov-project-checkup/scripts/run_checkup.py"),
         "policy", "--query", "高企补贴", "--region", "浙江省杭州市", "--strict"],
        env=env,
    )
    assert p_pol.returncode == 2
    assert json.loads(p_pol.stdout)["status"] == "no_match"


# 7. High-Tech: --require-complete-form standalone exit 2 + cross-year without breakdown table + spec path guard
def test_hightech_complete_form_and_cross_year_without_breakdown(tmp_path: Path):
    # 0-table DOCX with ONLY --require-complete-form MUST exit 2
    empty_doc = tmp_path / "zero_tbl.docx"
    d = Document()
    d.add_paragraph("正文无表。")
    d.save(empty_doc)
    p0 = _run([sys.executable, str(REPO_ROOT / "skills/hightech-application-writer/scripts/audit_application_docx.py"), str(empty_doc), "--require-complete-form"])
    assert p0.returncode == 2

    # 2025 RD project with 2024 expense and NO expense breakdown table -> MUST STILL catch cross-year conflict!
    cross_doc = tmp_path / "cross_no_exp.docx"
    d2 = Document()
    d2.add_paragraph("主要情况")
    ts = d2.add_table(rows=4, cols=2)
    ts.cell(0, 0).text, ts.cell(0, 1).text = "年度", "营收"
    ts.cell(1, 0).text, ts.cell(2, 0).text, ts.cell(3, 0).text = "2023", "2024", "2025"
    d2.add_paragraph("研发活动编号：RD01")
    trd = d2.add_table(rows=6, cols=2)
    trd.cell(0, 0).text, trd.cell(0, 1).text = "研发活动名称", "新型阻隔膜研发"
    trd.cell(1, 0).text, trd.cell(1, 1).text = "起止时间", "2025.01-2025.12"
    trd.cell(2, 0).text, trd.cell(2, 1).text = "研发经费近三年总支出（万元）", "100"
    trd.cell(3, 0).text, trd.cell(3, 1).text = "第一年", "0"
    trd.cell(4, 0).text, trd.cell(4, 1).text = "第二年", "40"
    trd.cell(5, 0).text, trd.cell(5, 1).text = "第三年", "60"
    d2.save(cross_doc)
    pc = _run([sys.executable, str(REPO_ROOT / "skills/hightech-application-writer/scripts/audit_application_docx.py"), str(cross_doc), "--strict"])
    assert pc.returncode == 2
    assert any("跨期冲突" in i["issue"] for i in json.loads(pc.stdout).get("rd_expense_issues", []))

    # fill_rd_core_innovation: --report pointing to spec JSON MUST fail without overwriting spec
    spec_f = tmp_path / "spec.json"
    spec_f.write_text('{"schema_version": 1}', encoding="utf-8")
    p_col = _run([
        sys.executable, str(REPO_ROOT / "skills/hightech-application-writer/scripts/fill_rd_core_innovation.py"),
        str(empty_doc), str(spec_f), str(tmp_path / "out.docx"), "--report", str(spec_f),
    ])
    assert p_col.returncode != 0
    assert spec_f.read_text(encoding="utf-8") == '{"schema_version": 1}'


# 8. SME assessment validator: empty/null hard_gates blocked, provincial SME 50-point floor passes 55
def test_sme_validator_hard_gates_and_provincial_score(tmp_path: Path):
    base = {
        "application_context": {"project_level": "省级专精特新中小企业", "region": "浙江省", "year": 2026, "application_type": "recognition", "form_version": "2026", "version_status": "confirmed", "policy_status": "current"},
        "overall_conclusion": "eligible",
        "four_judgments": {k: {"decision": "retain", "evidence_state": "verified", "object": "产品", "reason": "依据充分", "actions": ["无"]} for k in ("leading_product", "bottleneck", "gap_filling", "import_substitution")},
        "hard_gates": {"revenue": {"pass": True}},
        "evaluation": {"quality_score": {"status": "verified-platform-score", "value": 55, "source": "工信部平台"}},
        "evidence_gaps": [], "risks": [], "actions": [],
    }
    f_ok = tmp_path / "sme_ok.json"
    f_ok.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    assert _run([sys.executable, str(REPO_ROOT / "skills/sme-giant-writer/scripts/validate_sme_assessment.py"), str(f_ok), "--strict"]).returncode == 0

    f_empty = tmp_path / "sme_empty_hg.json"
    f_empty.write_text(json.dumps({**base, "hard_gates": {}}, ensure_ascii=False), encoding="utf-8")
    assert _run([sys.executable, str(REPO_ROOT / "skills/sme-giant-writer/scripts/validate_sme_assessment.py"), str(f_empty), "--strict"]).returncode == 2

    f_null = tmp_path / "sme_null_hg.json"
    f_null.write_text(json.dumps({**base, "hard_gates": {"revenue": {"pass": None}}}, ensure_ascii=False), encoding="utf-8")
    assert _run([sys.executable, str(REPO_ROOT / "skills/sme-giant-writer/scripts/validate_sme_assessment.py"), str(f_null), "--strict"]).returncode == 2


# 9. General Grant: 169号文 exact tiers, draft partial_pass, subsidy cross-card invoice cap, feasibility ambiguity
def test_general_grant_169_subsidy_and_feasibility(tmp_path: Path):
    script = str(REPO_ROOT / "skills/general-grant-writer/scripts/validate_grant_deliverable.py")
    common = {"rd_staff_count": 60, "rd_equipment_original_value": 1200, "rd_venue_area_m2": 1200}

    # 3000万 / 149.9万 -> 4.9967% < 5% MUST FAIL
    f1 = tmp_path / "i1.json"
    f1.write_text(json.dumps({**common, "tier": "provincial_institute", "latest_revenue": 3000, "latest_rd_expense": 149.9}))
    assert _run([sys.executable, script, "--track", "institute", "--input", str(f1)]).returncode == 2

    # 1亿 / 300万 on provincial_key_institute -> MUST FAIL (rev<2亿, ratio<4%, exp<5000万)
    f2 = tmp_path / "i2.json"
    f2.write_text(json.dumps({**common, "tier": "provincial_key_institute", "latest_revenue": 10000, "latest_rd_expense": 300}))
    assert _run([sys.executable, script, "--track", "institute", "--input", str(f2)]).returncode == 2

    # 1.5亿 / 250万 on provincial_institute -> MUST PASS (5000万~2亿: >=4% OR >=250万)
    f3 = tmp_path / "i3.json"
    f3.write_text(json.dumps({**common, "tier": "provincial_institute", "latest_revenue": 15000, "latest_rd_expense": 250}))
    assert _run([sys.executable, script, "--track", "institute", "--input", str(f3)]).returncode == 0

    # draft mode with missing fields -> exit 0 & status == partial_pass
    f_draft = tmp_path / "idraft.json"
    f_draft.write_text(json.dumps({"tier": "provincial_institute", "latest_revenue": 15000, "latest_rd_expense": 250}))
    p_dr = _run([sys.executable, script, "--track", "institute", "--mode", "draft", "--input", str(f_draft)])
    assert p_dr.returncode == 0 and json.loads(p_dr.stdout)["status"] == "partial_pass"

    # Subsidy: same 100万 invoice on 2 asset cards at full amount -> MUST FAIL (no 200万 doubling)
    f_sub = tmp_path / "sub.json"
    f_sub.write_text(json.dumps({
        "construction_start": "2025-01-01", "construction_end": "2025-12-31",
        "investments": [
            {"asset_name": "主机A", "invoice_no": "INV-001", "asset_card_no": "CARD-1", "invoice_date": "2025-06-01", "contract_amount": 100, "invoice_amount": 100, "paid_amount": 100},
            {"asset_name": "主机B", "invoice_no": "INV-001", "asset_card_no": "CARD-2", "invoice_date": "2025-06-01", "contract_amount": 100, "invoice_amount": 100, "paid_amount": 100},
        ],
    }))
    assert _run([sys.executable, script, "--track", "subsidy", "--input", str(f_sub)]).returncode == 2

    # Feasibility: generic "不低于" collapsing 2 requirements -> MUST FAIL
    f_feas = tmp_path / "feas.json"
    f_feas.write_text(json.dumps({
        "template_requirements": ["营业收入不低于5000万元", "研发强度不低于4%"],
        "conditions": [{"match": "不低于"}],
    }))
    assert _run([sys.executable, script, "--track", "feasibility", "--input", str(f_feas)]).returncode == 2


# 10. Patent review_adder: default scope_impact enforcement + renders standalone scope_impact + preserves existing target on skip
def test_patent_review_adder_scope_and_no_clobber(tmp_path: Path):
    src, dst, rev = tmp_path / "src.docx", tmp_path / "dst.docx", tmp_path / "rev.json"
    d = Document()
    d.add_paragraph("权利要求1：一种导轨固定结构。")
    d.save(src)
    script = str(REPO_ROOT / "skills/patent-docx-reviewer/scripts/review_adder.py")

    # Missing scope_impact blocked by default CLI
    rev.write_text(json.dumps([{"highlight_text": "导轨", "comment": "核对术语"}]), encoding="utf-8")
    assert _run([sys.executable, script, str(src), str(dst), "--reviews-file", str(rev)]).returncode != 0

    # Standalone scope_impact is rendered into comments.xml
    rev.write_text(json.dumps([{"highlight_text": "导轨", "comment": "核对术语", "保护范围影响": "限缩"}]), encoding="utf-8")
    assert _run([sys.executable, script, str(src), str(dst), "--reviews-file", str(rev)]).returncode == 0
    with zipfile.ZipFile(dst) as zf:
        cxml = zf.read("word/comments.xml").decode("utf-8")
    assert "保护范围影响：限缩" in cxml
    orig_bytes = dst.read_bytes()

    # Out-of-bounds occurrence_in_paragraph with --overwrite MUST NOT clobber existing target
    rev.write_text(json.dumps([{"highlight_text": "导轨", "occurrence_in_paragraph": 5, "comment": "越界", "保护范围影响": "不动"}]), encoding="utf-8")
    p_oob = _run([sys.executable, script, str(src), str(dst), "--reviews-file", str(rev), "--overwrite"])
    assert p_oob.returncode == 1
    assert dst.read_bytes() == orig_bytes


# 11. Standard drafting: excludes 注/资料性附录, catches year mismatch & repeated filler
def test_standard_drafting_strict_rules():
    sys.path.insert(0, str(REPO_ROOT / "skills/standard-drafting/scripts"))
    import audit_standard_draft  # noqa: E402

    # Code only cited in 注 -> uncited error
    s_note = "# 1 范围\n本文件规定指标。\n# 2 规范性引用文件\nGB/T 1234—2020 试验规范\n# 3 要求\n产品应符合要求。\n注：可参照 GB/T 1234—2020。\n# 4 试验方法\n按本文件规定的标准测试方法连续测定样品三组并记录结果。\n"
    assert any(f["code"] == "uncited-normative-reference" for f in audit_standard_draft.audit(s_note)["findings"])

    # Different year cited in body -> version mismatch
    s_yr = "# 1 范围\n本文件规定指标。\n# 2 规范性引用文件\nGB/T 1234—2020 试验规范\n# 3 要求\n产品应符合 GB/T 1234—2018 规定。\n# 4 试验方法\n按 GB/T 1234—2020 在恒温条件下测定三组样品并记录结果。\n"
    assert any(f["code"] == "normative-reference-version-mismatch" for f in audit_standard_draft.audit(s_yr)["findings"])

    # Test method ONLY in informative appendix -> missing-verification
    s_app = "# 1 范围\n本文件规定指标。\n# 2 规范性引用文件\n无。\n# 3 要求\n产品应符合指标。\n# 附录 A（资料性） 试验方法\n按标准测试工况测定样品厚度与拉伸强度并记录全部检测数据。\n"
    assert any(f["code"] == "missing-verification" for f in audit_standard_draft.audit(s_app)["findings"])

    # Repeated filler instruction -> empty-verification-section
    s_fill = "# 1 范围\n本文件规定指标。\n# 2 规范性引用文件\n无。\n# 3 要求\n产品应符合指标。\n# 4 试验方法\n请补充具体试验方法。\n请补充具体试验方法。\n请补充具体试验方法。\n"
    assert any(f["code"] == "empty-verification-section" for f in audit_standard_draft.audit(s_fill)["findings"])


# 12. Enterprise Due Diligence: duplicate JSON section key rejected, --strict requires --company-type
def test_due_diligence_duplicate_key_and_company_type(tmp_path: Path):
    sys.path.insert(0, str(REPO_ROOT / "skills/enterprise-due-diligence/scripts"))
    import build_standard_html  # noqa: E402

    dup = tmp_path / "dup.json"
    dup.write_text('{"company":{"name":"测试公司"},"sections":{"02":{"paragraphs":["一"]},"02":{"paragraphs":["二"]}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="重复键"):
        build_standard_html.render_standard_html(dup)

    # Strict company law check without --company-type MUST exit 2
    p_no_type = _run([
        sys.executable, str(REPO_ROOT / "skills/enterprise-due-diligence/scripts/check_company_law.py"),
        "paid-in", "--founded", "2019-01-01", "--subscribed-deadline", "2030-01-01",
        "--registered-wan", "1000", "--paid-in-wan", "500", "--strict",
    ])
    assert p_no_type.returncode == 2
    # Explicit --company-type jsc blocks 2030 deadline for legacy JSC
    p_jsc = _run([
        sys.executable, str(REPO_ROOT / "skills/enterprise-due-diligence/scripts/check_company_law.py"),
        "paid-in", "--company-type", "jsc", "--founded", "2019-01-01", "--subscribed-deadline", "2030-01-01",
        "--registered-wan", "1000", "--paid-in-wan", "500", "--strict",
    ])
    assert p_jsc.returncode == 2


# 13. Manufacturing Tax Risk: credit_code/period/balance-sheet reconciliation & input overwrite guard
def test_manufacturing_tax_reconciliation_and_path_guards(tmp_path: Path):
    calc_script = str(REPO_ROOT / "skills/manufacturing-tax-risk/scripts/calculate_metrics.py")
    html_script = str(REPO_ROOT / "skills/manufacturing-tax-risk/scripts/generate_report_html.py")

    sample_in = tmp_path / "in.json"
    year_row = {
        "revenue": 1000, "cost": 600, "profit_before_tax": 100, "net_profit": 80,
        "assets": 100, "assets_open": 90, "liabilities": 40, "equity": 80, "equity_open": 70,  # gap = -20!
        "current_assets": 60, "current_liabilities": 30, "cash": 20, "receivables": 10, "receivables_open": 10,
        "other_receivables": 5, "inventory": 15, "inventory_open": 15, "advances_from_customers": 5,
        "short_term_loans": 10, "operating_cash_flow": 90, "capex_cash": 10, "taxes_paid": 20,
        "sales_cash": 1050, "research_expense": 50, "interest_expense": 2, "income_tax_expense": 20,
    }
    sample_in.write_text(json.dumps({"company": {"name": "测试制造有限公司", "unified_social_credit_code": ""}, "years": {"2025": year_row}}), encoding="utf-8")

    # Overwriting input path MUST fail
    assert _run([sys.executable, calc_script, str(sample_in), str(sample_in)]).returncode != 0

    facts_out, metrics_out = tmp_path / "facts.json", tmp_path / "metrics.json"
    assert _run([sys.executable, calc_script, str(sample_in), str(facts_out), "--metrics-output", str(metrics_out)]).returncode == 0

    # Report with credit_code while metrics lacks credit_code + period mismatch (2024 vs 2025) + balance sheet gap -20 -> MUST BLOCK formal ok (exit 2)
    rep_in = tmp_path / "rep.json"
    rep_in.write_text(json.dumps({
        "company": "测试制造有限公司",
        "credit_code": "91330100MA27X1234A",
        "period": {"start": "2023", "end": "2024"},
        "financial_overview": {"years": ["2025"], "rows": [], "kpis": [], "conclusion": "{{financial.2025.facts.revenue}}"},
    }, ensure_ascii=False), encoding="utf-8")
    out_html = tmp_path / "report.html"
    p_html = _run([sys.executable, html_script, str(rep_in), str(out_html), "--metrics-json", str(metrics_out)])
    assert p_html.returncode == 2
    receipt = json.loads(p_html.stdout)
    assert receipt["status"] == "blocked_unreconciled"
    assert len(receipt["blocking_issues"]) >= 3
    # Diagnostic draft HTML is still preserved for review
    assert out_html.is_file()

    # Overwriting input JSON with HTML output MUST fail
    assert _run([sys.executable, html_script, str(rep_in), str(rep_in), "--metrics-json", str(metrics_out)]).returncode != 0

    # Existing formal HTML report MUST NOT be overwritten when blocked (diagnostic goes to .draft.html)
    formal_html = tmp_path / "formal_existing.html"
    formal_html.write_text("ORIGINAL_FORMAL_HTML", encoding="utf-8")
    p_keep = _run([sys.executable, html_script, str(rep_in), str(formal_html), "--metrics-json", str(metrics_out)])
    assert p_keep.returncode == 2
    assert formal_html.read_text(encoding="utf-8") == "ORIGINAL_FORMAL_HTML"
    assert formal_html.with_suffix(".draft.html").is_file()


def test_round3_six_surgical_fixes(tmp_path: Path, monkeypatch):
    # 1. Local RAG real field name sensitivity=restricted
    fake_rag = tmp_path / "rag_sens.sh"
    fake_rag.write_text(
        '#!/bin/sh\necho \'{"results":[{"title":"小巨人内部底稿","sensitivity":"restricted","excerpt":"小巨人公开测试词"},{"title":"小巨人办法","sensitivity":"public","excerpt":"小巨人公开测试词"}]}\'\n',
        encoding="utf-8",
    )
    fake_rag.chmod(0o755)
    monkeypatch.setattr(kb_local, "RAG_QUERY_SH", fake_rag)
    r_rag = kb_local.search_local_rag("小巨人", limit=5)
    assert r_rag["count"] == 1 and r_rag["dropped"]["restricted"] == 1

    # 2. High-tech single-sided missing tech_employees -> partial_pass (not fail!)
    sys.path.insert(0, str(REPO_ROOT / "skills/gov-project-checkup/scripts"))
    import run_checkup  # noqa: E402
    ht_one_side = {
        "founded_date": "2020-01-01",
        "balance_sheet": {"total_assets": 1000, "total_liabilities": 400, "total_equity": 600},
        "patents": [{"type": "发明", "patent_no": "ZL202110123456.7"}],
        "total_employees": 100,
        "latest_revenue": 6000, "hightech_product_revenue": 4500,
        "revenue_3y": 15000, "rd_expense_3y": 900, "domestic_rd_expense_3y": 900,
    }
    res_os = run_checkup.check_hightech(ht_one_side, strict=False)
    assert res_os["status"] == "partial_pass" and res_os["errors"] == []

    # 3. Little Giant rejects utility models even if forged with ip_class="I"
    fake_i_utils = [{"type": "实用新型", "ip_class": "I", "patent_no": f"ZL20222012345{i}.7"} for i in range(4)]
    res_util = run_checkup.check_sme({
        "target_tier": "little_giant",
        "balance_sheet": {"total_assets": 10000, "total_liabilities": 7000, "total_equity": 3000},
        "latest_revenue": 9000, "annual_revenues": [7000, 8000, 9000], "rd_expenses_2y": [600, 600],
        "patents": fake_i_utils,
    }, strict=True)
    assert res_util["status"] == "fail" and res_util["gates"]["i_class_ip"]["valid_i_class_count"] == 0

    # 4. Standard drafting excludes two-line informative appendix ("# 附录 A\n（资料性）")
    sys.path.insert(0, str(REPO_ROOT / "skills/standard-drafting/scripts"))
    import audit_standard_draft  # noqa: E402
    two_line_app = "# 1 范围\n本文件规定指标。\n# 2 规范性引用文件\n无。\n# 3 要求\n产品应符合要求。\n# 附录 A\n（资料性）\n## A.1 试验方法\n按标准工况测定三组样品并记录完整数据结果。\n"
    assert any(f["code"] == "missing-verification" for f in audit_standard_draft.audit(two_line_app)["findings"])

    # 5. 169 mountain/island cannot pass with 0 R&D or missing basis; subsidy 50.2+50.2 > 100 blocked
    grant_script = str(REPO_ROOT / "skills/general-grant-writer/scripts/validate_grant_deliverable.py")
    f_mt = tmp_path / "mt.json"
    f_mt.write_text(json.dumps({
        "tier": "provincial_key_institute", "is_mountain_island_county": True,
        "latest_revenue": 100, "latest_rd_expense": 0,
        "rd_staff_count": 60, "rd_equipment_original_value": 1200, "rd_venue_area_m2": 1200,
    }))
    assert _run([sys.executable, grant_script, "--track", "institute", "--input", str(f_mt)]).returncode == 2

    f_sub2 = tmp_path / "sub2.json"
    f_sub2.write_text(json.dumps({
        "construction_start": "2025-01-01", "construction_end": "2025-12-31",
        "investments": [
            {"asset_name": "卡1", "invoice_no": "INV-9", "asset_card_no": "C1", "invoice_date": "2025-05-01", "contract_amount": 100, "invoice_amount": 100, "allocated_amount": 50.2, "paid_amount": 100},
            {"asset_name": "卡2", "invoice_no": "INV-9", "asset_card_no": "C2", "invoice_date": "2025-05-01", "contract_amount": 100, "invoice_amount": 100, "allocated_amount": 50.2, "paid_amount": 100},
        ],
    }))
    assert _run([sys.executable, grant_script, "--track", "subsidy", "--input", str(f_sub2)]).returncode == 2


# 14. Post-real-case fixes: Zhejiang single_champion 179号文 wording, SME stat_cutoff_date filter, High-Tech transferred patent no 1-year false block
def test_real_enterprise_shenxin_3_bugfixes(tmp_path: Path):
    # Bug 1: single_champion Zhejiang 179号文 basic gate is 全球前五或全国前三 + 近三年任一年主营收入≥4亿元
    adapters = json.loads((REPO_ROOT / "skills/sme-giant-writer/references/project-view-adapters.json").read_text(encoding="utf-8"))
    sc = adapters["adapters"]["single_champion"]
    assert "全球前五或全国前三" in sc["commercial_basis"]
    assert "近三年任一年主营业务收入原则上达4亿元" in sc["commercial_basis"]
    assert "近三年平均主营收入" not in json.dumps(sc, ensure_ascii=False)

    sys.path.insert(0, str(REPO_ROOT / "skills/gov-project-checkup/scripts"))
    import run_checkup  # noqa: E402

    # Bug 2: Little Giant stat_cutoff_date excludes post-cutoff granted invention patent
    sme_cutoff = {
        "target_tier": "little_giant",
        "stat_cutoff_date": "2025-12-31",
        "balance_sheet": {"total_assets": 55168.21, "total_liabilities": 24811.25, "total_equity": 30356.96},
        "latest_revenue": 61002.09, "annual_revenues": [38874.51, 48726.90, 61002.09],
        "rd_expenses_2y": [1672.87, 2050.83],
        "patents": [
            {"patent_no": "ZL202011071894.5", "type": "发明专利", "filing_date": "2020-10-09", "grant_date": "2024-06-21", "acquisition": "自主研发"},
            {"patent_no": "ZL202011071891.1", "type": "发明专利", "filing_date": "2020-10-09", "grant_date": "2025-04-04", "acquisition": "自主研发"},
            {"patent_no": "ZL202310414797.9", "type": "发明专利", "filing_date": "2023-04-18", "grant_date": "2025-11-14", "acquisition": "自主研发"},
            {"patent_no": "ZL202510920827.2", "type": "发明专利", "filing_date": "2025-07-04", "grant_date": "2026-06-19", "acquisition": "自主研发"},
        ],
    }
    res_cut = run_checkup.check_sme(sme_cutoff, strict=True)
    assert res_cut["status"] == "fail"
    assert res_cut["gates"]["i_class_ip"]["valid_i_class_count"] == 3
    assert any("晚于批次统计截止日" in e for e in res_cut["errors"])

    # Bug 3: High-Tech does NOT falsely block transferred patent missing transfer_date (国科发火〔2016〕32号/195号 has no 1-year holding gate)
    ht_transfer = {
        "founded_date": "2003-07-01",
        "balance_sheet": {"total_assets": 55168.21, "total_liabilities": 24811.25, "total_equity": 30356.96},
        "patents": [
            {"patent_no": "ZL202011071894.5", "type": "发明专利", "filing_date": "2020-10-09", "grant_date": "2024-06-21", "acquisition": "自主研发"},
            {"patent_no": "ZL201911000594.5", "type": "发明专利", "filing_date": "2019-10-21", "grant_date": "2022-11-08", "acquisition": "受让"},
        ],
        "total_employees": 303, "tech_employees": 62,
        "latest_revenue": 61002.09, "hightech_product_revenue": 56666.79,
        "revenue_3y": 148603.50, "rd_expense_3y": 5001.79, "domestic_rd_expense_3y": 5001.79,
    }
    res_ht = run_checkup.check_hightech(ht_transfer, strict=True)
    assert res_ht["status"] == "pass" and res_ht["gates"]["ip_validity"]["valid_count"] == 2
    assert any("著录项目变更通知书" in w for w in res_ht["warnings"])


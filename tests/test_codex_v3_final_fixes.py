from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from docx import Document
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "skills" / "_core",
    ROOT / "skills" / "gov-project-checkup" / "scripts",
    ROOT / "skills" / "general-grant-writer" / "scripts",
    ROOT / "src",
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fact_ledger  # noqa: E402
import quality_gate  # noqa: E402
import run_checkup  # noqa: E402
import select_report_template  # noqa: E402
import split_application_sections as sas  # noqa: E402
import validate_grant_deliverable as vgd  # noqa: E402
from project_assistant.skill_integrity import trusted_publisher_fingerprint, verify_skill_directory  # noqa: E402


def test_hightech_and_sme_explicit_hard_gates_block_false_pass() -> None:
    ht_bad = {
        "founded_date": "2020-01-01",
        "balance_sheet": {"total_assets": 1000, "total_liabilities": 400, "total_equity": 600},
        "patents": [{"type": "发明", "patent_no": "ZL202110123456.7"}],
        "total_employees": 100, "tech_employees": 20,
        "latest_revenue": 6000, "hightech_product_revenue": 4500,
        "revenue_3y": 15000, "rd_expense_3y": 900, "domestic_rd_expense_3y": 900,
        "in_supported_field": False,
        "innovation_score": 0,
        "major_safety_quality_env_accident": True,
    }
    res_ht = run_checkup.check_hightech(ht_bad, strict=True)
    # Objective gates (field + major accident) block; subjective innovation_score is NOT scored as an error
    assert res_ht["status"] == "fail" and len(res_ht["errors"]) == 2
    assert any("不测分" in w for w in res_ht["warnings"])

    own_4 = [{"type": "发明", "patent_no": f"ZL20211012345{i}.7"} for i in range(4)]
    sme_score_only = {
        "target_tier": "little_giant",
        "balance_sheet": {"total_assets": 10000, "total_liabilities": 6000, "total_equity": 4000},
        "latest_revenue": 9000, "annual_revenues": [7000, 8000, 9000],
        "rd_expenses_2y": [600, 600], "patents": own_4,
        "quality_score": 40,
    }
    res_sme_score = run_checkup.check_sme(sme_score_only, strict=True)
    assert res_sme_score["status"] == "pass" and any("不测分" in w for w in res_sme_score["warnings"])

    sme_bad = {
        **sme_score_only,
        "main_business_ratio_pct": 10.0, "niche_years": 1, "has_prerequisite_title": False,
    }
    res_sme = run_checkup.check_sme(sme_bad, strict=True)
    assert res_sme["status"] == "fail" and len(res_sme["errors"]) >= 3


def test_patent_legal_status_business_type_and_exemption_guard() -> None:
    pending_tooling = [
        {"type": "发明", "patent_no": f"ZL20211012345{i}.7", "legal_status": "审中", "role": "自用工装"}
        for i in range(4)
    ]
    base = {
        "target_tier": "little_giant",
        "balance_sheet": {"total_assets": 10000, "total_liabilities": 6000, "total_equity": 4000},
        "latest_revenue": 9000, "annual_revenues": [7000, 8000, 9000],
        "rd_expenses_2y": [600, 600],
    }
    # Pending + self-use tooling must NOT count
    r1 = run_checkup.check_sme({**base, "business_type": "product_or_material_maker", "patents": pending_tooling}, strict=True)
    assert r1["status"] == "fail"

    # Granted self-use tooling excluded for product/material maker, INCLUDED for equipment maker
    granted_tooling = [
        {"type": "发明", "patent_no": f"ZL20211012345{i}.7", "legal_status": "授权有效", "role": "自用工装"}
        for i in range(4)
    ]
    r_mat = run_checkup.check_sme({**base, "business_type": "product_or_material_maker", "patents": granted_tooling}, strict=True)
    assert r_mat["status"] == "fail"
    r_eq = run_checkup.check_sme({**base, "business_type": "equipment_or_mold_maker", "patents": granted_tooling}, strict=True)
    assert r_eq["status"] == "pass"

    # Negation-first patent status ("未授权，已公开" / "授权后终止") must be rejected even though text contains "授权"
    tricky_pats = [
        {"type": "发明", "patent_no": "ZL202110123450.7", "legal_status": "未授权，已公开"},
        {"type": "发明", "patent_no": "ZL202110123451.7", "legal_status": "授权后终止"},
    ]
    for tp in tricky_pats:
        assert fact_ledger.validate_patent_item(tp)

    # Little Giant IP exemption rejects provincial award rank 5
    r_ex_bad = run_checkup.check_sme({**base, "ip_exemption_reason": "省级科技进步奖，排名第五", "ip_exemption_evidence": "第1页"}, strict=True)
    assert r_ex_bad["status"] == "fail"

    # Strict bool/range parsing catches "否", 101%, "无"
    own_4 = [{"type": "发明", "patent_no": f"ZL20211012345{i}.7"} for i in range(4)]
    r_edge = run_checkup.check_sme({**base, "patents": own_4, "main_business_ratio_pct": 101, "has_prerequisite_title": "否", "niche_years": "无"}, strict=True)
    assert r_edge["status"] == "fail" and len(r_edge["errors"]) >= 3


def test_zhejiang_institute_rd_center_cancelled_and_three_first_invalid_date() -> None:
    errs = vgd.validate_institute({
        "tier": "rd_center", "latest_revenue": 5000, "latest_rd_expense": 300,
        "rd_staff_count": 20, "rd_equipment_original_value": 300, "rd_venue_area_m2": 300,
    })
    assert errs and "取消" in errs[0]

    # Evaluation-table staff count (49 < 50) should NOT hard-fail provincial key institute
    errs_49 = vgd.validate_institute({
        "tier": "provincial_key_institute", "latest_revenue": 25000, "latest_rd_expense": 1200,
        "rd_staff_count": 49, "rd_equipment_original_value": 1200, "rd_venue_area_m2": 1200,
    })
    assert errs_49 == []

    # Three-first validates strict full date format AND transitive design <= test without prototype_date
    tf_errs = vgd.validate_three_first({
        "conclusion": "eligible",
        "evidences": [{"name": "检测报告", "locator": "第1页"}],
        "design_start_date": "2025-05-01（暂定）",
    })
    assert any("日期格式无效" in e for e in tf_errs)
    tf_order = vgd.validate_three_first({
        "conclusion": "eligible",
        "evidences": [{"name": "检测报告", "locator": "第1页"}],
        "design_start_date": "2025-05-01",
        "test_report_date": "2025-03-01",
    })
    assert any("时间线倒挂" in e for e in tf_order)


def test_quality_gate_exact_subject_and_cross_year_swap() -> None:
    res = quality_gate.audit_formal_text(
        "申报单位：南方示例科技有限公司，从事精密部件制造。",
        expected_company="示例科技有限公司",
    )
    assert any(e["rule"] == "cross_enterprise_contamination" for e in res["errors"])

    src = "2024年研发费用为120万元，2025年研发费用为240万元。"
    swapped = "2024年研发费用为240万元，2025年研发费用为120万元。"
    rf = quality_gate.audit_rewrite_fidelity(src, swapped)
    assert any(e["rule"] == "year_value_swap" for e in rf["errors"])


def test_split_sections_year_isolation_and_multiline_summary(tmp_path: Path) -> None:
    txt = (
        "目录\n二、经济效益和经营情况……2\n"
        "一、企业基本情况\n企业名称 示例精密有限公司\n"
        "二、经济效益和经营情况\n重要指标 2023年 2024年 2025年\n"
        "三、专业化\n2026年工信部公告\n"
        "七、产业链配套\n说明（是否在细分领域实现关键技术首创等情况，300字以内）：" + ("技" * 280) + "\n主导产品是否为国内外知名大企业\n"
        "企业总体情况简要介绍（2000字以内，请勿\n另附页）\n公司成立于2015年，专注精密传动。\n真实性声明\n"
    )
    f = tmp_path / "app.txt"
    f.write_text(txt, encoding="utf-8")
    res = sas.run(f, company="示例精密有限公司")
    assert res["base_year"]["Y"] == 2025
    assert res["narrative_boxes"]["gap_filling_note"]["chars"] == 280
    assert res["narrative_boxes"]["summary_intro"]["found"] is True


def test_portable_lock_fallback_without_fcntl(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fact_ledger, "fcntl", None)
    monkeypatch.setattr(fact_ledger, "msvcrt", None)
    errors: list[Exception] = []

    def worker(idx: int) -> None:
        try:
            def _mut(bb: dict) -> None:
                bb.setdefault("checkupSnapshots", {})[f"k{idx}"] = idx
            fact_ledger.update_blackboard(tmp_path, "并发测试有限公司", "", _mut, strict=True)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    bb, _ = fact_ledger.load_blackboard(tmp_path, "并发测试有限公司", "", strict=True)
    assert bb and len(bb["checkupSnapshots"]) == 6


def test_hightech_natural_metric_passes_and_complete_form_requires_15_rd(tmp_path: Path) -> None:
    audit_script = ROOT / "skills/hightech-application-writer/scripts/audit_application_docx.py"
    sys.path.insert(0, str(audit_script.parent))
    import audit_application_docx as aad  # noqa: E402

    assert aad.RD_TECH_PATTERN.search("1、高速响应控制技术：通过动态补偿，响应时间控制在 10 ms 以内。")
    assert aad.RD_TECH_PATTERN.search("2、闭环补偿算法：通过动态补偿，响应时间控制在 10 ms 以内。")
    assert aad.UNIT_OR_BOUNDARY.search("响应时间控制在 10 ms 以内")

    # 1-RD doc fails --require-complete-form
    doc = Document()
    doc.add_paragraph("研发活动编号：RD01")
    t = doc.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text = "研发活动名称"
    t.rows[0].cells[1].text = "测试研发"
    t.rows[1].cells[0].text = "核心技术及创新点"
    t.rows[1].cells[1].text = "高新技术领域：电子信息\n核心技术\n1、高速响应控制技术：响应时间控制在 10 ms 以内。\n2、低噪滤波技术：信噪比提升至 65 dB 以上。\n创新点\n1、首创架构。\n2、集成设计。"
    p = tmp_path / "one_rd.docx"
    doc.save(p)
    proc = subprocess.run([sys.executable, str(audit_script), str(p), "--require-complete-form"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert any("15 个以上" in i["issue"] for i in json.loads(proc.stdout).get("required_field_issues", []))


def test_grant_report_generation_e2e_and_no_hash_locks(tmp_path: Path) -> None:
    sel = select_report_template.resolve_template("首台套", "可行性分析报告")
    assert Path(sel["template_path"]).is_file()
    assert "template_sha256" not in sel

    # End-to-end real DOCX generation for 首台套 using bundled master (verifies enterprise name fills cleanly)
    src_ev = tmp_path / "source.txt"
    src_ev.write_text("首台套检测报告，精度0.002mm。", encoding="utf-8")
    fixture = {
        "project_id": "first-equipment",
        "enterprise": "示例精密机床股份有限公司",
        "project_object": "五轴联动高精度数控工具磨床",
        "suggested_year": "2026",
        "conclusion": "可申报",
        "conclusion_basis": "核心整机自主可控，满足首台套基本要求",
        "primary_gap": "需补充首台用户应用验收证明",
        "next_action": "两周内收集首台用户合同与验收单",
        "policies": [{"title": "浙江省首台（套）装备认定办法", "locator": "https://jxt.zj.gov.cn/"}],
        "sources": [{"name": "检测报告", "path": str(src_ev), "anchors": ["精度0.002mm"]}],
        "conditions": [{"match": "要求", "value": "已达标", "gap": "无", "action": "保持", "priority": "低"}],
        "table_content": [],
    }
    fx_path = tmp_path / "fx.json"
    fx_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    out_docx = tmp_path / "out_first_eq.docx"
    gen_script = ROOT / "skills/general-grant-writer/scripts/generate_report.py"
    proc = subprocess.run(
        [sys.executable, str(gen_script), "--input", str(fx_path), "--output", str(out_docx), "--report-type", "feasibility"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out_docx.is_file()
    doc_text = "\n".join(p.text for p in Document(out_docx).paragraphs)
    assert "示例精密机床股份有限公司" in doc_text

    # Empty manifest guard remains active without hash lock
    empty_manifest = tmp_path / "empty.json"
    empty_manifest.write_text('{"version": "3.0.0", "bundles": []}', encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    marker = out_dir / "keep.txt"
    marker.write_text("existing", encoding="utf-8")
    proc_e = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_workbuddy_single.py"), "--manifest", str(empty_manifest), "--output", str(out_dir)],
        capture_output=True, text=True,
    )
    assert proc_e.returncode == 2
    assert marker.read_text(encoding="utf-8") == "existing"

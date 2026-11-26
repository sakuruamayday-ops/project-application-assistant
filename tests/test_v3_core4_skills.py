from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"


def _run(cmd: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)


# ---------- 1. gov-project-checkup ----------


def test_gov_project_checkup_positive_and_negative(tmp_path: Path):
    cli = SKILLS / "gov-project-checkup" / "scripts" / "run_checkup.py"

    # Negative high-tech: unbalanced balance sheet + expired utility patent + low R&D ratio -> exit 2 under --strict
    bad_ht = tmp_path / "bad_ht.json"
    bad_ht.write_text(
        json.dumps(
            {
                "founded_date": "2020-01-01",
                "balance_sheet": {"total_assets": 1000, "total_liabilities": 600, "total_equity": 999},
                "patents": [{"patent_no": "ZL201220123456.7", "type": "实用新型", "filing_date": "2012-03-01"}],
                "total_employees": 100,
                "tech_employees": 5,
                "latest_revenue": 4000,
                "hightech_product_revenue": 1500,
                "revenue_3y": 10000,
                "rd_expense_3y": 200,
                "domestic_rd_expense_3y": 100,
            }
        ),
        encoding="utf-8",
    )
    p_bad = _run([sys.executable, str(cli), "hightech", "--input", str(bad_ht), "--strict"])
    assert p_bad.returncode == 2
    out_bad = json.loads(p_bad.stdout)
    assert out_bad["ok"] is False
    assert len(out_bad["errors"]) >= 5

    # Positive high-tech -> exit 0
    good_ht = tmp_path / "good_ht.json"
    good_ht.write_text(
        json.dumps(
            {
                "founded_date": "2018-05-01",
                "balance_sheet": {"total_assets": 5000, "total_liabilities": 2000, "total_equity": 3000},
                "patents": [{"patent_no": "ZL202310123456.1", "type": "发明专利", "filing_date": "2023-05-01"}],
                "total_employees": 100,
                "tech_employees": 25,
                "latest_revenue": 4500,
                "hightech_product_revenue": 3600,
                "revenue_3y": 12000,
                "rd_expense_3y": 720,
                "domestic_rd_expense_3y": 720,
                "annual_revenues": [3200, 3800, 4500],
            }
        ),
        encoding="utf-8",
    )
    p_good = _run([sys.executable, str(cli), "hightech", "--input", str(good_ht), "--strict"])
    assert p_good.returncode == 0, p_good.stdout

    # Negative expired policy metadata -> exit 2
    exp_pol = tmp_path / "exp_policy.json"
    exp_pol.write_text(
        json.dumps({"region": "宁波市鄞州区", "expiry_date": "2023-12-31", "requires_guideline": True}),
        encoding="utf-8",
    )
    p_pol = _run([sys.executable, str(cli), "policy", "--metadata-json", str(exp_pol), "--strict"])
    assert p_pol.returncode == 2
    pol_out = json.loads(p_pol.stdout)
    assert pol_out["metadata_validation"]["region_scope"]["city"] == "宁波市"

    # Catalog leaf-weighted search
    p_cat = _run([sys.executable, str(cli), "catalog", "工业软件", "--limit", "5"])
    assert p_cat.returncode == 0
    cat_out = json.loads(p_cat.stdout)
    assert cat_out["search_summary"]["industry_foundation"]["scanned_records"] > 100


# ---------- 2. hightech-application-writer ----------


def _set_song_12(doc: Document) -> None:
    for p in doc.paragraphs:
        for r in p.runs:
            r.font.name = "宋体"
            r.font.size = Pt(12)
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.name = "宋体"
                        r.font.size = Pt(12)
                        r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def test_hightech_strict_blocks_lazy_ps_innovation_and_placeholders(tmp_path: Path):
    audit_cli = SKILLS / "hightech-application-writer" / "scripts" / "audit_application_docx.py"
    fill_cli = SKILLS / "hightech-application-writer" / "scripts" / "fill_rd_core_innovation.py"
    blank_tpl = SKILLS / "hightech-application-writer" / "assets" / "高新技术企业认定申请书空白模板.docx"

    # Negative 1: fill_rd_core_innovation on unexpanded blank template with non-empty items MUST fail (no silent rd_count=0)
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "enterprise_profile": {"name": "测试公司"},
                "items": [
                    {
                        "rd_id": "RD01",
                        "core_technologies": [
                            {"name": "核心算法", "description": "采用低时延调度", "indicators": "时延≤10ms", "indicator_kind": "proposed"},
                            {"name": "加密引擎", "description": "采用国密链路", "indicators": "吞吐≥2000次/秒", "indicator_kind": "proposed"},
                        ],
                        "innovations": ["架构解耦设计。", "零拷贝转发机制。"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    p_blank = _run([sys.executable, str(fill_cli), str(blank_tpl), str(spec), str(tmp_path / "out.docx")])
    assert p_blank.returncode != 0
    assert "未匹配到任何已编号的RD表" in p_blank.stderr

    # Negative 2: 50-char lazy PS / Innovation + XXX placeholder MUST exit 2 under --strict
    doc = Document()
    doc.add_paragraph("企业注册登记表")
    t0 = doc.add_table(rows=2, cols=2)
    t0.cell(0, 0).text, t0.cell(0, 1).text = "企业名称", "杭州测试科技有限公司"
    t0.cell(1, 0).text, t0.cell(1, 1).text = "注册时间", "2020.01.01"
    doc.add_paragraph("编号：PS01")
    tps = doc.add_table(rows=4, cols=2)
    tps.cell(0, 0).text, tps.cell(0, 1).text = "产品（服务）名称", "高并发安全网关"
    tps.cell(1, 0).text, tps.cell(1, 1).text = "关键技术及主要技术指标（限400字）", "产品性能优异XXX。"
    tps.cell(2, 0).text, tps.cell(2, 1).text = "与同类产品（服务）的竞争优势（限400字）", "具有明显优势。"
    tps.cell(3, 0).text, tps.cell(3, 1).text = "知识产权获得情况及其对产品（服务）在技术上发挥的支持作用（限400字）", "支撑产品开发。"
    doc.add_paragraph("七、企业创新能力")
    tinv = doc.add_table(rows=4, cols=2)
    for idx, lbl in enumerate(
        ("知识产权对企业竞争力的作用", "科技成果转化情况", "研究开发与技术创新组织管理情况", "管理与科技人员情况")
    ):
        tinv.cell(idx, 0).text = f"{lbl}（限400字）"
        tinv.cell(idx, 1).text = "企业重视研发创新，成果显著。"
    _set_song_12(doc)
    lazy_docx = tmp_path / "lazy.docx"
    doc.save(lazy_docx)

    p_strict = _run([sys.executable, str(audit_cli), str(lazy_docx), "--strict"])
    assert p_strict.returncode == 2
    rep = json.loads(p_strict.stdout)
    assert rep["ps_quality_issue_count"] >= 3
    assert rep["innovation_issue_count"] >= 4
    assert rep["placeholder_count"] >= 1


# ---------- 3. sme-giant-writer ----------


def test_sme_giant_writer_strict_warnings_and_single_champion(tmp_path: Path):
    val_cli = SKILLS / "sme-giant-writer" / "scripts" / "validate_sme_assessment.py"
    mat_cli = SKILLS / "sme-giant-writer" / "scripts" / "technical_product_revenue_matrix.py"
    adapters_path = SKILLS / "sme-giant-writer" / "references" / "project-view-adapters.json"

    # Verify single_champion adapter exists
    adapters = json.loads(adapters_path.read_text(encoding="utf-8"))
    assert "single_champion" in adapters["adapters"]

    # Negative 1: empty direct_support triggers warning -> --strict MUST exit 2!
    asm = {
        "application_context": {
            "project_level": "小巨人",
            "region": "浙江省杭州市",
            "year": 2026,
            "application_type": "新申报",
            "form_version": "2026版",
            "version_status": "confirmed",
            "policy_status": "current",
        },
        "overall_conclusion": "conditional",
        "four_judgments": {
            k: {"decision": "retain", "evidence_state": "verified", "object": "主导产品", "reason": "充分", "actions": ["继续"]}
            for k in ("leading_product", "bottleneck", "gap_filling", "import_substitution")
        },
        "hard_gates": {},
        "evaluation": {"quality_score": {"status": "pending-platform-evaluation", "value": None}},
        "evidence_gaps": [],
        "risks": [],
        "actions": [],
        "ai_meta": {
            "lockedProduct": {"rawAnchor": "阻隔复合膜", "businessType": "product_or_material_maker"},
            "patentTierReport": {"direct_support": [], "production_support": ["ZL202320001.1"]},
        },
    }
    asm_file = tmp_path / "asm.json"
    asm_file.write_text(json.dumps(asm, ensure_ascii=False), encoding="utf-8")
    p_warn = _run([sys.executable, str(val_cli), str(asm_file), "--strict"])
    assert p_warn.returncode == 2
    assert json.loads(p_warn.stdout)["status"] == "fail"

    # Negative 2: string item in performance_contributions must be reported cleanly (no AttributeError crash!)
    bad_mat = tmp_path / "bad_mat.json"
    bad_mat.write_text(
        json.dumps(
            {
                "enterprise": {"name": "测试公司"},
                "technologies": [
                    {
                        "id": "T1",
                        "internal_version": "V1",
                        "public_name": "涂布技术",
                        "carrier_type": "material",
                        "development_status": "mass_production",
                        "technical_goal": "降阻隔",
                        "public_route": "干法",
                        "public_window": "120℃",
                        "confidential_boundary": ["配方比例"],
                        "sources": [{"label": "工艺卡"}],
                    }
                ],
                "products": [
                    {
                        "id": "P1",
                        "name": "复合膜",
                        "product_type": "material",
                        "sales_status": "selling",
                        "sources": [{"label": "发票"}],
                    }
                ],
                "technology_product_links": [
                    {
                        "technology_id": "T1",
                        "product_id": "P1",
                        "relation": "core_enabler",
                        "stable_use": True,
                        "performance_contributions": ["透氧量降低50%"],
                    }
                ],
                "commercialization": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    p_mat = _run([sys.executable, str(mat_cli), "validate", str(bad_mat)])
    assert "Traceback" not in p_mat.stderr
    assert p_mat.returncode != 0


# ---------- 4. application-reviewer ----------


def test_application_reviewer_all_4_modes(tmp_path: Path):
    cli = SKILLS / "application-reviewer" / "scripts" / "review_application.py"

    # 1. Consistency blocks cross-company & hedging
    txt = tmp_path / "draft.md"
    txt.write_text("杭州甲公司研发，同时引用了宁波乙有限公司的数据，仅供参考。", encoding="utf-8")
    p1 = _run([sys.executable, str(cli), "check-consistency", str(txt), "--company", "杭州甲公司"])
    assert p1.returncode == 2

    # 2. Verify ledger blocks 99.99% wrong math
    led = tmp_path / "ledger.json"
    led.write_text(
        json.dumps(
            {
                "entries": [
                    {"kind": "computed", "claim": "研发占比", "formula": "350 / 5000 * 100", "claimed_value": 99.99, "source": "审计报告"}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    p2 = _run([sys.executable, str(cli), "verify-ledger", str(led)])
    assert p2.returncode == 2

    # 3. Audit rewrite blocks tampered ppm & inflated claim
    src = tmp_path / "src.txt"
    rew = tmp_path / "rew.txt"
    src.write_text("纯度达99.999%，氧含量低于15ppm。", encoding="utf-8")
    rew.write_text("纯度达99.999%，技术水平国际领先，氧含量低于5ppm。", encoding="utf-8")
    p3 = _run([sys.executable, str(cli), "audit-rewrite", str(src), str(rew)])
    assert p3.returncode == 2

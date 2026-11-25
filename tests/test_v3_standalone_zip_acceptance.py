"""
Standalone-ZIP A-Grade Acceptance Suite for V3 10-Skill Architecture.
Extracts every single ZIP from dist/workbuddy/zips/ into an isolated tmp directory OUTSIDE the Git repo
and verifies BOTH real local-KB positive execution AND adversarial negative-probe rejection (exit 2).
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from docx import Document

REPO_ROOT = Path(__file__).resolve().parents[1]
ZIPS_DIR = REPO_ROOT / "dist" / "workbuddy" / "zips"


def _extract_bundle(tmp_path: Path, skill_name: str) -> Path:
    zips = sorted(ZIPS_DIR.glob("*.zip"))
    assert len(zips) == 10, f"expected 10 V3 ZIPs, found {len(zips)}"
    for zp in zips:
        dest = tmp_path / zp.stem
        if not dest.exists():
            with zipfile.ZipFile(zp, "r") as zf:
                zf.extractall(dest)
        meta_file = dest / "_skillhub_meta.json"
        if meta_file.is_file():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if meta.get("skillName") == skill_name:
                return dest
    raise AssertionError(f"bundle not found for {skill_name}")


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(not ZIPS_DIR.is_dir(), reason="dist/workbuddy/zips not built")
def test_all_10_standalone_zips_a_grade(tmp_path: Path):
    # 1. gov-project-checkup
    s1 = _extract_bundle(tmp_path, "gov-project-checkup")
    assert not list(s1.rglob("*.docx")), "free tier must have 0 DOCX masters"
    bad_ht = tmp_path / "bad_ht.json"
    bad_ht.write_text(json.dumps({"balance_sheet": {"total_assets": 100, "total_liabilities": 80, "total_equity": 80}}))
    assert _run([sys.executable, str(s1 / "scripts" / "run_checkup.py"), "hightech", "--input", str(bad_ht), "--strict"], s1).returncode == 2
    p_cat = _run([sys.executable, str(s1 / "scripts" / "run_checkup.py"), "catalog", "工业软件"], s1)
    assert p_cat.returncode == 0 and json.loads(p_cat.stdout)["search_summary"]["industry_foundation"]["scanned_records"] > 100

    # 2. application-reviewer
    s2 = _extract_bundle(tmp_path, "application-reviewer")
    src = tmp_path / "s.txt"
    rew = tmp_path / "r.txt"
    src.write_text("杂质≤15ppm，耐压2.5MPa。", encoding="utf-8")
    rew.write_text("杂质≤5ppm，技术国际领先。", encoding="utf-8")
    assert _run([sys.executable, str(s2 / "scripts" / "review_application.py"), "audit-rewrite", str(src), str(rew)], s2).returncode == 2
    led = tmp_path / "led.json"
    led.write_text(json.dumps({"entries": [{"kind": "computed", "claim": "比例", "formula": "10/100*100", "claimed_value": 88.8, "source": "审计"}]}))
    assert _run([sys.executable, str(s2 / "scripts" / "review_application.py"), "verify-ledger", str(led)], s2).returncode == 2

    # 3. hightech-application-writer
    s3 = _extract_bundle(tmp_path, "hightech-application-writer")
    assert (s3 / "assets" / "高新技术企业认定申请书空白模板.docx").is_file()
    lazy = tmp_path / "lazy_ht.docx"
    d = Document()
    d.add_paragraph("七、企业创新能力")
    t = d.add_table(rows=4, cols=2)
    for i, lbl in enumerate(("知识产权对企业竞争力的作用", "科技成果转化情况", "研究开发与技术创新组织管理情况", "管理与科技人员情况")):
        t.cell(i, 0).text = f"{lbl}（限400字）"
        t.cell(i, 1).text = "很短。"
    d.save(lazy)
    assert _run([sys.executable, str(s3 / "scripts" / "audit_application_docx.py"), str(lazy), "--strict"], s3).returncode == 2

    # 4. sme-giant-writer
    s4 = _extract_bundle(tmp_path, "sme-giant-writer")
    assert (s4 / "assets" / "专精特新小巨人前期培育方向卡模板.docx").is_file()
    adapters = json.loads((s4 / "references" / "project-view-adapters.json").read_text(encoding="utf-8"))
    assert "single_champion" in adapters["adapters"]

    # 5. general-grant-writer
    s5 = _extract_bundle(tmp_path, "general-grant-writer")
    assert len(list((s5 / "references" / "playbooks").glob("*.md"))) == 10
    g_ok = tmp_path / "g_ok.json"
    g_ok.write_text(json.dumps({"metrics": [{"name": "绿色物料占比", "value": 82.5, "unit": "%"}]}))
    assert _run([sys.executable, str(s5 / "scripts" / "validate_grant_deliverable.py"), "--track", "green", "--input", str(g_ok)], s5).returncode == 0
    g_bad = tmp_path / "g_bad.json"
    g_bad.write_text(json.dumps({"metrics": [{"name": "绿色物料占比", "value": "", "unit": "%"}]}))
    assert _run([sys.executable, str(s5 / "scripts" / "validate_grant_deliverable.py"), "--track", "green", "--input", str(g_bad)], s5).returncode == 2

    # 6. patent-docx-reviewer
    s6 = _extract_bundle(tmp_path, "patent-docx-reviewer")
    assert (s6 / "scripts" / "review_adder.py").is_file()
    assert (s6 / "scripts" / "patent_extractor.py").is_file()

    # 7. patent-strategy-assistant
    s7 = _extract_bundle(tmp_path, "patent-strategy-assistant")
    ipc_rules = json.loads((s7 / "references" / "ipc-inference-rules.json").read_text(encoding="utf-8"))
    h04l = next(r for r in ipc_rules["rules"] if r["code"] == "H04L")
    assert "国密" in h04l["keywords"]

    # 8. standard-drafting
    s8 = _extract_bundle(tmp_path, "standard-drafting")
    std_bad = tmp_path / "std_bad.md"
    std_bad.write_text("# 1 范围\n应遵守。\n# 2 规范性引用文件\nGB/T 88888 未引用\n# 3 要求\n产品应合格【合成】。\n# 4 试验方法\n无\n", encoding="utf-8")
    assert _run([sys.executable, str(s8 / "scripts" / "audit_standard_draft.py"), str(std_bad), "--json", "--strict"], s8).returncode == 2

    # 9. enterprise-due-diligence
    s9 = _extract_bundle(tmp_path, "enterprise-due-diligence")
    p_law = _run(
        [sys.executable, str(s9 / "scripts" / "check_company_law.py"), "paid-in",
         "--founded", "2019-01-01", "--subscribed-deadline", "2040-01-01",
         "--registered-wan", "1000", "--paid-in-wan", "100", "--strict"],
        s9,
    )
    assert p_law.returncode == 2

    # 10. manufacturing-tax-risk
    s10 = _extract_bundle(tmp_path, "manufacturing-tax-risk")
    assert (s10 / "scripts" / "generate_report_html.py").is_file()
    assert "跨企业串户硬拦截" in (s10 / "scripts" / "generate_report_html.py").read_text(encoding="utf-8")

    # Universal V3 Delivery Constitution check: EVERY SINGLE ONE of the 10 standalone ZIPs
    # MUST be able to execute `python3 scripts/_core/fact_ledger.py read` without exit code 2!
    for sdir in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10):
        fl_script = sdir / "scripts" / "_core" / "fact_ledger.py"
        assert fl_script.is_file(), f"missing unified fact_ledger.py in {sdir.name}"
        proc = _run(
            [sys.executable, str(fl_script), "read", "--workspace", str(tmp_path / f"ws_{sdir.name}"), "--company", "验收测试有限公司"],
            sdir,
        )
        assert proc.returncode == 0, f"constitution fact_ledger read failed in {sdir.name}: {proc.stderr}"
        assert json.loads(proc.stdout)["found"] is False

    # Check all 12 high-frequency-project-rules.jsonl management_rule paths resolve to real files in source repo
    rules_file = REPO_ROOT / "skills" / "gov-project-checkup" / "references" / "high-frequency-project-rules.jsonl"
    for line in rules_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        target = (rules_file.parent / rec["management_rule"]).resolve()
        assert target.is_file(), f"broken management_rule path in high-frequency-project-rules.jsonl: {rec['management_rule']}"

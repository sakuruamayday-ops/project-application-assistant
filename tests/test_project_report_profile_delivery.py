import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import fitz
from docx import Document


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "skills/project-feasibility/scripts/validate_report_profile_delivery.py"
)
SPEC = importlib.util.spec_from_file_location("report_profile_validator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

SELECTOR_PATH = ROOT / "skills/project-feasibility/scripts/select_report_template.py"
SELECTOR_SPEC = importlib.util.spec_from_file_location("profile_test_selector", SELECTOR_PATH)
SELECTOR = importlib.util.module_from_spec(SELECTOR_SPEC)
assert SELECTOR_SPEC.loader is not None
SELECTOR_SPEC.loader.exec_module(SELECTOR)


def test_report_profile_requires_dual_format_sections_tables_and_branding(tmp_path):
    document = Document()
    document.add_heading("项目版本与窗口", level=1)
    document.add_heading("总体结论", level=1)
    target = tmp_path / "incomplete.docx"
    document.save(target)
    result = MODULE.validate_profile(
        plugin_root=ROOT,
        profile_id="project-feasibility-analysis-report",
        artifacts=[target],
    )
    assert result["status"] == "fail"
    assert "缺少要求格式:pdf" in result["errors"]
    assert any("缺少必备章节" in item for item in result["errors"])
    assert any("缺少必备表格" in item for item in result["errors"])
    assert any("品牌校验失败" in item for item in result["errors"])
    assert "缺少受控模板选型回执" in result["errors"]
    assert "缺少受控模板成稿回执" in result["errors"]


def test_stop_hook_rejects_tampered_profile_receipt(tmp_path):
    hook_path = Path(
        "/Users/zsh/Documents/自动化区域/workbuddy-v165-local-hotfix-20260813/"
        "candidate/skill-release-manager/scripts/workbuddy_behavior_hook.py"
    )
    spec = importlib.util.spec_from_file_location("hotfix_behavior", hook_path)
    hook = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(hook)
    artifact = tmp_path / "report.docx"
    artifact.write_bytes(b"initial")
    turn_id = "turn-profile-test"
    receipt_dir = tmp_path / "validator-receipts" / turn_id
    receipt_dir.mkdir(parents=True)
    receipt = {
        "validator_id": MODULE.VALIDATOR_ID,
        "status": "pass",
        "turn_id": turn_id,
        "profile_id": "project-feasibility-analysis-report",
        "artifacts": [
            {
                "path": str(artifact),
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        ],
    }
    (receipt_dir / "profile.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    assert len(hook.load_profile_validator_receipts(tmp_path, turn_id)) == 1
    artifact.write_bytes(b"tampered")
    assert hook.load_profile_validator_receipts(tmp_path, turn_id) == []


def test_pdf_section_matching_tolerates_glyph_fragmentation_but_not_missing_text():
    fragmented = "\u4e8c\u3001\u7533\n\u62a5\n\u6761\u4ef6\n\u5bf9\n\u7167"
    assert MODULE._compact_text("申报条件对照") in MODULE._compact_text(fragmented)
    assert MODULE._compact_text("科技咨询补强") not in MODULE._compact_text(fragmented)


def test_pdf_text_extraction_uses_visual_sort_order(monkeypatch, tmp_path):
    calls = []

    class Page:
        def get_text(self, mode, *, sort=False):
            calls.append((mode, sort))
            return "申报条件对照"

    class Pdf:
        def __iter__(self):
            return iter([Page()])

        def close(self):
            return None

    import fitz

    monkeypatch.setattr(fitz, "open", lambda _: Pdf())
    assert MODULE._pdf_text(tmp_path / "fixture.pdf") == "申报条件对照"
    assert calls == [("text", True)]


def test_template_provenance_binds_registry_master_and_completed_docx(tmp_path):
    selection = SELECTOR.resolve_template("高新技术企业认定", "前期评估")
    copied = SELECTOR.materialize(selection, tmp_path / "masters", enterprise="测试企业")
    master = Path(copied["output_path"])
    completed = tmp_path / "completed.docx"
    shutil.copy2(master, completed)
    completion = {
        "schema": "gongchuang-completed-project-report/v1",
        "status": "pass",
        "project_id": copied["project_id"],
        "report_type": copied["report_type"],
        "template_path": str(master),
        "template_sha256": MODULE.sha256_file(master),
        "output_path": str(completed),
        "output_sha256": MODULE.sha256_file(completed),
    }
    completion_path = completed.with_suffix(".completion.json")
    completion_path.write_text(json.dumps(completion, ensure_ascii=False), encoding="utf-8")
    errors, provenance = MODULE._validate_template_provenance(
        plugin_root=ROOT,
        profile_id="project-presale-assessment-report",
        docx=completed,
        template_selection_receipt=Path(copied["receipt_path"]),
        completion_receipt=completion_path,
    )
    assert errors == []
    assert provenance["project_id"] == "high-tech-enterprise"
    completed.write_bytes(completed.read_bytes() + b"tampered")
    errors, _ = MODULE._validate_template_provenance(
        plugin_root=ROOT,
        profile_id="project-presale-assessment-report",
        docx=completed,
        template_selection_receipt=Path(copied["receipt_path"]),
        completion_receipt=completion_path,
    )
    assert "成稿回执与当前DOCX哈希不一致" in errors


def test_pdf_portability_rejects_nonembedded_china_s_font(tmp_path):
    path = tmp_path / "manual-china-s.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "申报条件对照和总体结论", fontname="china-s", fontsize=12)
    document.save(path)
    document.close()
    errors, details = MODULE._validate_pdf_portability(path)
    assert details["rendered_page_count"] == 1
    assert any("中文字体未嵌入" in item for item in errors)


def test_cjk_font_support_rejects_embedded_latin_font_with_unicode_mapping():
    latin = (7, "ttf", "TrueType", "BAAAAA+LinuxLibertineG", "F1", "", 0)
    type1_latin = (8, "pfa", "Type1", "CAAAAA+FrankRuhlHofshi-Bold", "F2", "", 0)
    assert MODULE._font_record_supports_cjk(latin) is False
    assert MODULE._font_record_supports_cjk(type1_latin) is False


def test_cjk_font_support_accepts_wps_embedded_identity_h_fonts():
    hiragino = (16, "ttf", "Type0", "BFTHXX+HiraginoSansGB-W6", "FT16", "Identity-H", 0)
    subset = (22, "ttf", "Type0", "UGYAVD+CustomerSubsetFont", "FT22", "Identity-H", 0)
    assert MODULE._font_record_supports_cjk(hiragino) is True
    assert MODULE._font_record_supports_cjk(subset) is True

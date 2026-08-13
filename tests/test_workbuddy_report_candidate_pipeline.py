from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest
from docx import Document


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
REGISTRY = SKILLS / "project-feasibility/references/report-template-registry.json"
SELECTOR_PATH = SKILLS / "project-feasibility/scripts/select_report_template.py"
FILLER_PATH = SKILLS / "project-feasibility/scripts/fill_report_template.py"
PIPELINE_PATH = ROOT / "scripts/run_workbuddy_report_candidate_pipeline.py"
VISUAL_FINALIZER_PATH = ROOT / "scripts/record_workbuddy_report_visual_review.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTOR = load_module("candidate_test_selector", SELECTOR_PATH)
FILLER = load_module("candidate_test_filler", FILLER_PATH)
PIPELINE = load_module("candidate_test_pipeline", PIPELINE_PATH)
VISUAL_FINALIZER = load_module("candidate_test_visual_finalizer", VISUAL_FINALIZER_PATH)


def client_source(path: Path, *, name: str = "某高端装备有限公司") -> Path:
    document = Document()
    document.add_heading("企业项目材料", level=1)
    document.add_paragraph(f"企业名称：{name}")
    document.add_paragraph("申报对象：工程机械智能控制系统")
    document.add_paragraph("已形成自主研发、版本测试和客户应用资料。")
    document.save(path)
    return path


def case_fixture(source: Path, project_id: str = "first-equipment") -> dict:
    return {
        "project_id": project_id,
        "enterprise": "某高端装备有限公司",
        "project_object": "工程机械智能控制系统",
        "suggested_year": "2027年",
        "deadline": "待当年通知",
        "conclusion": "培育后申报",
        "conclusion_basis": "已有产品和研发材料，检测、查新和首次应用证据待补齐。",
        "primary_gap": "性能验证与首次应用证据尚未闭合",
        "next_action": "锁定产品版本，完成第三方测试、查新和客户验收台账。",
        "materials": [
            {
                "path": str(source),
                "role": "企业技术材料",
                "anchors": ["某高端装备有限公司", "工程机械智能控制系统"],
            }
        ],
        "policies": [
            {
                "title": "当期项目申报通知待发布",
                "locator": "规划参考，待当年官方通知",
                "status": "规划基线",
            }
        ],
        "conditions": [
            {
                "match": "核心技术拥有自主知识产权",
                "value": "当前材料已列明自主研发，权利清单待核",
                "state": "企业提供待核",
                "gap": "权利状态与产品映射未闭合",
                "action": "建立知识产权与产品技术对应表",
            }
        ],
    }


@pytest.mark.parametrize("report_type", ["preassessment", "feasibility"])
def test_real_source_anchor_fill_produces_complete_editable_report(tmp_path: Path, report_type: str):
    source = client_source(tmp_path / "client.docx")
    selection = SELECTOR.resolve_template("first-equipment", report_type, registry_path=REGISTRY)
    copied = SELECTOR.materialize(selection, tmp_path / "masters", enterprise="某高端装备有限公司")
    output = tmp_path / f"completed-{report_type}.docx"
    result = FILLER.complete_report(
        template_path=Path(copied["output_path"]),
        output_path=output,
        fixture=case_fixture(source),
        report_type=report_type,
        release_tag="V1.6.5.2",
        public_root=ROOT,
    )
    assert result["status"] == "pass"
    assert result["source_count"] == 1
    document = Document(output)
    text = "\n".join(
        [paragraph.text for paragraph in document.paragraphs]
        + [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    )
    assert "［填写" not in text
    assert "培训模板" not in text
    assert "某高端装备有限公司" in text
    assert "资料来源与证据状态" in text
    visible_runs = [
        run
        for paragraph in list(document.paragraphs)
        + [p for table in document.tables for row in table.rows for cell in row.cells for p in cell.paragraphs]
        for run in paragraph.runs
        if run.text.strip()
    ]
    assert visible_runs
    assert all(run.font.name == FILLER.PORTABLE_CJK_FONT for run in visible_runs)


def test_source_anchor_must_match_real_material(tmp_path: Path):
    source = client_source(tmp_path / "client.docx")
    fixture = case_fixture(source)
    fixture["materials"][0]["anchors"] = ["原文完全不包含的假断言"]
    with pytest.raises(ValueError, match="原文锚点未命中"):
        FILLER.validate_case_fixture(fixture, public_root=ROOT)


def test_private_customer_material_is_rejected_inside_public_skill_tree(tmp_path: Path):
    source = client_source(tmp_path / "_private-client-fixture.docx")
    with pytest.raises(ValueError, match="不得放入公共技能树"):
        FILLER.validate_case_fixture(case_fixture(source), public_root=tmp_path)


def test_fixture_manifest_requires_exact_twelve_project_order(tmp_path: Path):
    cases = [{"project_id": project_id} for project_id in PIPELINE.PROJECT_IDS]
    manifest = tmp_path / "fixtures.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "gongchuang-private-real-client-report-fixtures/v1",
                "release_tag": "V1.6.5.2",
                "cases": cases,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert [item["project_id"] for item in PIPELINE.load_fixture_manifest(manifest, release_tag="V1.6.5.2")] == list(
        PIPELINE.PROJECT_IDS
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["cases"] = list(reversed(payload["cases"]))
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="12类受控项目顺序"):
        PIPELINE.load_fixture_manifest(manifest, release_tag="V1.6.5.2")


def test_zip_privacy_scan_blocks_customer_name_and_path(tmp_path: Path):
    source = client_source(tmp_path / "client.docx")
    fixture = case_fixture(source)
    clean = tmp_path / "clean.zip"
    with zipfile.ZipFile(clean, "w") as archive:
        archive.writestr("skills/example/SKILL.md", "---\nname: example\n---\n")
    assert PIPELINE.scan_archive_privacy(clean, [fixture])["status"] == "pass"
    dirty = tmp_path / "dirty.zip"
    with zipfile.ZipFile(dirty, "w") as archive:
        archive.writestr("leak.txt", fixture["enterprise"])
    with pytest.raises(RuntimeError, match="混入真实客户信息"):
        PIPELINE.scan_archive_privacy(dirty, [fixture])
    dirty_name = tmp_path / "dirty-name.zip"
    with zipfile.ZipFile(dirty_name, "w") as archive:
        archive.writestr(f"skills/{fixture['enterprise']}/SKILL.md", "clean body")
    with pytest.raises(RuntimeError, match="混入真实客户信息"):
        PIPELINE.scan_archive_privacy(dirty_name, [fixture])


def test_candidate_pipeline_source_excludes_generic_and_zcode_packaging():
    text = PIPELINE_PATH.read_text(encoding="utf-8").casefold()
    assert "package_workbuddy_suite.py" in text
    assert "package_skill_suite.py" not in text
    assert "run_release_gates" in text
    assert "run_post_package_gates" in text
    assert "installed_filler" in text
    assert "zcode" in text
    assert "not-built-not-tested" in text
    assert PIPELINE.PLATFORMS == ("macos", "windows")


def test_safe_extract_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "bad")
    with pytest.raises(RuntimeError, match="不安全条目"):
        PIPELINE.safe_extract_zip(archive, tmp_path / "out")


def visual_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    sheet = tmp_path / "contact.png"
    sheet.write_bytes(b"contact-sheet")
    digest = PIPELINE.sha256_file(sheet)
    receipt = tmp_path / "pipeline.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "gongchuang-workbuddy-report-candidate-pipeline/v1",
                "status": "pending",
                "automated_gate_status": "pass",
                "candidate_state": "pending-visual-review",
                "release_tag": "V1.6.5.2",
                "source_commit": "abc123",
                "contact_sheet": {"path": str(sheet), "sha256": digest, "sample_count": 24},
                "real_host_acceptance": {"macos": "pending", "windows": "pending"},
                "zcode": {"status": "not-built-not-tested"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    checklist = tmp_path / "checklist.json"
    checklist.write_text(
        json.dumps(
            {
                "schema": "gongchuang-report-visual-review/v1",
                "release_tag": "V1.6.5.2",
                "contact_sheet_sha256": digest,
                "reviewer": "test-reviewer",
                "review_method": "test-visual-review",
                "reviewed_at": "2026-08-13T21:00:00+08:00",
                "items": [
                    {
                        "project_id": project_id,
                        "report_type": report_type,
                        "status": "pass",
                        "checks": {name: True for name in VISUAL_FINALIZER.REQUIRED_CHECKS},
                    }
                    for project_id in PIPELINE.PROJECT_IDS
                    for report_type in PIPELINE.REPORT_TYPES
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return receipt, checklist, tmp_path / "visual-receipt.json"


def test_visual_finalizer_requires_exact_24_passed_samples(tmp_path: Path):
    receipt, checklist, output = visual_fixture(tmp_path)
    result = VISUAL_FINALIZER.finalize_visual_review(
        repo_root=ROOT,
        pipeline_receipt=receipt,
        checklist_path=checklist,
        output_path=output,
    )
    assert result["status"] == "pass"
    assert result["candidate_state"] == "ready-for-real-host-testing"
    assert result["formal_release_eligible"] is False
    payload = json.loads(checklist.read_text(encoding="utf-8"))
    payload["items"][0]["checks"]["no_missing_glyphs"] = False
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="视觉抽检未通过"):
        VISUAL_FINALIZER.finalize_visual_review(
            repo_root=ROOT,
            pipeline_receipt=receipt,
            checklist_path=bad,
            output_path=tmp_path / "bad-receipt.json",
        )

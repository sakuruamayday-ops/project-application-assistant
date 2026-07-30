import importlib.util
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "skills" / "jiaotang-patent-router"
CHECKER = ROOT / "skills" / "checking-patdocx-cn-single-agent"
CASE_FIXTURE = ROOT / "tests" / "fixtures" / "patent-case-delivery"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_core_patent_skill_count_and_internal_components():
    manifest = json.loads((ROOT / "skills/suite-manifest.json").read_text(encoding="utf-8"))
    public_patent_entries = {
        name
        for name in manifest["skills"]
        if name in {"jiaotang-patent-router", "checking-patdocx-cn-single-agent"}
        or name.startswith("patent-")
    }
    assert public_patent_entries == {
        "jiaotang-patent-router",
        "checking-patdocx-cn-single-agent",
    }
    for method in (
        "p1-search-analysis.md",
        "p2-mining-disclosure.md",
        "p3-preexam.md",
    ):
        assert (ROUTER / "references" / method).is_file()
    assert not (ROUTER / "components").exists()


def test_claim_structure_marks_nested_alternatives_and_markush_for_review():
    module = load_module(ROUTER / "scripts" / "claim_structure.py")
    claim = (
        "1. 一种组合物，其包含聚合物A，以及选自助剂B、助剂C或助剂D中的至少一种；"
        "其中R1和R2各自独立地选自氢、C1-C6烷基或芳基。"
    )
    result = module.analyze_feature("C1-F1", claim)
    serialized = json.dumps(result, ensure_ascii=False)
    assert "markush" in serialized.lower() or "马库什" in serialized
    assert result["requires_boundary_review"] is True


def test_claim_chart_requires_traceable_prior_art_locators(tmp_path: Path):
    source = tmp_path / "chain.json"
    prior_art = tmp_path / "prior-art.json"
    target = tmp_path / "chart.json"
    source.write_text(
        json.dumps(
            {
                "cutoff_date": "2026-07-27",
                "source_document": {"sha256": "0" * 64},
                "ipc_candidates": [],
                "independent_claim_feature_tree": [
                    {
                        "claim_number": 1,
                        "protection_object": "material",
                        "necessary_technical_features": [
                            {
                                "feature_id": "C1-F1",
                                "text": "阻隔层包含聚酯",
                                "structure": {},
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    prior_art.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "D1",
                        "publication_number": "CN100000001A",
                        "text": "[0032] 阻隔层包含聚酯。",
                        "feature_mappings": [
                            {
                                "feature_id": "C1-F1",
                                "status": "disclosed",
                                "source_locators": [],
                                "evidence": [],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            sys.executable,
            str(ROUTER / "scripts" / "build_claim_prior_art_matrix.py"),
            "--evidence-chain",
            str(source),
            "--prior-art",
            str(prior_art),
            "--out-json",
            str(target),
        ],
        check=True,
    )
    result = json.loads(target.read_text(encoding="utf-8"))
    assert "MAPPING_INCOMPLETE" in json.dumps(result, ensure_ascii=False)


def test_checker_extracts_extended_docx_objects_contract():
    source = (CHECKER / "scripts" / "patent_extractor.py").read_text(encoding="utf-8")
    for field in ("footnotes", "endnotes", "equations", "embedded_objects"):
        assert field in source


def test_comment_anchor_splits_cross_run_text_exactly():
    module = load_module(CHECKER / "scripts" / "review_adder.py")
    paragraph = ET.Element(module.qname(module.W, "p"))
    for value in ("前缀", "目标", "文本", "后缀"):
        run = ET.SubElement(paragraph, module.qname(module.W, "r"))
        ET.SubElement(run, module.qname(module.W, "t")).text = value
    precision = module.add_markers(paragraph, "0", "目标文本", 1)
    assert precision == "exact"
    tags = [child.tag.rsplit("}", 1)[-1] for child in paragraph]
    assert tags.index("commentRangeStart") < tags.index("commentRangeEnd")
    assert module.paragraph_text(paragraph) == "前缀目标文本后缀"


def test_no_unfused_patent_skill_names_remain():
    checked = [
        ROUTER / "SKILL.md",
        CHECKER / "SKILL.md",
        ROOT / "docs/provenance/patent-skills.md",
    ]
    forbidden = (
        "SkillHub",
        "formal-suite-v1.2",
        "patent-mining-disclosure-skill",
        "patent-preliminary-examination-check",
        "patent-lawyer-agent",
    )
    content = "\n".join(path.read_text(encoding="utf-8") for path in checked)
    assert all(value not in content for value in forbidden)


def run_manifest(case_dir: Path, *arguments: str, check: bool = True):
    return subprocess.run(
        [
            sys.executable,
            str(ROUTER / "scripts" / "patent_case_manifest.py"),
            *arguments,
            "--case-dir",
            str(case_dir),
        ],
        check=check,
        text=True,
        capture_output=True,
    )


def register(case_dir: Path, role: str, filename: str):
    return run_manifest(
        case_dir,
        "register",
        "--role",
        role,
        "--path",
        filename,
    )


def build_complete_fixture(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    shutil.copytree(CASE_FIXTURE, case_dir)
    run_manifest(
        case_dir,
        "init",
        "--case-id",
        "fixture-case",
        "--fixture",
    )
    for role, filename in (
        ("task_header", "task-header.json"),
        ("technical_disclosure", "technical-disclosure.md"),
        ("search_plan", "search-plan.json"),
        ("prior_art_evidence", "prior-art.json"),
    ):
        register(case_dir, role, filename)

    subprocess.run(
        [
            sys.executable,
            str(ROUTER / "scripts" / "build_patent_application.py"),
            "--input",
            str(case_dir / "application-input.json"),
            "--output",
            str(case_dir / "application.docx"),
            "--drawing-spec",
            str(case_dir / "drawing-spec.json"),
            "--audit-json",
            str(case_dir / "application-audit.json"),
            "--case-dir",
            str(case_dir),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    for role, filename in (
        ("claim_prior_art_matrix", "claim-matrix.json"),
        ("review_record", "review.json"),
        ("review_verification", "verification.json"),
        ("preexam_recommendation", "preexam.json"),
    ):
        register(case_dir, role, filename)
    run_manifest(case_dir, "checklist", "--out", "submission-checklist.md")
    return case_dir


def test_full_case_fixture_passes_one_manifest_and_generator_contract(tmp_path: Path):
    case_dir = build_complete_fixture(tmp_path)
    result = run_manifest(
        case_dir,
        "validate",
        "--milestone",
        "fixture",
    )
    audit = json.loads(result.stdout)
    assert audit["completion_allowed"] is True

    manifest = json.loads(
        (case_dir / "patent-case-manifest.json").read_text(encoding="utf-8")
    )
    assert set(manifest["artifacts"]) == {
        "task_header",
        "technical_disclosure",
        "search_plan",
        "prior_art_evidence",
        "patent_application_input",
        "patent_application_docx",
        "drawing_spec",
        "claim_prior_art_matrix",
        "review_record",
        "review_verification",
        "preexam_recommendation",
        "submission_checklist",
    }
    assert all(
        len(artifact["sha256"]) == 64
        for artifact in manifest["artifacts"].values()
    )
    with zipfile.ZipFile(case_dir / "application.docx") as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    for heading in ("摘要", "权利要求书", "说明书", "具体实施方式"):
        assert heading in xml

    extracted = case_dir / "extracted.json"
    subprocess.run(
        [
            sys.executable,
            str(CHECKER / "scripts" / "patent_extractor.py"),
            str(case_dir / "application.docx"),
            "--output-json",
            str(extracted),
            "--extract-only",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert extracted.is_file()


def test_fixture_cannot_be_misrepresented_as_filing_ready(tmp_path: Path):
    case_dir = build_complete_fixture(tmp_path)
    result = run_manifest(
        case_dir,
        "validate",
        "--milestone",
        "filing-ready",
        check=False,
    )
    assert result.returncode == 1
    audit = json.loads(result.stdout)
    assert "FIXTURE_NOT_FILING_READY" in {
        item["code"] for item in audit["errors"]
    }


def test_changed_upstream_file_invalidates_downstream_case_files(tmp_path: Path):
    case_dir = build_complete_fixture(tmp_path)
    disclosure = case_dir / "technical-disclosure.md"
    disclosure.write_text(
        disclosure.read_text(encoding="utf-8") + "\n\n版本变更。\n",
        encoding="utf-8",
    )
    register(case_dir, "technical_disclosure", "technical-disclosure.md")
    result = run_manifest(
        case_dir,
        "validate",
        "--milestone",
        "fixture",
        check=False,
    )
    assert result.returncode == 1
    audit = json.loads(result.stdout)
    stale_roles = {
        item["role"]
        for item in audit["errors"]
        if item["code"] == "STALE_DEPENDENCY"
    }
    assert "search_plan" in stale_roles
    assert all(item["repair_task"] for item in audit["errors"])


def test_case_revision_change_blocks_every_old_stage_file(tmp_path: Path):
    case_dir = build_complete_fixture(tmp_path)
    run_manifest(
        case_dir,
        "revise",
        "--reason",
        "事实底稿发生实质变更",
    )
    result = run_manifest(
        case_dir,
        "validate",
        "--milestone",
        "fixture",
        check=False,
    )
    audit = json.loads(result.stdout)
    wrong_revision_roles = {
        item["role"]
        for item in audit["errors"]
        if item["code"] == "WRONG_CASE_REVISION"
    }
    assert wrong_revision_roles == {
        "task_header",
        "technical_disclosure",
        "search_plan",
        "prior_art_evidence",
        "patent_application_input",
        "patent_application_docx",
        "drawing_spec",
        "claim_prior_art_matrix",
        "review_record",
        "review_verification",
        "preexam_recommendation",
        "submission_checklist",
    }


def test_generator_refuses_unconfirmed_fact_lock(tmp_path: Path):
    payload = json.loads(
        (CASE_FIXTURE / "application-input.json").read_text(encoding="utf-8")
    )
    payload["anonymized_test_fixture"] = False
    payload["fact_lock"]["status"] = "pending"
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROUTER / "scripts" / "build_patent_application.py"),
            "--input",
            str(input_path),
            "--output",
            str(tmp_path / "application.docx"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "事实锁未确认为confirmed" in result.stdout


def test_fixture_contains_no_archived_case_technology_or_real_patent_number():
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in CASE_FIXTURE.rglob("*")
        if path.is_file()
    )
    assert "政策版本图" not in content
    assert "企业项目检索推荐" not in content
    assert not re.search(r"CN\d{7,}[A-Z]\d?", content)

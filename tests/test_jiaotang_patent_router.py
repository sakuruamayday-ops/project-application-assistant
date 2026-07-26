import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "skills" / "jiaotang-patent-router"
CHECKER = ROOT / "skills" / "checking-patdocx-cn-single-agent"


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
    for component in (
        "patent-lawyer-agent",
        "patent-mining-disclosure-skill",
        "patent-preliminary-examination-check",
    ):
        assert (ROUTER / "components" / component / "METHOD.md").is_file()


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

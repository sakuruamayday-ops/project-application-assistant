import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "skills" / "evidence-ledger" / "scripts" / "grounded_evidence.py"
FIXTURE = ROOT / "tests" / "fixtures" / "grounded-citations" / "standard-ledger.json"
SPEC = importlib.util.spec_from_file_location("grounded_profiles", ENGINE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_registry_covers_entire_suite_and_standard_uses_native_profile():
    manifest = load(ROOT / "skills" / "suite-manifest.json")
    registry = load(ROOT / "skills" / "report-skill-registry.json")
    config = load(ROOT / "config" / "grounded-citations.json")
    registered = {item["skill"] for item in registry["skills"]}
    assert registered == set(manifest["skills"])
    standard = next(item for item in registry["skills"] if item["skill"] == "standard-drafting")
    assert standard == {
        "skill": "standard-drafting",
        "profile": "standard-native",
        "uses_grounded_engine": True,
    }
    assert registry["artifact_validation"] == config["artifact_validation"]
    assert registry["artifact_validation"]["pdf"]["fail_closed"] is True
    assert registry["artifact_validation"]["docx"]["renderer_missing_cjk_is"] == "pending-device-acceptance"


def test_generated_registry_and_call_graph_are_current():
    result = subprocess.run(
        [sys.executable, "scripts/generate_grounded_registry.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    graph = load(ROOT / "skills" / "skill-call-graph.json")
    assert any(
        item["from"] == "standard-drafting"
        and item["to"] == "evidence-ledger"
        and item["type"] == "requires"
        for item in graph["relations"]
    )


def test_standard_body_preserves_normative_references_and_uses_separate_source_memo():
    bundle = MODULE.render_profile_bundle(load(FIXTURE), profile="standard-native", artifact="docx")
    assert bundle["source_placement"] == "separate-source-memo"
    assert "### 规范性引用文件" in bundle["primary"]
    assert "GB/T 1.1—2020" in bundle["primary"]
    assert "数据来源" not in bundle["primary"]
    assert "[1]" not in bundle["primary"]
    assert len(bundle["sidecars"]) == 1
    memo = bundle["sidecars"][0]["content"]
    assert memo.startswith("# 标准数据来源说明")
    assert "https://example.gov.cn/standard/drafting-rule" in memo
    assert "产品试验数据.xlsx" in memo
    assert "knowledge/internal" not in memo


def test_analysis_report_and_native_artifacts_keep_distinct_layout_contracts():
    payload = load(ROOT / "skills" / "evidence-ledger" / "examples" / "normal-grounded-report.json")
    report = MODULE.render_profile_bundle(payload, profile="analysis-report", artifact="pdf")
    workbook = MODULE.render_profile_bundle(payload, profile="analysis-report", artifact="xlsx")
    slides = MODULE.render_profile_bundle(payload, profile="analysis-report", artifact="pptx")
    assert report["source_placement"] == "end-section"
    assert report["primary"].rfind("## 数据来源") > report["primary"].find("### 结论")
    assert workbook["profile"] == "spreadsheet-native"
    assert workbook["source_placement"] == "final-worksheet"
    assert slides["profile"] == "presentation-native"
    assert slides["source_placement"] == "final-slide"


def test_codex_and_workbuddy_adapters_return_identical_contract_bytes():
    outputs = []
    for host in ("codex", "workbuddy"):
        adapter = ROOT / "skills" / "_runtime" / "grounded-citations" / f"{host}_adapter.py"
        result = subprocess.run(
            [
                sys.executable,
                str(adapter),
                "render-profile",
                str(FIXTURE),
                "--profile",
                "standard-native",
                "--artifact",
                "docx",
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONHASHSEED": "0"},
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    assert hashlib.sha256(outputs[0]).hexdigest()


def test_standard_profile_refuses_report_source_heading_in_primary_blocks():
    payload = load(FIXTURE)
    payload["document"]["blocks"][0]["heading"] = "数据来源"
    try:
        MODULE.render_profile_bundle(payload, profile="standard-native", artifact="docx")
    except ValueError as exc:
        assert "禁止章节" in str(exc)
    else:
        raise AssertionError("standard-native must reject report-style source headings")

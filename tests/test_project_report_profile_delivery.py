import hashlib
import importlib.util
import json
from pathlib import Path

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

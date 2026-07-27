from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from docx import Document


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "high-tech-enterprise-application-drafting"
SCRIPT = SKILL_ROOT / "scripts" / "expand_rd_ps_tables.py"
TEMPLATE = SKILL_ROOT / "assets" / "高新技术企业认定申请书空白模板.docx"
SPEC = importlib.util.spec_from_file_location("expand_rd_ps_tables", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_rd_tables_expand_and_empty_tail_trim() -> None:
    document = Document(TEMPLATE)
    expansion = MODULE.resize_kind(document, "rd", 20, "RD")
    assert expansion["operation"] == "expand"
    assert expansion["before"] == 1
    assert expansion["after"] == 20
    assert expansion["renumbered_continuously"] is True

    trimming = MODULE.resize_kind(
        document,
        "rd",
        13,
        "RD",
        trim_empty_tail=True,
    )
    assert trimming["operation"] == "trim"
    assert trimming["before"] == 20
    assert trimming["after"] == 13
    assert [item["code"] for item in trimming["removed"]] == [
        "RD14",
        "RD15",
        "RD16",
        "RD17",
        "RD18",
        "RD19",
        "RD20",
    ]
    assert trimming["renumbered_continuously"] is True


def test_trim_blocks_when_trailing_table_contains_content() -> None:
    document = Document(TEMPLATE)
    MODULE.resize_kind(document, "rd", 3, "RD")
    units = MODULE.collect_units(document, "rd")
    assert len(units) == 3
    units[-1][1].rows[0].cells[-1].text = "已填写项目名称"

    with pytest.raises(ValueError, match="缩表已阻断"):
        MODULE.resize_kind(
            document,
            "rd",
            2,
            "RD",
            trim_empty_tail=True,
        )

    assert len(MODULE.collect_units(document, "rd")) == 3


def test_cli_trim_generates_default_audit_report(tmp_path: Path) -> None:
    expanded = tmp_path / "expanded.docx"
    output = tmp_path / "trimmed.docx"
    expansion = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(TEMPLATE),
            str(expanded),
            "--rd-count",
            "18",
            "--ps-count",
            "3",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert expansion.returncode == 0, expansion.stderr
    process = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(expanded),
            str(output),
            "--rd-count",
            "17",
            "--ps-count",
            "2",
            "--trim-empty-tail",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    audit = output.with_suffix(output.suffix + ".audit.json")
    assert output.is_file()
    assert audit.is_file()
    report = json.loads(audit.read_text(encoding="utf-8"))
    assert report["trim_empty_tail_authorized"] is True
    assert report["rd"]["after"] == 17
    assert report["ps"]["after"] == 2

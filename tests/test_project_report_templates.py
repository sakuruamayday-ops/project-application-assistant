from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/project-feasibility"
REGISTRY = SKILL / "references/report-template-registry.json"
SELECTOR = SKILL / "scripts/select_report_template.py"
CONTRACT = ROOT / "skills/delivery-contracts.json"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

SPEC = importlib.util.spec_from_file_location("project_report_template_selector", SELECTOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def docx_text_and_tables(path: Path) -> tuple[str, list[list[str]]]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        settings = ET.fromstring(archive.read("word/settings.xml"))
    assert settings.find(f".//{{{WORD_NS}}}documentProtection") is None
    paragraphs = [
        "".join(node.text or "" for node in paragraph.findall(f".//{{{WORD_NS}}}t"))
        for paragraph in root.findall(f".//{{{WORD_NS}}}p")
    ]
    tables: list[list[str]] = []
    for table in root.findall(f".//{{{WORD_NS}}}tbl"):
        rows = []
        for row in table.findall(f"./{{{WORD_NS}}}tr"):
            cells = [
                "".join(node.text or "" for node in cell.findall(f".//{{{WORD_NS}}}t"))
                for cell in row.findall(f"./{{{WORD_NS}}}tc")
            ]
            rows.append(" | ".join(cells))
        tables.append(rows)
    return "\n".join(paragraphs + [line for table in tables for line in table]), tables


def test_registry_has_twelve_projects_and_twenty_four_verified_editable_masters():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert registry["release_tag"] == "V1.6.9"
    assert len(registry["projects"]) == 12
    assert set(registry["report_types"]) == {"preassessment", "feasibility"}
    seen = set()
    for project in registry["projects"]:
        assert project["id"] not in seen
        seen.add(project["id"])
        assert project["core_object"].strip()
        for report_type, profile_id in (
            ("preassessment", "project-presale-assessment-report"),
            ("feasibility", "project-feasibility-analysis-report"),
        ):
            template = project["templates"][report_type]
            path = SKILL / template["path"]
            assert path.is_file()
            assert MODULE.sha256_file(path) == template["sha256"]
            text, tables = docx_text_and_tables(path)
            profile = contract["delivery_profiles"][profile_id]
            for section in profile["required_sections"]:
                assert section in text, (project["id"], report_type, section)
            for requirement in profile["required_tables"]:
                headers = requirement["required_columns"]
                matching = [
                    table for table in tables if table and all(item in table[0] for item in headers)
                ]
                assert matching, (project["id"], report_type, requirement["id"])
                assert len(matching[0]) - 1 >= requirement["min_rows"]


def test_alias_routing_prefers_specific_project_and_report_type():
    cases = {
        "高企前期评估": ("high-tech-enterprise", "preassessment"),
        "专精特新小巨人可行性分析报告": ("little-giant", "feasibility"),
        "省级专精特新A版": ("specialized-sme", "preassessment"),
        "首台套产品B版": ("first-equipment", "feasibility"),
        "新材料首批次前期评估": ("first-material", "preassessment"),
        "软件首版次可行性分析": ("first-software", "feasibility"),
        "研发中心前期评估": ("enterprise-rd-center", "preassessment"),
        "浙江制造精品可行性分析": ("manufacturing-excellence", "feasibility"),
        "省级单项冠军前期评估": ("single-champion", "preassessment"),
        "国家级绿色工厂可行性分析": ("green-factory", "feasibility"),
        "智能工厂前期评估": ("digitalization", "preassessment"),
        "尖兵领雁可行性分析": ("science-plan", "feasibility"),
    }
    for query, expected in cases.items():
        project_query = query.replace("前期评估", "").replace("可行性分析报告", "").replace("可行性分析", "").replace("A版", "").replace("B版", "")
        report_query = "preassessment" if expected[1] == "preassessment" else "feasibility"
        result = MODULE.resolve_template(project_query, report_query)
        assert (result["project_id"], result["report_type"]) == expected


def test_materialize_copies_master_and_writes_provenance_without_overwrite(tmp_path):
    selection = MODULE.resolve_template("小巨人", "项目前期评估报告")
    result = MODULE.materialize(selection, tmp_path, enterprise="测试企业")
    output = Path(result["output_path"])
    receipt = Path(result["receipt_path"])
    assert output.is_file() and receipt.is_file()
    assert result["editable"] is True
    assert MODULE.sha256_file(output) == selection["template_sha256"]
    try:
        MODULE.materialize(selection, tmp_path, enterprise="测试企业")
    except FileExistsError:
        pass
    else:
        raise AssertionError("应拒绝覆盖现有报告")


def test_unknown_project_fails_closed():
    try:
        MODULE.resolve_template("未登记的项目", "前期评估")
    except ValueError as exc:
        assert "未命中" in str(exc)
    else:
        raise AssertionError("未知项目不得默认套用模板")

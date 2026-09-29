import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/project-feasibility/scripts"
spec = importlib.util.spec_from_file_location("sme_action_report", SCRIPTS / "sme_action_report.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    return {
        "enterprise": "合成测试企业", "project_id": "specialized-sme",
        "report_date": "2026-09-28", "suggested_year": "2027",
        "report_sections": {
            key: {"paragraphs": [f"{key}的实际说明"], "rows": [[f"{key}-{i}" for i in range(len(headers))]] if headers else []}
            for key, _, headers in module.SECTIONS
        },
    }


def build(data):
    return module.build_action_document(
        ROOT / "skills/project-feasibility/assets/report-templates/specialized-sme/preassessment.docx", data
    )


def tasks(doc):
    return next(t for t in doc.tables if t.rows[0].cells[0].text == "补强动作")


@pytest.mark.parametrize("assets,expected", [(None, []), ("0", []),
    ("5999999.99", []), ("6000000", ["研发档A"]),
    ("10000000", ["研发档A", "研发档B"])])
def test_research_equipment_half_assets_boundary(assets, expected):
    tiers = [{"name": "研发档B", "equipment_threshold_yuan": "5000000", "source": "合成政策B"},
             {"name": "研发档A", "equipment_threshold_yuan": "3000000", "source": "合成政策A"}]
    assert module.screen_research_equipment(assets, tiers)["recommended"] == expected


@pytest.mark.parametrize("assets", ["-1", "NaN", "Infinity", "错误"])
def test_research_equipment_rejects_invalid_amounts(assets):
    with pytest.raises(ValueError, match="非负有限数"):
        module.screen_research_equipment(assets, [])


def test_research_screen_reaches_renderer_without_leaking_estimate():
    data = fixture()
    data["research_equipment_screen"] = {
        "fixed_assets_yuan": "6000000", "existing_basis": "已有研发团队及产品",
        "tiers": [{"name": "合成研发中心", "equipment_threshold_yuan": "3000000", "source": "测试政策"}],
    }
    before = copy.deepcopy(data)
    doc = build(data)
    text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "建议申报方向：合成研发中心" in text
    assert "6000000" not in text and "3000000" not in text and "50%" not in text
    assert data == before
    assert [c.text for c in tasks(doc).rows[1].cells] == data["report_sections"]["tasks"]["rows"][0]


def test_research_screen_never_uses_total_assets():
    data = fixture()
    data["research_equipment_screen"] = {
        "total_assets_yuan": "100000000", "existing_basis": "已有研发团队及产品",
        "tiers": [{"name": "合成研发中心", "equipment_threshold_yuan": "3000000", "source": "测试政策"}],
    }
    rows = module.prepare_sections(data)["next_tasks"]["rows"]
    assert rows[-1][1] == "优先培育"
    assert "合成研发中心" not in rows[-1][-1]


@pytest.mark.parametrize("project", ["specialized-sme", "little-giant"])
def test_fixed_structure_and_preserved_tasks(project):
    data = fixture()
    data["project_id"] = project
    doc = build(data)
    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert headings == [heading for heading, _ in module.GROUPS]
    assert [c.text for c in tasks(doc).rows[1].cells] == data["report_sections"]["tasks"]["rows"][0]
    assert "5.1 补强任务表" in [p.text for p in doc.paragraphs]


def test_edit_one_section_does_not_reset_other_content():
    before = fixture()
    after = copy.deepcopy(before)
    after["report_sections"]["product"]["paragraphs"] = ["用户修改后的产品说明"]
    doc = build(after)
    assert "用户修改后的产品说明" in [p.text for p in doc.paragraphs]
    assert [c.text for c in tasks(doc).rows[1].cells] == before["report_sections"]["tasks"]["rows"][0]
    assert doc.settings.element.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}documentProtection") is None


def test_missing_product_has_explanation_not_empty_template_rows():
    data = fixture()
    data["report_sections"]["product"] = {"paragraphs": ["未提供产品清单，先核实际销售对象。"], "rows": []}
    assert "未提供产品清单，先核实际销售对象。" in [p.text for p in build(data).paragraphs]


@pytest.mark.parametrize("mutation", ["wrong-project", "missing-section", "wrong-columns", "empty-tasks"])
def test_invalid_input_has_direct_error(mutation):
    data = fixture()
    if mutation == "wrong-project":
        data["project_id"] = "high-tech-enterprise"
    elif mutation == "missing-section":
        del data["report_sections"]["finance"]
    elif mutation == "wrong-columns":
        data["report_sections"]["tasks"]["rows"] = [["x"]]
    else:
        data["report_sections"]["tasks"]["rows"] = []
    with pytest.raises(ValueError):
        build(data)


def test_runtime_manifest_includes_renderer_dependency():
    import json
    operations = json.loads((ROOT / "skills/client-runtime-operations.json").read_text())["operations"]
    operation = next(o for o in operations if o["id"] == "project-feasibility.generate-report")
    assert "project-feasibility/scripts/sme_action_report.py" in operation["files"]


@pytest.mark.parametrize("project", ["specialized-sme", "little-giant"])
def test_scores_and_unavailable_score_explanations_not_exported(project):
    data = fixture()
    data["project_id"] = project
    data["report_sections"]["conclusion"]["paragraphs"] = ["研发基础保留。分数由系统自动评，获取不到。"]
    data["report_sections"]["acceptance"]["rows"].append(
        ["发展质量", "当年平台得分≥60分", "当前平台分未取得", "明年模拟填报"]
    )
    doc = build(data)
    text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])
    assert "研发基础保留。" in text
    assert not module.SCORE_TEXT.search(text)
    assert "获取不到" not in text
    assert data["report_sections"]["acceptance"]["rows"][-1][0] == "发展质量"


def test_all_reference_content_blocks_exist_in_order():
    doc = build(fixture())
    expected = [heading for _, heading, _ in module.SECTIONS if heading]
    assert [p.text for p in doc.paragraphs if p.style.name == "Heading 2"] == expected


def test_action_values_and_peer_comparison_columns():
    doc = build(fixture())
    assert [c.text for c in tasks(doc).rows[0].cells] == ["补强动作", "补强价值", "建议节点"]
    peer = next(t for t in doc.tables if t.cell(0, 0).text == "对标企业或产品体系")
    assert len(peer.columns) == 4
    assert peer.cell(0, 2).text == "与本企业的异同"


@pytest.mark.parametrize("project", ["specialized-sme", "little-giant"])
def test_qualitative_indicator_benefits_survive_export(project):
    data = fixture()
    data["project_id"] = project
    data["report_sections"]["tasks"]["rows"] = [["PCT国际布局", "对应国际拓展正向指标，可作为加分提升方向。", "按适用期限"]]
    data["report_sections"]["soft"]["rows"] = [["质量管理能力", "等级待核", "对应质量控制，可形成加分优势。", "按实际等级取用"]]
    doc = build(data)
    text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "加分提升方向" in text and "加分优势" in text
    assert not module.SCORE_TEXT.search(text)


@pytest.mark.parametrize("project", ["specialized-sme", "little-giant"])
def test_project_specific_prerequisite_and_hidden_sections(project):
    data = fixture()
    data["project_id"] = project
    data["report_sections"]["conditional"] = {"paragraphs": ["条件触发旧输入"], "rows": []}
    data["report_sections"]["current_tasks"]["rows"].append(
        ["前置称号", "近期", "旧前置资格条件", "企业状态待核", "核对", "核认定文件与有效状态"])
    data["report_sections"]["acceptance"]["rows"].append(["资格与专注", "条件", "现状", "动作"])
    doc = build(data)
    text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])
    assert "条件触发" not in text and "资格与专注" not in text
    if project == "specialized-sme":
        assert "前置称号" not in text
    else:
        assert "前置称号" in text and "已获认定的省级专精特新中小企业" in text
        assert "企业状态待核" in text
    assert data["report_sections"]["current_tasks"]["rows"][-1][2] == "旧前置资格条件"

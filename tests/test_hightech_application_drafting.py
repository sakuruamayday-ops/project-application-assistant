from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "high-tech-enterprise-application-drafting"
SCRIPT = SKILL_ROOT / "scripts" / "expand_rd_ps_tables.py"
FILL_SCRIPT = SKILL_ROOT / "scripts" / "fill_rd_core_innovation.py"
AUDIT_SCRIPT = SKILL_ROOT / "scripts" / "audit_application_docx.py"
TEMPLATE = SKILL_ROOT / "assets" / "高新技术企业认定申请书空白模板.docx"
SPEC = importlib.util.spec_from_file_location("expand_rd_ps_tables", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
FILL_SPEC = importlib.util.spec_from_file_location("fill_rd_core_innovation", FILL_SCRIPT)
FILL_MODULE = importlib.util.module_from_spec(FILL_SPEC)
assert FILL_SPEC and FILL_SPEC.loader
FILL_SPEC.loader.exec_module(FILL_MODULE)
AUDIT_SPEC = importlib.util.spec_from_file_location("audit_application_docx", AUDIT_SCRIPT)
AUDIT_MODULE = importlib.util.module_from_spec(AUDIT_SPEC)
assert AUDIT_SPEC and AUDIT_SPEC.loader
AUDIT_SPEC.loader.exec_module(AUDIT_MODULE)


FOUR_LEVEL_FIELD = "五、高技术服务—一、研发与设计服务—2、涉及服务—专业设计技术"


def set_first_rd_field(document: Document) -> None:
    MODULE.resize_kind(document, "rd", 1, "RD")
    for table in document.tables:
        labels = {"".join(cell.text.split()) for row in table.rows for cell in row.cells}
        if not all(any(value.startswith(label) for value in labels) for label in (
            "研发活动名称",
            "技术领域",
            "核心技术及创新点",
        )):
            continue
        for row in table.rows:
            cells = list(MODULE.unique_cells(row))
            for index, cell in enumerate(cells):
                if "".join(cell.text.split()).startswith("技术领域") and index + 1 < len(cells):
                    cells[index + 1].text = FOUR_LEVEL_FIELD
                    for paragraph in cells[index + 1].paragraphs:
                        for run in paragraph.runs:
                            run.font.name = "宋体"
                            run.font.size = Pt(12)
                            run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")
                    return
    raise AssertionError("空白模板中未找到RD技术领域单元格")


def realistic_spec() -> dict:
    return {
        "schema_version": 1,
        "enterprise_profile": {
            "name": "某传统制造中小企业",
            "scale_summary": "中小型传统制造企业，以通用加工设备和人工辅助装配为主",
            "main_business": "精密五金部件及配套治具的设计、加工与交付",
            "patent_summary": "当前资料显示企业专利集中在治具结构、定位机构和防护组件",
            "scale_evidence": ["企业提供的员工及设备清单，核验日期2026-08-11"],
            "patent_evidence": ["企业提供的知识产权汇总表，核验日期2026-08-11"],
            "verified_advanced_terms": [],
        },
        "items": [
            {
                "rd_id": "RD01",
                "core_technologies": [
                    {
                        "name": "弹性浮动夹持与重复定位技术",
                        "description": (
                            "围绕薄壁零件受力后易翘曲、边缘易产生压痕的问题，采用分区弹片、限位台阶和可调预紧结构形成柔性夹持，"
                            "并利用底板定位孔与设备定位柱配合控制装夹基准。结构设计优先复用企业现有机加工、线切割和常规检测条件，"
                            "不依赖超出企业设备能力的复杂控制系统；通过对夹爪接触面、支撑高度和受力路径的协同优化，兼顾装夹稳定性、"
                            "表面防护和不同规格工件的快速切换"
                        ),
                        "indicators": "重复装夹位置偏差控制在±0.20毫米以内，单件装夹时间不超过45秒，边缘可见压痕发生率不高于1%",
                    },
                    {
                        "name": "模块化遮挡防护与换型技术",
                        "description": (
                            "针对不同工件孔位、外形和非加工区域差异，将通用载具与可拆卸遮挡片分体设计，采用卡扣和定位销实现快速安装，"
                            "减少整套治具重复制造。依据现有冲压、激光切割和人工检验条件确定遮挡片厚度、搭接量与防错方向，"
                            "通过首件确认、过程巡检和末件复核闭合质量记录，使多品种小批量生产中的换型动作、遮挡边界和清洁维护要求可执行、可追溯"
                        ),
                        "indicators": "不同型号换型时间不超过30分钟，遮挡边界偏差不大于0.30毫米，通用载具复用率不低于70%",
                    },
                ],
                "innovations": [
                    (
                        "将弹性夹持、基准定位和双面作业空间集成在同一套可加工治具中，在不改造主体设备的前提下减少翻面后的二次找正；"
                        "与传统刚性压紧方式相比，夹持力沿工件边缘分散，可降低薄壁部位局部受力和划伤风险，同时保留操作人员能够观察、"
                        "清洁和调整的结构空间，适合企业现有人员、设备和小批量订单条件"
                    ),
                    (
                        "将易随产品型号变化的遮挡件从载具主体中分离，通过更换低成本薄片而不是重新制作整套治具完成换型；"
                        "同时建立孔位防错、首件确认和更换记录，使结构改进与现场质量控制相衔接，减少因型号混用、遮挡不到位和清洁不充分造成的返工，"
                        "形成符合中小制造企业实际能力的渐进式工艺改进路径"
                    ),
                ],
            }
        ],
    }


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


def test_fill_rd_core_innovation_uses_exact_field_and_seven_line_format(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "filled.docx"
    report_path = tmp_path / "filled.audit.json"
    spec_path = tmp_path / "spec.json"
    document = Document(TEMPLATE)
    set_first_rd_field(document)
    document.save(source)
    spec_path.write_text(json.dumps(realistic_spec(), ensure_ascii=False, indent=2), encoding="utf-8")

    process = subprocess.run(
        [sys.executable, str(FILL_SCRIPT), str(source), str(spec_path), str(output), "--report", str(report_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["rd"]["RD01"]["body_length"] >= 400
    assert report["rd"]["RD01"]["core_technology_count"] == 2
    assert report["rd"]["RD01"]["innovation_count"] == 2
    assert report["enterprise"]["scale_evidence_count"] == 1
    assert report["enterprise"]["patent_evidence_count"] == 1

    rd_result, issues = AUDIT_MODULE.audit_rd_core_innovation(Document(output))
    assert issues == []
    assert rd_result["RD01"]["field"] == FOUR_LEVEL_FIELD
    assert rd_result["RD01"]["line_count"] == 7
    assert rd_result["RD01"]["body_length"] >= 400
    assert rd_result["RD01"]["core_technology_count"] == 2
    assert rd_result["RD01"]["innovation_count"] == 2


def test_fill_blocks_unverified_advanced_terms_before_output(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "blocked.docx"
    spec_path = tmp_path / "spec.json"
    document = Document(TEMPLATE)
    set_first_rd_field(document)
    document.save(source)
    data = realistic_spec()
    data["items"][0]["innovations"][0] += "项目同步建设数字孪生系统。"
    spec_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    process = subprocess.run(
        [sys.executable, str(FILL_SCRIPT), str(source), str(spec_path), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode != 0
    assert "缺少企业能力证据的高阶技术词" in process.stderr
    assert not output.exists()


def test_fill_requires_scale_and_patent_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "blocked.docx"
    spec_path = tmp_path / "spec.json"
    document = Document(TEMPLATE)
    set_first_rd_field(document)
    document.save(source)
    data = realistic_spec()
    data["enterprise_profile"]["patent_evidence"] = []
    spec_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    process = subprocess.run(
        [sys.executable, str(FILL_SCRIPT), str(source), str(spec_path), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode != 0
    assert "patent_evidence必须是非空字符串数组" in process.stderr
    assert not output.exists()

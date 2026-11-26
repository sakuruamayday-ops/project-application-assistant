#!/usr/bin/env python3
"""Fill a governed dual-report DOCX master from a private evidence fixture.

The fixture stays outside the public skill tree.  This module validates real
source anchors, fills the copied Word master, adds a source ledger, and refuses
to leave training placeholders in a completed draft.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.opc.part import XmlPart
from docx.shared import Pt, RGBColor
from lxml import etree


PLACEHOLDER = re.compile(r"［[^］\r\n]{1,120}］")
TRAINING_MARKERS = ("培训模板", "培训说明", "灰色提示文字")
INTERNAL_DRAFT_MARKERS = ("真实客户资料候选验收稿", "候选验收稿")
REPORT_TYPES = {"preassessment", "feasibility"}
CONDITION_COLUMNS = ("要求", "企业现状", "证据来源", "证据状态", "差距", "补强动作", "优先级")
REQUIRED_CONDITION_FIELDS = ("match", "value", "gap", "action", "priority")
REQUIRED_CONDITION_COLUMNS = ("要求", "企业现状", "差距", "补强动作", "优先级")
CONDITION_FIELD_LABELS = dict(zip(REQUIRED_CONDITION_FIELDS, REQUIRED_CONDITION_COLUMNS, strict=True))
BARE_NUMBER = re.compile(r"\s*\d+(?:\.\d+)?\s*")
HIGH_TECH_THRESHOLD = re.compile(
    r"(?:企业)?创新能力(?:综合|评价|得分)*\s*(?:须|应)?(?:超过|大于|不低于|达到|[>≥])\s*[0-9]+(?:\.[0-9]+)?\s*分"
    r"(?:[（(]不含[）)]|[（(]含[）)]|[。；])?"
)
DEFECT_COLUMNS = ("优先级", "缺陷项", "要求", "企业现状", "差距", "证据", "补强动作")
SCORE_COLUMN = re.compile(
    r"评分.*|.*(?:得分|评分|估分|计分|分数|分值|上限分)|(?:总|满|确定|条件|目标|保守|压力|平台|质量)分"
    r"|(?:fixed_|conditional_|estimated_)?score(?:_basis)?",
    re.IGNORECASE,
)
CONCLUSION_ALIASES = {
    "待资料": "暂无法判断",
    "培育后申报": "有条件申报",
    "建议申报": "可申报",
}
CONCLUSIONS = {"可申报", "有条件申报", "不可申报", "暂无法判断"}
EVIDENCE_STATES = {
    "已具备",
    "企业提供待核",
    "待企业确认",
    "第三方平台查询，待企业确认",
    "当前检索层未命中",
    "明确未具备",
    "存在差距",
    "冲突待核",
    "不适用",
}
EVIDENCE_STATE_ALIASES = {"待补强": "存在差距", "待核实": "待企业确认", "待核": "待企业确认",
                          "已有": "已具备", "待确认": "待企业确认", "未具备": "明确未具备"}
CJK_FONT = "宋体"
WESTERN_FONT = "Times New Roman"
PUBLIC_DIGEST = re.compile(r"(?:SHA[\s_-]*256|(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f]))", re.IGNORECASE)


class ReportInputError(ValueError):
    """A known input defect that the host may recognize without parsing prose."""

    def __init__(self, message: str, code: str, fields: list[str]):
        super().__init__(message)
        self.input_rejection = {"code": code, "fields": fields}


def table_header_key(columns) -> tuple[str, ...]:
    aliases = {"现行条件或评分项": "要求", "企业值": "企业现状", "评价项": "缺陷项",
               "补强": "补强动作", "补强建议": "补强动作", "补强措施": "补强动作",
               "责任人员": "责任人", "截止日期": "内部节点",
               "申报截止日期": "准备节点", "申报年度": "评估年度"}
    return tuple(aliases.get(normalize_text(str(value)), normalize_text(str(value))) for value in columns)


def _report_value(value, *, hightech_field=None):
    if isinstance(value, str):
        from sme_action_report import SCORE_TEXT, public_text
        if hightech_field in {"要求", "缺陷项"} and HIGH_TECH_THRESHOLD.fullmatch(value.strip()):
            return value
        if (hightech_field in {"企业现状", "差距", "补强动作"}
                and re.match(r"缺|未|需|补|取|核|建立", value.strip())
                and set(SCORE_TEXT.findall(value)) == {"评分"}):
            return value
        if SCORE_TEXT.search(value):
            return public_text(value)
    return value


def report_table_entries(fixture: dict[str, Any], *, feasibility: bool, hightech_word: bool = False) -> list[dict[str, Any]]:
    entries = fixture.get("table_content", [])
    if isinstance(entries, dict) and set(entries) <= {"columns", "rows"}:
        entries = [entries]
    if not isinstance(entries, list):
        raise ReportInputError("table_content 必须为表格数组或单张表格对象", "report-table-shape", ["table_content"])
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReportInputError("table_content 每项必须包含 columns 与 rows", "report-table-shape", ["table_content"])
        columns, rows = entry.get("columns"), entry.get("rows")
        if (not isinstance(columns, list) or not columns
                or not all(isinstance(value, str) and value.strip() for value in columns)):
            raise ReportInputError("table_content.columns 必须为非空表头数组", "report-table-shape", ["table_content.columns"])
        if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
            raise ReportInputError("table_content.rows 每行列数须与表头一致", "report-table-shape", ["table_content.rows"])
        if "评分维度" in columns:
            continue
        kept = [index for index, column in enumerate(columns)
                if not SCORE_COLUMN.fullmatch(normalize_text(column)) or column == "现行条件或评分项"]
        if not kept:
            continue
        removed_score = len(kept) != len(columns)
        columns = [columns[index] for index in kept]
        public_rows = [[row[index] for index in kept] for row in rows
                       if not SCORE_COLUMN.fullmatch(normalize_text(str(row[0])))]
        if any(not isinstance(value, (str, int, float)) or isinstance(value, bool)
               for row in public_rows for value in row):
            raise ReportInputError("table_content.rows 仅支持文本和数值", "report-table-shape", ["table_content.rows"])
        if rows and not public_rows:
            continue
        if removed_score:
            columns = list(table_header_key(columns))
        if feasibility:
            key = table_header_key(columns)
            hightech_fields = hightech_word and key in {CONDITION_COLUMNS, CONDITION_COLUMNS[:5],
                                                        REQUIRED_CONDITION_COLUMNS, DEFECT_COLUMNS}
            public_rows = [[_report_value(value, hightech_field=column if hightech_fields else None)
                            for column, value in zip(key, row, strict=True)] for row in public_rows]
            if removed_score and tuple(columns) == CONDITION_COLUMNS[:5]:
                columns = list(CONDITION_COLUMNS)
                for row in public_rows:
                    _, _, _, _, action, priority = _condition_values(fixture, str(row[0]))
                    row.extend((action, priority))
        if hightech_word and table_header_key(columns) in {CONDITION_COLUMNS, REQUIRED_CONDITION_COLUMNS}:
            if table_header_key(columns) == REQUIRED_CONDITION_COLUMNS:
                public_rows = [[row[0], row[1], "", "", *row[2:]] for row in public_rows]
            _verify_condition_rows(public_rows, _hightech_condition_rows(fixture))
            continue
        if hightech_word and table_header_key(columns) == DEFECT_COLUMNS:
            _check_hightech_defects(public_rows)
        result.append({"columns": columns, "rows": public_rows})
    if feasibility and not any(table_header_key(entry["columns"]) == DEFECT_COLUMNS for entry in result):
        items = fixture.get("items")
        if items:
            fields = ("priority", "item", "requirement", "actual", "gap", "evidence", "action")
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ReportInputError("items 必须为缺陷事项数组", "report-items-shape", ["items"])
            rows = [[_report_value(str(item.get(field) or "—"), hightech_field=column if hightech_word else None)
                     or "—" for column, field in zip(DEFECT_COLUMNS, fields, strict=True)] for item in items]
            if hightech_word:
                _check_hightech_defects(rows)
            result.append({"columns": list(DEFECT_COLUMNS), "rows": rows})
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def primary_source_name(fixture: dict[str, Any]) -> str:
    sources = fixture["_validated_sources"]
    return sources[0]["name"] if sources else "尚未提供客户资料"


def extract_source_text(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        document = Document(path)
        parts = [paragraph.text for paragraph in document.paragraphs]
        parts.extend(
            cell.text
            for table in document.tables
            for row in table.rows
            for cell in row.cells
        )
        return "\n".join(parts)
    if suffix == ".pdf":
        if __name__ == "__main__":
            sys.modules.setdefault("pymupdf.layout", None)
            sys.modules.setdefault("pymupdf4llm", None)
        import fitz

        document = fitz.open(path)
        try:
            return "\n".join(page.get_text("text") for page in document)
        finally:
            document.close()
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            return "\n".join(
                str(value)
                for sheet in workbook.worksheets
                for row in sheet.iter_rows(values_only=True)
                for value in row
                if value not in (None, "")
            )
        finally:
            workbook.close()
    if suffix in {".txt", ".md", ".csv", ".json", ".jsonl"}:
        return path.read_text(encoding="utf-8")
    raise ValueError(f"不支持的客户资料格式:{path.name}")


def _public_source_reference(material: dict[str, Any]) -> dict[str, str | None]:
    source_type = str(material.get("source_type") or "").strip().casefold()
    raw = str(
        material.get("url")
        or material.get("official_url")
        or material.get("link")
        or material.get("source")
        or ""
    ).strip()
    if source_type in {"knowledge-base", "knowledge_base", "local-knowledge"} or raw == "知识库":
        return {"label": "来源知识库", "url": None}
    if raw.startswith(("https://", "http://")):
        return {"label": raw, "url": raw}
    return {"label": raw or "用户提供", "url": None}


def validate_case_fixture(
    fixture: dict[str, Any],
    *,
    expected_project_id: str | None = None,
    public_root: Path | None = None,
    feasibility: bool = False,
    hightech_word: bool = False,
) -> dict[str, Any]:
    required = {
        "project_id",
        "enterprise",
    }
    missing = sorted(required - set(fixture))
    if missing:
        raise ReportInputError("客户夹具缺字段:" + ",".join(missing), "report-required-fields", missing)
    project_id = str(fixture["project_id"]).strip()
    if expected_project_id and project_id != expected_project_id:
        raise ValueError(f"项目路由与夹具不一致:{expected_project_id}/{project_id}")
    if not str(fixture["enterprise"]).strip():
        raise ValueError("企业名称不得为空")
    fixture = deepcopy(fixture)
    warnings: list[str] = []
    if feasibility:
        for key in ("conclusion_basis", "primary_gap", "next_action", "headline_fact", "gate_summary",
                    "year_basis", "level_basis", "window_status"):
            if key in fixture:
                fixture[key] = _report_value(fixture[key])
    defaults = {"project_object": "申报核心对象待明确", "suggested_year": "客户填写",
                "conclusion": "暂无法判断",
                "conclusion_basis": "现有资料不足以确认主要结论。", "primary_gap": "关键证据待补充",
                "next_action": "补充关键证据后继续完善报告"}
    labels = {"project_object": "申报核心对象", "suggested_year": "评估年度",
              "conclusion": "总体结论", "conclusion_basis": "结论依据", "primary_gap": "主要差距", "next_action": "下一步行动"}
    for key, default in defaults.items():
        if not str(fixture.get(key) or "").strip():
            fixture[key] = default
            warnings.append(f"{labels[key]}尚未明确，当前保留待核提示")
    materials = fixture.get("materials", [])
    if not isinstance(materials, list):
        raise ValueError("materials 必须为资料数组")
    if not materials:
        warnings.append("尚未提供可核验的客户资料，以下结论作为初稿参考")
    normalized_sources: list[dict[str, Any]] = []
    for material in materials:
        if not isinstance(material, dict):
            raise ValueError("客户资料记录格式错误")
        path = Path(str(material.get("path") or "")).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if public_root is not None:
            try:
                path.relative_to(public_root.resolve())
            except ValueError:
                pass
            else:
                raise ValueError("真实客户资料不得放入公共技能树")
        anchors = material.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            raise ValueError(f"客户资料缺原文锚点:{path.name}")
        source_text = normalize_text(extract_source_text(path))
        checked_anchors: list[str] = []
        for anchor in anchors:
            anchor_text = str(anchor).strip()
            if len(normalize_text(anchor_text)) < 4:
                raise ValueError(f"原文锚点过短:{path.name}")
            if normalize_text(anchor_text) not in source_text:
                raise ValueError(f"原文锚点未命中:{path.name}:{anchor_text}")
            checked_anchors.append(anchor_text)
        normalized_sources.append(
            {
                "path": path,
                "name": path.name,
                "sha256": sha256_file(path),
                "anchors": checked_anchors,
                "role": str(material.get("role") or "企业资料"),
                "public_source": _public_source_reference(material),
            }
        )
    policies = fixture.get("policies", [])
    if not isinstance(policies, list):
        raise ValueError("policies 必须为政策数组")
    for policy in policies:
        if not isinstance(policy, dict) or not str(policy.get("title") or "").strip():
            raise ValueError("政策基线缺文件名称")
        if not str(policy.get("locator") or "").strip():
            raise ValueError("政策基线缺原文位置或官方链接")
    policies = [policy for policy in policies if not is_batch_policy(policy)]
    if not policies:
        warnings.append("缺适用管理办法")
    conditions = fixture.get("conditions", [])
    if not isinstance(conditions, list) or any(
        not isinstance(row, dict) or not str(row.get("match") or "").strip() for row in conditions
    ):
        raise ReportInputError("conditions 须逐项填写 match 条件名称", "report-conditions-shape", ["conditions.match"])
    for condition in conditions:
        state = str(condition.get("state") or "待企业确认")
        state = EVIDENCE_STATE_ALIASES.get(state, state)
        if state not in EVIDENCE_STATES:
            raise ReportInputError(f"不受控的证据状态:{state}", "report-evidence-state", ["conditions.state"])
        condition["state"] = state
        for key in ("value", "gap", "action", "priority"):
            if key in condition:
                column = CONDITION_FIELD_LABELS[key]
                condition[key] = _report_value(condition[key], hightech_field=column if hightech_word else None)
        match = str(condition["match"])
        if (BARE_NUMBER.fullmatch(str(condition.get("value", "")))
                and (re.search(r"创新能力评价|发展质量评价|主管部门.*评价", match)
                     or hightech_word and "创新能力" in match)):
            condition.pop("value")
    if hightech_word:
        if not conditions:
            raise ReportInputError("高企可行性报告缺门槛条件", "report-condition-rows", ["conditions"])
        names = [normalize_text(str(condition["match"])) for condition in conditions]
        if len(names) != len(set(names)):
            raise ReportInputError("高企门槛条件名称重复", "report-condition-rows", ["conditions.match"])
        for index, condition in enumerate(conditions, 1):
            _require_condition_fields([condition.get(field) for field in REQUIRED_CONDITION_FIELDS],
                                      f"conditions[{index}]", REQUIRED_CONDITION_FIELDS)
    conclusion = CONCLUSION_ALIASES.get(str(fixture["conclusion"]).strip(), str(fixture["conclusion"]).strip())
    if conclusion not in CONCLUSIONS:
        raise ValueError("前期评估结论必须为可申报、有条件申报、不可申报或暂无法判断")
    return {**fixture, "materials": materials, "policies": policies, "conclusion": conclusion,
            "_validated_sources": normalized_sources, "_input_warnings": warnings}


def _set_text(paragraph, value: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = value
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(value)


def _apply_report_fonts(document: Document) -> None:
    """Apply the report font names to overrides in the supplied Word master."""
    for part in document.part.package.parts:
        name = str(part.partname)
        if not name.startswith("/word/") or not name.endswith(".xml") or name == "/word/numbering.xml":
            continue
        root = part._element if isinstance(part, XmlPart) else parse_xml(part.blob)
        fonts_in_part = list(root.iter(qn("w:rFonts")))
        changed = bool(fonts_in_part)
        for fonts in fonts_in_part:
            for theme in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
                fonts.attrib.pop(qn(f"w:{theme}"), None)
            for attribute in ("ascii", "hAnsi", "cs"):
                fonts.set(qn(f"w:{attribute}"), WESTERN_FONT)
            fonts.set(qn("w:eastAsia"), CJK_FONT)
        if name == "/word/fontTable.xml":
            for relation_id, relation in list(part.rels.items()):
                if relation.reltype == RELATIONSHIP_TYPE.FONT:
                    del part.rels[relation_id]
            for font in root.iter(qn("w:font")):
                for entry in list(font):
                    if etree.QName(entry).localname.startswith("embed"):
                        font.remove(entry)
                        changed = True
        if changed and not isinstance(part, XmlPart):
            part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    settings = document.settings.element
    for tag in ("embedTrueTypeFonts", "embedSystemFonts", "saveSubsetFonts"):
        option = settings.find(qn(f"w:{tag}"))
        if option is not None:
            settings.remove(option)

def _iter_paragraphs(document: Document) -> Iterable[Any]:
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
    for section in document.sections:
        for container in (section.header, section.footer):
            yield from container.paragraphs
            for table in container.tables:
                for row in table.rows:
                    for cell in row.cells:
                        yield from cell.paragraphs


def _replace_training_text(value: str, fixture: dict[str, Any], release_tag: str) -> str:
    replacements = {
        "企业名称：［填写］": f"企业名称：{fixture['enterprise']}",
        "报告日期：［填写］": f"报告日期：{fixture.get('report_date') or date.today().isoformat()}",
        "顾问：［填写］": "",
        "灰色提示文字为培训说明，正式交付前应替换或删除。": "本稿已按真实客户资料回填，未取得的企业数据统一标注待企业确认。",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    version_pattern = rf"(?:{re.escape(release_tag)}|V\d+(?:\.\d+){{2,3}})"
    return re.sub(rf"{version_pattern}\s*培训模板(?:\s*\|\s*)?", "", value)


def _fallback_for_placeholder(token: str, context: str, fixture: dict[str, Any]) -> str:
    hint = token.strip("［］")
    combined = context + hint
    primary_source = primary_source_name(fixture)
    if any(word in hint for word in ("企业全称", "企业名称", "申报企业")) or (hint == "填写" and "企业" in context):
        return str(fixture["enterprise"])
    if any(word in hint for word in ("评估结论", "申报结论", "总体结论")):
        return str(fixture["conclusion"])
    if hint == "填写并注明来源":
        return "同行数据未取得，来源待补充"
    if hint in ("政府公示同类企业", "行业代表产品"):
        return "可比对象待检索核验"
    if any(word in combined for word in ("申报年度", "完成年度")):
        return str(fixture["suggested_year"])
    if any(word in combined for word in ("产品", "申报对象", "核心对象")):
        return str(fixture["project_object"])
    if any(word in combined for word in ("文件、页码", "文件或台账", "证据", "来源")):
        return primary_source
    if any(word in combined for word in ("责任人", "核验人", "复核人")):
        return str(fixture.get("owner") or "企业项目负责人")
    if any(word in combined for word in ("准备节点", "完成节点", "建议时间", "年度/季度", "内部节点")):
        return str(fixture.get("target_period") or "按当年度申报批次排期")
    if any(word in combined for word in ("具体动作", "补强动作", "后续动作", "下一步")):
        return str(fixture["next_action"])
    if any(word in combined for word in ("差距", "短板")):
        return str(fixture["primary_gap"])
    if hint == "优先级":
        return "待排序"
    if any(word in combined for word in ("数据", "企业值", "现状", "已知")):
        return str(fixture.get("headline_fact") or "当前资料未提供可复算数据")
    if any(word in combined for word in ("状态", "已具备/待")):
        return "待企业确认"
    if any(word in combined for word in ("口径", "统计期间")):
        return "按适用管理办法及企业专项底稿"
    if any(word in combined for word in ("交付物", "完成标准", "可核验成果")):
        return "形成可复核台账、报告及原始证据索引"
    if any(word in combined for word in ("核心原因", "依据", "限制")):
        return str(fixture["conclusion_basis"])
    return "待企业确认"


def _condition_match(fixture: dict[str, Any], condition_text: str) -> dict[str, Any] | None:
    normalized = normalize_text(condition_text)
    matches: list[tuple[int, dict[str, Any]]] = []
    for item in fixture.get("conditions", []):
        key = normalize_text(str(item.get("match") or ""))
        if _is_sme_prerequisite(fixture, condition_text) and _is_sme_prerequisite(fixture, key):
            key = normalized
        if normalized == "主管部门当年度发展质量评价达到适用要求" and key == "专业化、精细化、特色化和创新能力评价达到现行分值要求":
            key = normalized
        if key and (key in normalized or normalized in key):
            matches.append((len(key), item))
    return max(matches, default=(0, None), key=lambda pair: pair[0])[1]


def _condition_values(fixture: dict[str, Any], requirement: str) -> tuple[str, ...]:
    return _condition_row_values(fixture, _condition_match(fixture, requirement), requirement)


def _is_sme_prerequisite(fixture, requirement):
    if fixture.get("project_id") not in {"specialized-sme", "little-giant"}:
        return False
    from sme_action_report import PREREQUISITE
    return bool(PREREQUISITE.search(requirement))


def _condition_row_values(fixture: dict[str, Any], condition: dict[str, Any] | None,
                          requirement: str = "") -> tuple[str, ...]:
    match = condition or {}
    supplied_value = match.get("value")
    value = "当前资料未提供可复算数据" if supplied_value in (None, "") else str(supplied_value)
    state = str(match.get("state") or "待企业确认")
    source = str(match.get("source") or primary_source_name(fixture))
    if state == "企业提供待核" and re.search(r"(?:企查查|天眼查|\bQCC\b|\bTYC\b)", source, re.IGNORECASE):
        state = "第三方平台查询，待企业确认"
    pending = state not in {"已具备", "不适用"}
    gap = str(match.get("gap") or ("数据和证据尚未闭合" if pending else "—"))
    action = str(match.get("action") or ("补齐本项核验材料" if pending else "—"))
    priority = str(match.get("priority") or ("待排序" if pending else "—"))
    if pending and supplied_value in (None, "") and _is_sme_prerequisite(fixture, requirement):
        from sme_action_report import MISSING_PREREQUISITE
        value = MISSING_PREREQUISITE
        gap = str(match.get("gap") or "缺有效前置称号或适用批次证明")
        action = str(match.get("action") or "核对有效称号、对应年度和认定或复核批次")
    return value, source, state, gap, action, priority


def _require_condition_fields(values, label, fields=REQUIRED_CONDITION_COLUMNS):
    missing = [field for field, value in zip(fields, values, strict=True)
               if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float))
               or str(value).strip() in {"", "—", "-", "－"}]
    if missing:
        raise ReportInputError(f"{label} 缺字段：{'、'.join(missing)}", "report-condition-fields", list(missing))


def _hightech_condition_rows(fixture):
    return [[str(condition["match"]), *_condition_row_values(fixture, condition)]
            for condition in fixture["conditions"]]


def _verify_condition_rows(actual, expected):
    if len(actual) != len(expected):
        raise ReportInputError(f"高企门槛行数不一致，输入 {len(expected)} 条，实际 {len(actual)} 行",
                               "report-condition-rows", ["conditions", "table_content.rows"])
    fields = (0, 1, 4, 5, 6)
    for index, (row, reference) in enumerate(zip(actual, expected, strict=True), 1):
        values = [row[column] for column in fields]
        _require_condition_fields(values, f"第 {index} 行高企门槛")
        if any(normalize_text(str(value)) != normalize_text(reference[column])
               for column, value in zip(fields, values, strict=True)):
            raise ReportInputError(f"第 {index} 行高企门槛不对应输入条件 {reference[0]}",
                                   "report-condition-rows", ["conditions", "table_content.rows"])


def _check_hightech_defects(rows):
    for index, row in enumerate(rows, 1):
        if "创新能力" in str(row[1]) or "创新能力" in str(row[2]):
            if BARE_NUMBER.fullmatch(str(row[3])):
                raise ReportInputError(f"第 {index} 行创新能力缺企业现状的事实依据",
                                       "report-condition-fields", ["企业现状"])
            _require_condition_fields([row[column] for column in (2, 3, 4, 6, 0)],
                                      f"第 {index} 行创新能力缺陷")


def _write_table_rows(table, rows):
    prototype = deepcopy(table.rows[-1]._tr)
    for row in table.rows[1:]:
        table._tbl.remove(row._tr)
    for values in rows:
        table._tbl.append(deepcopy(prototype))
        for cell, value in zip(table.rows[-1].cells, values, strict=True):
            _set_cell_text(cell, str(value))
    _lock_table_pagination(table)


def retained_condition_rows(fixture, header, template_rows, supplied_rows):
    if header not in {CONDITION_COLUMNS, ("现行条件", "企业现状", "证据状态", "差距", "补强动作")}:
        return supplied_rows

    def row_key(label):
        return "前置称号" if _is_sme_prerequisite(fixture, str(label)) else normalize_text(str(label))

    replacements = {row_key(row[0]): row for row in supplied_rows}
    rows = []
    for original in template_rows:
        replacement = replacements.pop(row_key(original[0]), None)
        rows.append([original[0], *replacement[1:]] if replacement else original)
    return [*rows, *replacements.values()]


def _pending_items_summary(fixture: dict[str, Any]) -> tuple[str, str]:
    for entry in fixture["table_content"]:
        if table_header_key(entry["columns"]) == DEFECT_COLUMNS:
            return f"{len(entry['rows'])} 项", "按缺陷与差距表所列事项计"
    conditions = fixture.get("conditions", [])
    if conditions:
        count = sum(item["state"] not in {"已具备", "不适用"} for item in conditions)
        return f"{count} 项", "按已登记条件中的待补事项计"
    return "—", "缺逐项核验结果"


POLICY_ROW_KINDS = {
    "管理办法或评价办法": "management",
    "地方实施细则": "implementation",
    "办法随文评价附件": "guidance",
    "工作指引": "work-guidance",
    "申报指南与评分附件": "guidance",
    "申报指南与评价附件": "guidance",
}


def policy_kinds(policy: dict[str, Any]) -> set[str]:
    declared = str(policy.get("kind") or "").strip().casefold()
    result = {declared} if declared else set()
    title = str(policy.get("title") or "")
    if "实施细则" in title:
        result.add("implementation")
    if "工作指引" in title:
        result.add("work-guidance")
    if re.search(r"管理办法|评价办法|实施办法", title):
        result.add("management")
    if re.search(r"评分附件|评价附件|评价导则", title):
        result.add("guidance")
    return result


def is_batch_policy(policy: dict[str, Any]) -> bool:
    kind = str(policy.get("kind") or "").strip().casefold()
    title = str(policy.get("title") or "")
    return kind in {"annual-notice", "deadline"} or bool(
        re.search(r"(?:关于(?:组织)?(?:开展|申报|征集|推荐|实施)|\d{4}\s*年度).*通知", title)
    )


def _fill_policy_table(table, fixture: dict[str, Any], feasibility: bool) -> None:
    policies = fixture["policies"]
    if len(table.rows[0].cells) >= 3:
        _set_text(table.rows[0].cells[2].paragraphs[0], "官方来源")

    def write_policy(cells, policy: dict[str, Any] | None) -> None:
        if policy is None:
            cells[1].text = "当前未取得独立文件"
            for cell in cells[2:-1]:
                cell.text = "—"
            cells[-1].text = "待核验"
            return
        cells[1].text = str(policy["title"])
        if len(cells) == 5:
            cells[2].text = str(policy.get("scope") or "按管理办法适用范围")
        locator = str(policy["locator"])
        if locator.startswith(("https://", "http://")):
            _set_cell_text(cells[-2], "")
            _add_hyperlink(cells[-2].paragraphs[0], "查看官方原文", locator)
        else:
            cells[-2].text = locator
        cells[-1].text = str(policy.get("status") or "已锁定基线")

    written = set()
    for row in list(table.rows[1:]):
        cells = row.cells
        row_name = cells[0].text.strip()
        expected = POLICY_ROW_KINDS.get(row_name)
        policy = next((item for item in policies if expected in policy_kinds(item)), None)
        if policy is None and expected != "management":
            table._tbl.remove(row._tr)
            continue
        if feasibility and row_name == "申报指南与评分附件":
            _set_text(cells[0].paragraphs[0], "申报指南与评价附件")
        write_policy(cells, policy)
        if policy is not None:
            written.add(id(policy))

    for policy in policies:
        if id(policy) not in written:
            cells = table.add_row().cells
            cells[0].text = "其他政策依据"
            write_policy(cells, policy)


def _fill_summary_table(table, fixture: dict[str, Any]) -> None:
    for row in table.rows[1:]:
        key = row.cells[0].text.strip()
        if "当前可行性" in key:
            row.cells[1].text = str(fixture["conclusion"])
            row.cells[2].text = str(fixture["conclusion_basis"])
        elif "申报结论" in key:
            row.cells[1].text = str(fixture["conclusion"])
            row.cells[2].text = str(fixture["conclusion_basis"])
        elif key in {"建议申报年度", "评估年度"}:
            row.cells[1].text = str(fixture["suggested_year"])
            row.cells[2].text = str(fixture.get("year_basis") or "客户选择评估年度")
        elif "申报层级" in key or "档次" in key:
            row.cells[1].text = str(fixture.get("level") or "待企业确认适用层级")
            row.cells[2].text = str(fixture.get("level_basis") or "按项目属地和管理办法")
        elif "首要短板" in key:
            row.cells[1].text = str(fixture["primary_gap"])
            row.cells[2].text = str(fixture["next_action"])
        elif "预计满足硬门槛" in key:
            row.cells[1].text = str(fixture.get("gate_summary") or "待企业补齐数据后复算")
            row.cells[2].text = "按管理办法条款核对"
        elif key == "待补事项数":
            count, basis = _pending_items_summary(fixture)
            row.cells[1].text = count
            row.cells[2].text = basis
        elif "关键前置任务" in key:
            row.cells[1].text = str(fixture["next_action"])
            row.cells[2].text = str(fixture.get("target_period") or "客户填写")


def _fill_condition_table(table, fixture: dict[str, Any], *, hightech_word: bool = False) -> None:
    if hightech_word:
        _write_table_rows(table, _hightech_condition_rows(fixture))
        return
    template_rows = table.rows[1:]
    matched = [_condition_match(fixture, row.cells[0].text.strip()) for row in template_rows]
    uses = Counter(id(item) for item in matched if item is not None)
    written = set()

    def write_condition(cells, condition):
        value, source, state, gap, action, priority = _condition_row_values(fixture, condition, cells[0].text)
        values = (value, state, gap, action) if len(cells) == 5 else (value, source, state, gap, action, priority)
        for cell, text in zip(cells[1:], values, strict=True):
            cell.text = text

    for row, item in zip(template_rows, matched, strict=True):
        cells = row.cells
        if item is not None:
            exact = normalize_text(cells[0].text) == normalize_text(str(item["match"]))
            if uses[id(item)] > 1 and not exact:
                item = None
        write_condition(cells, item)
        if item is not None:
            written.add(id(item))
    for item in fixture.get("conditions", []):
        if id(item) not in written:
            cells = table.add_row().cells
            cells[0].text = str(item["match"])
            write_condition(cells, item)


def _fill_path_table(table, fixture: dict[str, Any]) -> None:
    for row in table.rows[1:]:
        cells = row.cells
        if len(cells) >= 5:
            cells[1].text = str(fixture["suggested_year"])
            cells[2].text = str(fixture.get("target_period") or "客户填写")
            cells[3].text = str(fixture["conclusion"])
            cells[4].text = str(fixture["next_action"])


def _fill_strengthening_table(table, fixture: dict[str, Any]) -> None:
    defaults = {
        "国内产品技术水平评价咨询报告": (
            "当前资料未提供国内技术水平评价报告，是否已有待确认",
            "国内产品技术水平评价咨询报告",
        ),
        "国际产品技术水平评价咨询报告": (
            "当前资料未提供国际技术水平评价报告，是否已有待确认",
            "国际产品技术水平评价咨询报告",
        ),
        "技术查新或科技咨询": (
            "尚未提供技术查新或科技咨询成果",
            "技术查新报告或科技咨询意见",
        ),
        "任务指标检测方案和项目预算底稿": (
            "任务指标与项目预算底稿尚未闭合",
            "任务指标对照表、检测方案和项目预算底稿",
        ),
    }
    configured = [
        item
        for item in fixture.get("strengthening_tasks", [])
        if isinstance(item, dict) and str(item.get("task") or "").strip()
    ]
    if configured:
        template_row = table.rows[-1]._tr
        while len(table.rows) - 1 < len(configured):
            table._tbl.append(deepcopy(template_row))
        while len(table.rows) - 1 > len(configured):
            table._tbl.remove(table.rows[-1]._tr)
    default_period = fixture.get("target_period") or "客户填写"
    for index, row in enumerate(table.rows[1:], start=1):
        cells = row.cells
        task = cells[1].text.strip()
        item = configured[index - 1] if configured else {}
        default_status, default_deliverable = defaults.get(
            task,
            ("当前资料未提供该项成果，是否已有待确认", "形成可核验的成果文件"),
        )
        cells[0].text = str(index)
        cells[1].text = str(item.get("task") or task)
        cells[2].text = str(item.get("status") or default_status)
        cells[3].text = str(item.get("target_period") or fixture.get("target_period") or default_period)
        cells[4].text = str(item.get("deliverable") or default_deliverable)


def _lock_table_pagination(table) -> None:
    if not table.rows:
        return
    header_properties = table.rows[0]._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    header_properties.append(repeat)
    for row in table.rows:
        properties = row._tr.get_or_add_trPr()
        cant_split = OxmlElement("w:cantSplit")
        cant_split.set(qn("w:val"), "true")
        properties.append(cant_split)


def _preserve_report_pagination(document: Document) -> None:
    # 表后空段仍占正文行高，嵌入字体后会把短清单挤到独立页；保留段落与章节分页，只压缩纯空白间隔。
    for paragraph in document.paragraphs:
        previous = paragraph._p.getprevious()
        if previous is None or previous.tag != qn("w:tbl") or paragraph.text:
            continue
        if any(list(paragraph._p.iter(qn(tag))) for tag in ("w:drawing", "w:pict", "w:object", "w:br", "w:fldChar", "w:sectPr")):
            continue
        if paragraph.paragraph_format.page_break_before:
            continue
        paragraph.paragraph_format.line_spacing = Pt(1)
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.keep_with_next = True
    # 母版中的短清单应连同标题保留，不能把最后一两条单独挤到新页。
    paragraphs = document.paragraphs
    for paragraph, following in zip(paragraphs, paragraphs[1:]):
        if (paragraph.style.name == "List Bullet" and following.style.name == "List Bullet"
                and paragraph._p.getnext() is following._p):
            paragraph.paragraph_format.keep_with_next = True


def _fill_project_specific_paragraphs(document: Document, fixture: dict[str, Any]) -> None:
    replacements = {
        "申报主体：": f"申报主体：{fixture['enterprise']}",
        "主导产品或申报对象：": f"主导产品或申报对象：{fixture['project_object']}",
        "建议口径：": f"建议口径：{fixture.get('recommended_scope') or fixture['project_object']}",
    }
    for paragraph in document.paragraphs:
        for prefix, replacement in replacements.items():
            if paragraph.text.strip().startswith(prefix):
                _set_text(paragraph, replacement)


def _fill_table_by_header(table, fixture: dict[str, Any], feasibility: bool, *, hightech_word: bool = False) -> None:
    if not table.rows:
        return
    cells = table.rows[0].cells
    columns = tuple(cell.text.strip() for cell in cells)
    header = " | ".join(columns)
    if "政策层级" in header and ("现行文件" in header or "文件名称与文号" in header):
        _fill_policy_table(table, fixture, feasibility)
    elif ("判断项" in header and "一句话依据" in header) or ("事项" in header and "依据及限制" in header):
        _fill_summary_table(table, fixture)
    elif "现行条件 | 企业值" in header or columns == CONDITION_COLUMNS:
        _fill_condition_table(table, fixture, hightech_word=hightech_word)
    elif feasibility and table_header_key(columns) == DEFECT_COLUMNS and columns[1] != "缺陷项":
        _set_text(cells[1].paragraphs[0], "缺陷项")
    elif table_header_key(columns)[:3] == ("项目", "评估年度", "准备节点"):
        for cell, label in zip(cells[1:3], ("评估年度", "准备节点"), strict=True):
            _set_text(cell.paragraphs[0], label)
        _fill_path_table(table, fixture)
    elif "补强任务" in header and "成果证据" in header:
        _fill_strengthening_table(table, fixture)


def _fill_table_content(document: Document, fixture: dict[str, Any]) -> None:
    """Match known header aliases; retain additional analysis without changing the master."""
    used: set[tuple[str, ...]] = set()
    for entry in fixture["table_content"]:
        columns, rows = entry.get("columns"), entry.get("rows")
        key = table_header_key(columns)
        if key in used:
            raise ReportInputError("重复回填同一表头:" + " | ".join(key), "report-table-target", ["table_content.columns"])
        used.add(key)
        matches = [table for table in document.tables if table.rows
                   and table_header_key([cell.text for cell in table.rows[0].cells]) == key]
        if not matches:
            document.add_heading("补充分析", level=2)
            table = document.add_table(rows=1, cols=len(columns))
            table.style = "Table Grid"
            for cell, value in zip(table.rows[0].cells, columns, strict=True):
                _set_cell_text(cell, value)
            for values in rows:
                for cell, value in zip(table.add_row().cells, values, strict=True):
                    _set_cell_text(cell, str(value))
            fixture["_input_warnings"].append("补充分析中的表格内容和位置尚需复核")
            continue
        if len(matches) != 1:
            raise ReportInputError("表头必须唯一匹配母版:" + " | ".join(key), "report-table-target", ["table_content.columns"])
        if not rows:
            continue
        table = matches[0]
        rows = retained_condition_rows(fixture, key, [[cell.text for cell in row.cells] for row in table.rows[1:]], rows)
        _write_table_rows(table, rows)


def _fill_hightech_associations(document: Document, fixture: dict[str, Any]) -> None:
    rows = fixture.get("core_associations")
    if rows is None:
        return
    if fixture["project_id"] != "high-tech-enterprise":
        raise ValueError("core_associations 仅用于高企四关联矩阵")
    columns = ["研发项目", "核心技术", "知识产权及状态", "成果转化", "高新产品及收入", "对应依据与缺口"]
    if (not isinstance(rows, list) or not rows
            or any(not isinstance(row, list) or len(row) != len(columns)
                   or not all(isinstance(value, str) and value.strip() for value in row) for row in rows)):
        raise ValueError("core_associations 每行须按四关联矩阵提供六列非空文本")
    headings = [p for p in document.paragraphs
                if p.text.strip() in {"三、项目专属核心对象", "四、项目专属核心对象"}]
    if len(headings) != 1:
        raise ValueError("高企母版缺少项目专属核心对象章节")
    heading = headings[0]
    table = document.add_table(rows=1, cols=len(columns))
    table.style = "Table Grid"
    for cell, value in zip(table.rows[0].cells, columns, strict=True):
        _set_cell_text(cell, value)
    for values in rows:
        for cell, value in zip(table.add_row().cells, values, strict=True):
            _set_cell_text(cell, value)
    heading._p.addnext(table._tbl)
    _lock_table_pagination(table)


def _remove_authoring_guidance(document: Document) -> None:
    # These master-only instructions are not customer-facing report findings.
    headings = {"2.1 政策原文摘录规则", "4.2 得分解释", "6.2 任务排序"}
    removing = False
    for paragraph in list(document.paragraphs):
        if paragraph.style.name.startswith("Heading"):
            removing = paragraph.text.strip() in headings
        if removing:
            paragraph._p.getparent().remove(paragraph._p)
    for table in list(document.tables):
        if len(table.rows) == 1 and len(table.rows[0].cells) == 1:
            label = table.cell(0, 0).text.split("\n", 1)[0].strip()
            if label in {"使用说明", "判定规则", "项目路由", "专项要求"}:
                table._tbl.getparent().remove(table._tbl)


def _generic_fill(document: Document, fixture: dict[str, Any], placeholders: re.Pattern[str]) -> None:
    source_name = primary_source_name(fixture)
    for paragraph in _iter_paragraphs(document):
        if paragraph._p.findall(".//" + qn("w:fldChar")) or paragraph._p.findall(".//" + qn("w:instrText")):
            for run in paragraph.runs:
                value = _replace_training_text(
                    run.text,
                    fixture,
                    str(fixture.get("release_tag") or "V1.6.5.2"),
                )
                if value != run.text:
                    run.text = value
            continue
        original = paragraph.text
        value = _replace_training_text(original, fixture, str(fixture.get("release_tag") or "V1.6.5.2"))
        if "□可申报" in value:
            value = str(fixture["conclusion"])
        if "□建议申报" in value:
            value = str(fixture["conclusion"])
        value = value.replace("□已核验 □待补", "☐已核验 ☒待补")
        value = value.replace("□已有 □待确认 □待补强", "☐已有 ☒待确认 ☐待补强")
        value = value.replace("□通过 □不通过", "☐通过 ☒不通过")
        # Only replace tokens captured from the blank master, in one pass.
        # Full-width brackets in source text (for example audit document numbers)
        # are content, not placeholders; replacement values must not be rescanned.
        value = placeholders.sub(
            lambda match: _fallback_for_placeholder(match.group(), value, fixture), value
        )
        value = value.replace("待核验", "待企业确认") if "政策" not in value else value
        if value != original:
            _set_text(paragraph, value)
        if "企业提供待核/待补强" in paragraph.text:
            paragraph.text = paragraph.text.replace("企业提供待核/待补强", "待企业确认")
        if "文件、页码或台账" in paragraph.text and placeholders.search(paragraph.text):
            paragraph.text = placeholders.sub(source_name, paragraph.text)


def _set_public_document_metadata(document: Document, fixture: dict[str, Any], report_type: str) -> None:
    properties = document.core_properties
    label = "项目前期评估报告" if report_type == "preassessment" else "项目申报可行性分析报告"
    properties.title = f"{fixture['enterprise']}_{fixture['project_object']}_{label}"
    properties.subject = label
    properties.author = ""
    properties.last_modified_by = ""
    properties.keywords = "政府项目申报,前期评估"
    properties.category = "政府项目咨询报告"
    properties.comments = ""


def _set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        tc_pr.append(shading)
    shading.set(qn("w:fill"), fill)


def _set_cell_text(cell, value: str, *, centered: bool = False) -> None:
    cell.text = value
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if centered else WD_ALIGN_PARAGRAPH.LEFT
        for run in paragraph.runs:
            run.font.size = Pt(8)


def _add_hyperlink(paragraph, label: str, url: str) -> None:
    relation_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relation_id)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    properties.append(color)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(underline)
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "16")
    properties.append(size)
    text = OxmlElement("w:t")
    text.text = label
    run.append(properties)
    run.append(text)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _append_source_ledger(document: Document, fixture: dict[str, Any]) -> None:
    document.add_heading("附录 C、数据来源", level=1)
    table = document.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    headers = ["序号", "文件名称", "链接"]
    for index, value in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = value
        _set_cell_shading(cell, "A51C30")
        for run in cell.paragraphs[0].runs:
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.bold = True
            run.font.size = Pt(8)
    for index, source in enumerate(fixture["_validated_sources"], start=1):
        cells = table.add_row().cells
        _set_cell_text(cells[0], str(index), centered=True)
        _set_cell_text(cells[1], source["name"])
        reference = source["public_source"]
        if reference["url"] is None:
            _set_cell_text(cells[2], str(reference["label"]))
        else:
            _set_cell_text(cells[2], "")
            _add_hyperlink(cells[2].paragraphs[0], str(reference["label"]), str(reference["url"]))


def document_text(document: Document) -> str:
    return "\n".join(paragraph.text for paragraph in _iter_paragraphs(document))


def _write_completed_report(template_path, output_path, validated, report_type, release_tag,
                            output_bytes, text, placeholders, *, project_id=None):
    if report_type == "feasibility" and re.search(r"预计(?:评分|得分)|评分维度|现行条件或完整评分表", text):
        raise ReportInputError("可行性成稿仍有旧评估栏位，请使用已更新母版和缺陷数据",
                               "report-template-defect-columns", ["template"])
    errors: list[str] = []
    if placeholders.search(text):
        errors.append("仍存在方括号填写占位符")
    for marker in TRAINING_MARKERS:
        if marker in text:
            errors.append(f"仍存在培训标记:{marker}")
    for marker in INTERNAL_DRAFT_MARKERS:
        if marker in text:
            errors.append(f"仍存在内部候选标记:{marker}")
    if str(validated["enterprise"]) not in text:
        errors.append("成稿缺企业名称")
    if normalize_text(str(validated["project_object"])) not in normalize_text(text):
        errors.append("成稿缺项目核心对象")
    if "数据来源" not in text:
        errors.append("成稿缺资料来源台账")
    if PUBLIC_DIGEST.search(text):
        errors.append("对外成稿不得展示内部文件校验值")
    if errors:
        raise ValueError("成稿校验失败:" + "；".join(errors))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb" if output_path == template_path else "xb") as output:
        output.write(output_bytes)
    result = {
        "schema": "completed-project-report/v1",
        "status": "pass",
        "release_tag": release_tag,
        "project_id": validated["project_id"] if project_id is None else project_id,
        "report_type": report_type,
        "delivery_profile": "sme-action-report" if validated.get("report_layout") == "sme-action" else (
            "project-presale-assessment-report" if report_type == "preassessment"
            else "project-feasibility-analysis-report"
        ),
        "enterprise": validated["enterprise"],
        "template_path": str(template_path),
        "template_sha256": sha256_file(template_path),
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "source_count": len(validated["_validated_sources"]),
        "report_stage": "draft" if validated["_input_warnings"] else "unclassified",
        "warnings": validated["_input_warnings"],
        "source_receipts": [
            {"name": item["name"], "sha256": item["sha256"], "anchor_count": len(item["anchors"])}
            for item in validated["_validated_sources"]
        ],
        "errors": [],
    }
    receipt = output_path.with_suffix(".completion.json")
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**result, "receipt_path": str(receipt)}


def complete_report(
    *,
    template_path: Path,
    output_path: Path,
    fixture: dict[str, Any],
    report_type: str,
    release_tag: str,
    public_root: Path | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    if report_type not in REPORT_TYPES:
        raise ValueError(f"未知报告类型:{report_type}")
    template_path = template_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if output_path.suffix.lower() not in {".docx", ".html"}:
        raise ValueError("报告输出仅支持 .docx 或供本地 PDF 渲染的 .html")
    if not template_path.is_file():
        raise FileNotFoundError(template_path)
    if output_path.exists() and output_path != template_path:
        raise FileExistsError(f"拒绝覆盖现有文件:{output_path}")
    feasibility = report_type == "feasibility"
    hightech_word = (feasibility and fixture["project_id"] == "high-tech-enterprise"
                     and template_path.suffix.lower() == output_path.suffix.lower() == ".docx")
    validated = validate_case_fixture(
        {**fixture, "release_tag": release_tag},
        expected_project_id=str(fixture["project_id"]),
        public_root=public_root,
        feasibility=feasibility,
        hightech_word=hightech_word,
    )
    layout = fixture.get("report_layout")
    if layout not in {None, "sme-action"}:
        raise ValueError(f"未知报告布局:{layout}")
    if layout != "sme-action":
        validated["table_content"] = report_table_entries(validated, feasibility=feasibility, hightech_word=hightech_word)
    if template_path.suffix.lower() == ".html":
        if output_path.suffix.lower() != ".html":
            raise ValueError("HTML 报告模板只生成 HTML；申请书使用独立 Word 回填操作")
        from direct_html_report import render_report
        source_html, text, placeholders = render_report(template_path, validated, report_type, release_tag)
        return _write_completed_report(template_path, output_path, validated, report_type, release_tag,
                                       source_html.encode("utf-8"), text, placeholders, project_id=project_id)
    if layout == "sme-action":
        from sme_action_report import build_action_document
        document = build_action_document(template_path, validated)
    else:
        document = Document(template_path)
    template_tokens = set(PLACEHOLDER.findall(document_text(document)))
    placeholders = re.compile("|".join(re.escape(token) for token in sorted(template_tokens)) or r"(?!)")
    if layout != "sme-action":
        for table in document.tables:
            _fill_table_by_header(table, validated, feasibility, hightech_word=hightech_word)
            _lock_table_pagination(table)
        _fill_project_specific_paragraphs(document, validated)
        _generic_fill(document, validated, placeholders)
        _fill_table_content(document, validated)
        _fill_hightech_associations(document, validated)
        _remove_authoring_guidance(document)
    _append_source_ledger(document, validated)
    if normalize_text(str(validated["project_object"])) not in normalize_text(document_text(document)):
        document.add_paragraph(f"项目核心对象：{validated['project_object']}")
    if validated["_input_warnings"]:
        document.add_heading("初稿说明与待补事项", level=1)
        for warning in dict.fromkeys(validated["_input_warnings"]):
            document.add_paragraph(warning)
    if layout == "sme-action":
        for paragraph in document.paragraphs:
            if paragraph.text == "附录 C、数据来源":
                _set_text(paragraph, "数据来源")
        for cell in document.tables[-1].rows[0].cells:
            _set_cell_shading(cell, "233D66")
        for section in document.sections:
            for container in (section.header, section.footer, section.first_page_header,
                              section.first_page_footer, section.even_page_header,
                              section.even_page_footer):
                for node in container._element.iter(qn("w:t")):
                    if node.text:
                        node.text = _replace_training_text(node.text, validated, release_tag)
        for policy in validated["policies"]:
            paragraph = document.add_paragraph(str(policy["title"]) + "，" + str(policy["locator"]))
            if str(policy.get("url", "")).startswith("https://"):
                _add_hyperlink(paragraph, " 官方原文", policy["url"])
    _lock_table_pagination(document.tables[-1])
    _apply_report_fonts(document)
    _preserve_report_pagination(document)
    _set_public_document_metadata(document, validated, report_type)
    if layout == "sme-action":
        document.core_properties.title = f"{validated['enterprise']}_专精特新申报体检与培育建议报告"
    serialized = BytesIO()
    document.save(serialized)
    serialized.seek(0)
    rendered = Document(serialized)
    if hightech_word:
        tables = [table for table in rendered.tables if table.rows
                  and table_header_key([cell.text for cell in table.rows[0].cells]) == CONDITION_COLUMNS]
        if len(tables) != 1:
            raise ReportInputError(f"高企 Word 成稿应有一张门槛表，实际 {len(tables)} 张",
                                   "report-condition-rows", ["template"])
        _verify_condition_rows([[cell.text for cell in row.cells] for row in tables[0].rows[1:]],
                               _hightech_condition_rows(validated))
        for table in rendered.tables:
            if table.rows and table_header_key([cell.text for cell in table.rows[0].cells]) == DEFECT_COLUMNS:
                _check_hightech_defects([[cell.text for cell in row.cells] for row in table.rows[1:]])
    text = document_text(rendered)
    if output_path.suffix.lower() == ".html":
        from report_html import report_html
        output_bytes = report_html(rendered).encode("utf-8")
    else:
        output_bytes = serialized.getvalue()
    return _write_completed_report(template_path, output_path, validated, report_type, release_tag,
                                   output_bytes, text, placeholders, project_id=project_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--report-type", choices=sorted(REPORT_TYPES), required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--public-root", type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.expanduser().resolve().read_text(encoding="utf-8-sig"))
    try:
        result = complete_report(
            template_path=args.template,
            output_path=args.output,
            fixture=fixture,
            report_type=args.report_type,
            release_tag=args.release_tag,
            public_root=args.public_root.expanduser().resolve() if args.public_root else None,
        )
    except ReportInputError as error:
        print(json.dumps({"status": "fail", "errors": [str(error)], "input_rejection": error.input_rejection},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

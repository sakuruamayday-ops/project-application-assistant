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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


PLACEHOLDER = re.compile(r"［[^］\r\n]{1,120}］")
TRAINING_MARKERS = ("培训模板", "培训说明", "灰色提示文字")
REPORT_TYPES = {"preassessment", "feasibility"}
EVIDENCE_STATES = {
    "已具备",
    "企业提供待核",
    "待企业确认",
    "当前检索层未命中",
    "明确未具备",
    "存在差距",
    "冲突待核",
    "不适用",
}
PORTABLE_CJK_FONT = "Hiragino Sans GB"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


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


def validate_case_fixture(
    fixture: dict[str, Any],
    *,
    expected_project_id: str | None = None,
    public_root: Path | None = None,
) -> dict[str, Any]:
    required = {
        "project_id",
        "enterprise",
        "project_object",
        "suggested_year",
        "deadline",
        "conclusion",
        "conclusion_basis",
        "primary_gap",
        "next_action",
        "materials",
        "policies",
    }
    missing = sorted(required - set(fixture))
    if missing:
        raise ValueError("客户夹具缺字段:" + ",".join(missing))
    project_id = str(fixture["project_id"]).strip()
    if expected_project_id and project_id != expected_project_id:
        raise ValueError(f"项目路由与夹具不一致:{expected_project_id}/{project_id}")
    if not str(fixture["enterprise"]).strip():
        raise ValueError("企业名称不得为空")
    materials = fixture.get("materials")
    if not isinstance(materials, list) or not materials:
        raise ValueError("每类项目至少需要一份真实客户资料")
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
            }
        )
    policies = fixture.get("policies")
    if not isinstance(policies, list) or not policies:
        raise ValueError("夹具必须至少锁定一项政策基线")
    for policy in policies:
        if not isinstance(policy, dict) or not str(policy.get("title") or "").strip():
            raise ValueError("政策基线缺文件名称")
        if not str(policy.get("locator") or "").strip():
            raise ValueError("政策基线缺原文位置或官方链接")
    for condition in fixture.get("conditions", []):
        state = str(condition.get("state") or "待企业确认")
        if state not in EVIDENCE_STATES:
            raise ValueError(f"不受控的证据状态:{state}")
    return {**fixture, "_validated_sources": normalized_sources}


def _set_text(paragraph, value: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = value
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(value)


def _apply_portable_cjk_font(document: Document) -> None:
    """Bind visible text to a macOS CJK font before PDF visual regression."""
    for paragraph in _iter_paragraphs(document):
        for run in paragraph.runs:
            if not run.text:
                continue
            run.font.name = PORTABLE_CJK_FONT
            run_properties = run._element.get_or_add_rPr()
            fonts = run_properties.get_or_add_rFonts()
            for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                fonts.set(qn(f"w:{attribute}"), PORTABLE_CJK_FONT)


def _iter_paragraphs(document: Document) -> Iterable[Any]:
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _replace_training_text(value: str, fixture: dict[str, Any], release_tag: str) -> str:
    replacements = {
        f"{release_tag} 培训模板": f"{release_tag} 真实客户资料候选验收稿",
        "V1.6.5.1 培训模板": f"{release_tag} 真实客户资料候选验收稿",
        "企业名称：［填写］": f"企业名称：{fixture['enterprise']}",
        "报告日期：［填写］": f"报告日期：{fixture.get('report_date') or date.today().isoformat()}",
        "顾问：［填写］": f"顾问：{fixture.get('advisor') or '共创研究院'}",
        "灰色提示文字为培训说明，正式交付前应替换或删除。": "本稿已按真实客户资料回填，未取得的企业数据统一标注待企业确认。",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _fallback_for_placeholder(token: str, context: str, fixture: dict[str, Any]) -> str:
    hint = token.strip("［］")
    combined = context + hint
    primary_source = fixture["_validated_sources"][0]["name"]
    if any(word in combined for word in ("截止", "官方时间")):
        return str(fixture["deadline"])
    if any(word in combined for word in ("申报年度", "完成年度")):
        return str(fixture["suggested_year"])
    if any(word in combined for word in ("产品", "申报对象")):
        return str(fixture["project_object"])
    if any(word in combined for word in ("文件、页码", "文件或台账", "证据", "来源")):
        return primary_source
    if any(word in combined for word in ("责任人", "核验人", "复核人")):
        return str(fixture.get("owner") or "企业项目负责人")
    if any(word in combined for word in ("完成节点", "建议时间", "年度/季度", "截止日")):
        return str(fixture.get("target_period") or f"{fixture['suggested_year']}年申报前")
    if any(word in combined for word in ("具体动作", "补强动作", "后续动作", "下一步")):
        return str(fixture["next_action"])
    if any(word in combined for word in ("差距", "短板")):
        return str(fixture["primary_gap"])
    if any(word in combined for word in ("评分", "预计得分", "确定分", "条件分", "满分")):
        return "待锁定当期评分表"
    if any(word in combined for word in ("数据", "企业值", "现状", "已知")):
        return str(fixture.get("headline_fact") or "当前资料未提供可复算数据")
    if any(word in combined for word in ("状态", "已具备/待")):
        return "待企业确认"
    if any(word in combined for word in ("口径", "统计期间")):
        return "以申报年度通知及企业专项底稿为准"
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
        if key and (key in normalized or normalized in key):
            matches.append((len(key), item))
    return max(matches, default=(0, None), key=lambda pair: pair[0])[1]


def _fill_policy_table(table, fixture: dict[str, Any], feasibility: bool) -> None:
    policies = fixture["policies"]
    for index, row in enumerate(table.rows[1:]):
        policy = policies[min(index, len(policies) - 1)]
        cells = row.cells
        if len(cells) == 4:
            cells[1].text = str(policy["title"])
            cells[2].text = str(policy["locator"])
            cells[3].text = str(policy.get("status") or "已锁定基线")
        elif len(cells) >= 5:
            cells[1].text = str(policy["title"])
            cells[2].text = str(policy.get("scope") or "以通知和附件适用范围为准")
            cells[3].text = str(policy["locator"])
            cells[4].text = str(fixture.get("advisor") or "共创研究院")


def _fill_summary_table(table, fixture: dict[str, Any], feasibility: bool) -> None:
    for row in table.rows[1:]:
        key = row.cells[0].text.strip()
        if "当前可行性" in key:
            row.cells[1].text = str(fixture["conclusion"])
            row.cells[2].text = str(fixture["conclusion_basis"])
        elif "申报结论" in key:
            row.cells[1].text = str(fixture["conclusion"])
            row.cells[2].text = str(fixture["conclusion_basis"])
        elif "建议申报年度" in key:
            row.cells[1].text = str(fixture["suggested_year"])
            row.cells[2].text = str(fixture.get("year_basis") or "结合当期窗口、证据完整度和补强周期")
        elif "申报层级" in key or "档次" in key:
            row.cells[1].text = str(fixture.get("level") or "待企业确认适用层级")
            row.cells[2].text = str(fixture.get("level_basis") or "以项目属地和当期申报表为准")
        elif "首要短板" in key:
            row.cells[1].text = str(fixture["primary_gap"])
            row.cells[2].text = str(fixture["next_action"])
        elif "预计满足硬门槛" in key:
            row.cells[1].text = str(fixture.get("gate_summary") or "待企业补齐数据后复算")
            row.cells[2].text = "按当期通知原文逐条确认"
        elif "预计评分" in key:
            row.cells[1].text = str(fixture.get("score") or "不估分")
            row.cells[2].text = str(fixture.get("score_basis") or "当期完整评分表或企业数据未闭合")
        elif "关键前置任务" in key:
            row.cells[1].text = str(fixture["next_action"])
            row.cells[2].text = str(fixture.get("target_period") or f"{fixture['suggested_year']}年申报前")


def _fill_condition_table(table, fixture: dict[str, Any], feasibility: bool) -> None:
    primary_source = fixture["_validated_sources"][0]["name"]
    for row in table.rows[1:]:
        cells = row.cells
        condition = cells[0].text.strip()
        match = _condition_match(fixture, condition) or {}
        value = str(match.get("value") or "当前资料未提供可复算数据")
        state = str(match.get("state") or "待企业确认")
        gap = str(match.get("gap") or "数据和证据尚未闭合")
        action = str(match.get("action") or fixture["next_action"])
        if len(cells) == 5:
            cells[1].text = value
            cells[2].text = state
            cells[3].text = gap
            cells[4].text = action
        elif len(cells) >= 7:
            cells[1].text = value
            cells[2].text = str(match.get("source") or primary_source)
            cells[3].text = state
            cells[4].text = str(match.get("fixed_score") or "不计分")
            cells[5].text = str(match.get("conditional_score") or "不计分")
            cells[6].text = gap


def _fill_path_table(table, fixture: dict[str, Any]) -> None:
    for row in table.rows[1:]:
        cells = row.cells
        if len(cells) >= 5:
            cells[1].text = str(fixture["suggested_year"])
            cells[2].text = str(fixture["deadline"])
            cells[3].text = str(fixture.get("window_status") or "按报告基准日核验")
            cells[4].text = str(fixture["next_action"])


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


def _fill_table_by_header(table, fixture: dict[str, Any], feasibility: bool) -> None:
    if not table.rows:
        return
    header = " | ".join(cell.text.strip() for cell in table.rows[0].cells)
    if "政策层级" in header and ("现行文件" in header or "文件名称与文号" in header):
        _fill_policy_table(table, fixture, feasibility)
    elif "判断项" in header and "一句话依据" in header:
        _fill_summary_table(table, fixture, feasibility)
    elif "事项" in header and "依据及限制" in header:
        _fill_summary_table(table, fixture, feasibility)
    elif "现行条件 | 企业值" in header:
        _fill_condition_table(table, fixture, feasibility)
    elif "现行条件或评分项" in header:
        _fill_condition_table(table, fixture, feasibility)
    elif "项目 | 申报年度 | 申报截止日期" in header:
        _fill_path_table(table, fixture)


def _generic_fill(document: Document, fixture: dict[str, Any]) -> None:
    source_name = fixture["_validated_sources"][0]["name"]
    for paragraph in _iter_paragraphs(document):
        original = paragraph.text
        value = _replace_training_text(original, fixture, str(fixture.get("release_tag") or "V1.6.5.2"))
        if "□可申报" in value:
            value = str(fixture["conclusion"])
        if "□建议申报" in value:
            value = str(fixture["conclusion"])
        value = value.replace("□已核验 □待补", "☐已核验 ☒待补")
        value = value.replace("□已有 □待确认 □待补强", "☐已有 ☒待确认 ☐待补强")
        value = value.replace("□通过 □不通过", "☐通过 ☒不通过")
        while True:
            match = PLACEHOLDER.search(value)
            if not match:
                break
            value = value[: match.start()] + _fallback_for_placeholder(match.group(), value, fixture) + value[match.end() :]
        value = value.replace("待核验", "待企业确认") if "政策" not in value else value
        if value != original:
            _set_text(paragraph, value)
        if "企业提供待核/待补强" in paragraph.text:
            paragraph.text = paragraph.text.replace("企业提供待核/待补强", "待企业确认")
        if "文件、页码或台账" in paragraph.text and PLACEHOLDER.search(paragraph.text):
            paragraph.text = PLACEHOLDER.sub(source_name, paragraph.text)


def _set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        tc_pr.append(shading)
    shading.set(qn("w:fill"), fill)


def _declare_repeating_table_headers(document: Document) -> None:
    """Make every first table row repeat in Word/PDF page flows."""
    for table in document.tables:
        if not table.rows:
            continue
        properties = table.rows[0]._tr.get_or_add_trPr()
        if properties.find(qn("w:tblHeader")) is None:
            header = OxmlElement("w:tblHeader")
            header.set(qn("w:val"), "true")
            properties.append(header)


def _set_delivery_metadata(document: Document, fixture: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    author = str(fixture.get("advisor") or "共创研究院")
    properties = document.core_properties
    properties.author = author
    properties.last_modified_by = author
    properties.created = now
    properties.modified = now
    properties.title = f"{fixture['enterprise']}项目申报咨询报告"
    properties.subject = str(fixture["project_object"])
    properties.keywords = "政府项目申报,前期评估,可行性分析,证据台账"


def _append_source_ledger(document: Document, fixture: dict[str, Any]) -> None:
    document.add_heading("数据来源", level=1)
    document.add_paragraph("附录 C、资料来源与证据状态")
    paragraph = document.add_paragraph(
        "本附录只列文件名、校验值和已命中原文锚点，不在公共候选包中保存客户原文或本机绝对路径。"
    )
    paragraph.style = document.styles["Normal"]
    table = document.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    headers = ["序号", "资料名称", "资料作用", "SHA-256", "原文锚点"]
    for index, value in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = value
        _set_cell_shading(cell, "A51C30")
        for run in cell.paragraphs[0].runs:
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.bold = True
            run.font.size = Pt(8)
    for index, source in enumerate(fixture["_validated_sources"], start=1):
        document.add_paragraph(
            f"[{index}] {source['name']}；用途：{source['role']}；"
            f"SHA-256：{source['sha256']}；原文锚点：{'；'.join(source['anchors'])}。"
        )
        cells = table.add_row().cells
        values = [
            str(index),
            source["name"],
            source["role"],
            source["sha256"],
            "；".join(source["anchors"]),
        ]
        for cell, value in zip(cells, values):
            cell.text = value
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT if cell is not cells[0] else WD_ALIGN_PARAGRAPH.CENTER
                for run in paragraph.runs:
                    run.font.size = Pt(7.5)
    document.add_paragraph(
        "政策边界：下一次对外交付前重新核验当期通知、附件、补充通知和属地截止时间；未核验数据不得改写为已满足。"
    )


def document_text(document: Document) -> str:
    return "\n".join(paragraph.text for paragraph in _iter_paragraphs(document))


def complete_report(
    *,
    template_path: Path,
    output_path: Path,
    fixture: dict[str, Any],
    report_type: str,
    release_tag: str,
    public_root: Path | None = None,
) -> dict[str, Any]:
    if report_type not in REPORT_TYPES:
        raise ValueError(f"未知报告类型:{report_type}")
    template_path = template_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if not template_path.is_file():
        raise FileNotFoundError(template_path)
    if output_path.exists() and output_path != template_path:
        raise FileExistsError(f"拒绝覆盖现有文件:{output_path}")
    validated = validate_case_fixture(
        {**fixture, "release_tag": release_tag},
        expected_project_id=str(fixture["project_id"]),
        public_root=public_root,
    )
    document = Document(template_path)
    feasibility = report_type == "feasibility"
    for table in document.tables:
        _fill_table_by_header(table, validated, feasibility)
    _fill_project_specific_paragraphs(document, validated)
    _generic_fill(document, validated)
    _append_source_ledger(document, validated)
    _declare_repeating_table_headers(document)
    _set_delivery_metadata(document, validated)
    _apply_portable_cjk_font(document)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)
    rendered = Document(output_path)
    text = document_text(rendered)
    errors: list[str] = []
    if PLACEHOLDER.search(text):
        errors.append("仍存在方括号填写占位符")
    for marker in TRAINING_MARKERS:
        if marker in text:
            errors.append(f"仍存在培训标记:{marker}")
    if str(validated["enterprise"]) not in text:
        errors.append("成稿缺企业名称")
    if str(validated["project_object"]) not in text:
        errors.append("成稿缺项目核心对象")
    if "资料来源与证据状态" not in text:
        errors.append("成稿缺资料来源台账")
    result = {
        "schema": "gongchuang-completed-project-report/v1",
        "status": "pass" if not errors else "fail",
        "release_tag": release_tag,
        "project_id": validated["project_id"],
        "report_type": report_type,
        "enterprise": validated["enterprise"],
        "template_path": str(template_path),
        "template_sha256": sha256_file(template_path),
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "source_count": len(validated["_validated_sources"]),
        "source_receipts": [
            {
                "name": item["name"],
                "sha256": item["sha256"],
                "anchor_count": len(item["anchors"]),
            }
            for item in validated["_validated_sources"]
        ],
        "errors": errors,
    }
    receipt = output_path.with_suffix(".completion.json")
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise ValueError("成稿校验失败:" + "；".join(errors))
    return {**result, "receipt_path": str(receipt)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--report-type", choices=sorted(REPORT_TYPES), required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--public-root", type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.expanduser().resolve().read_text(encoding="utf-8"))
    result = complete_report(
        template_path=args.template,
        output_path=args.output,
        fixture=fixture,
        report_type=args.report_type,
        release_tag=args.release_tag,
        public_root=args.public_root.expanduser().resolve() if args.public_root else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

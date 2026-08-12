#!/usr/bin/env python3
"""Fail-closed delivery gate for high-tech application summary DOCX files.

The gate records four immutable stages:
1. template-copy: source template and initial working-copy hashes;
2. summary-lint: compact summary-table structure and prohibited placeholders;
3. record-wps-review: human WPS page review bound to DOCX and screenshot hashes;
4. finalize: final DOCX hash, prior receipts and optional brand-gate evidence.

It does not automate WPS. A reviewer must open the DOCX in WPS Office, inspect every
page, save screenshots, and provide a JSON checklist. Pretending another renderer is
WPS is intentionally impossible because the review payload requires engine="WPS Office".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document


PROHIBITED_SUMMARY_PHRASES = (
    "XXX万元",
    "待核定",
    "待审计",
    "名称详见",
    "指标待实测",
    "项目待补",
    "2026项目",
)
PS_HEADER_GROUPS = {
    "index": ("编号", "序号"),
    "name": ("高新技术产品（服务）名称", "高新技术产品服务名称", "产品（服务）名称"),
    "revenue": ("高新收入", "上年度销售收入"),
    "technology": ("关键技术",),
    "field": ("所属高新领域", "技术领域"),
    "rd": ("对应的RD", "对应RD"),
    "ip": ("知识产权名称", "知识产权编号"),
    "indicator": ("技术指标",),
    "proof": ("证明材料",),
}
RESULT_HEADER_GROUPS = {
    "index": ("序号", "编号"),
    "name": ("成果名称",),
    "source": ("成果来源",),
    "method": ("转化方式",),
    "target": ("转化目标产品",),
    "time": ("转化时间",),
    "technology": ("涉及关键技术",),
    "effect": ("转化所取得成效",),
    "rd": ("关联项目RD编号", "关联RD编号"),
    "ip": ("关联专利IP编号", "关联IP编号"),
    "proof": ("成果转化证明材料", "转化证明材料"),
}
IP_HEADER_GROUPS = {
    "index": ("知识产权编号", "IP编号"),
    "name": ("知识产权名称",),
    "category": ("类别", "知识产权类别"),
    "date": ("授权日期", "登记日期", "授权或登记日期"),
    "number": ("授权号", "登记号", "授权或登记号"),
    "method": ("获得方式", "取得方式"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        prefix = handle.read(24)
    if len(prefix) < 24 or not prefix.startswith(b"\x89PNG\r\n\x1a\n") or prefix[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", prefix[16:24])


def normalized(value: str) -> str:
    return re.sub(r"[\s\u3000（）()：:、，,。.;；/\\_-]+", "", value).casefold()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON不可读取：{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON顶层必须是对象：{path}")
    return data


def receipt(stage: str, status: str, **values: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "gate": "hightech-application-delivery",
        "stage": stage,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **values,
    }


def table_headers(table) -> list[str]:
    if not table.rows:
        return []
    return [cell.text.strip() for cell in table.rows[0].cells]


def header_mapping(headers: list[str], groups: dict[str, tuple[str, ...]]) -> dict[str, int] | None:
    header_values = [normalized(value) for value in headers]
    mapping: dict[str, int] = {}
    for key, aliases in groups.items():
        match = next(
            (
                index
                for index, header in enumerate(header_values)
                if any(normalized(alias) in header for alias in aliases)
            ),
            None,
        )
        if match is None:
            return None
        mapping[key] = match
    return mapping


def nonempty_rows(table) -> list[Any]:
    return [row for row in table.rows[1:] if any(cell.text.strip() for cell in row.cells)]


def cell_text(row, index: int) -> str:
    return row.cells[index].text.strip()


def audit_ps_table(table, mapping: dict[str, int], table_index: int) -> dict[str, Any]:
    issues: list[str] = []
    rows = nonempty_rows(table)
    if not rows:
        issues.append("汇总表没有已填写数据行")
    numbers: list[int] = []
    for row_number, row in enumerate(rows, 1):
        index_text = cell_text(row, mapping["index"])
        match = re.fullmatch(r"\s*(\d+)\s*[、.]?\s*", index_text)
        if match:
            numbers.append(int(match.group(1)))
        else:
            issues.append(f"第{row_number}项编号不是整数：{index_text!r}")
        row_text = "\n".join(cell.text for cell in row.cells)
        for phrase in PROHIBITED_SUMMARY_PHRASES:
            if phrase.casefold() in row_text.casefold():
                issues.append(f"第{row_number}项含禁用占位语：{phrase}")
        revenue = cell_text(row, mapping["revenue"])
        if revenue and not re.search(r"\d", revenue):
            issues.append(f"第{row_number}项高新收入非数值且未留空：{revenue}")
        technology = cell_text(row, mapping["technology"])
        if len(technology.replace("\n", "")) > 180:
            issues.append(f"第{row_number}项关键技术超过180字，疑似误填PS正文")
        field = cell_text(row, mapping["field"])
        if field and not re.search(r"(?:^|[—/])\s*\d+[、.]", field):
            issues.append(f"第{row_number}项所属领域未显示四级末级编号")
        indicator = cell_text(row, mapping["indicator"])
        if indicator and not re.search(r"\d", indicator):
            issues.append(f"第{row_number}项技术指标缺少数值")
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        issues.append(f"序号不连续：{numbers}")
    return {
        "kind": "ps-summary",
        "table_index": table_index,
        "row_count": len(rows),
        "numbers": numbers,
        "issues": issues,
    }


def audit_result_table(table, mapping: dict[str, int], table_index: int) -> dict[str, Any]:
    issues: list[str] = []
    rows = nonempty_rows(table)
    if not rows:
        issues.append("汇总表没有已填写数据行")
    numbers: list[int] = []
    for row_number, row in enumerate(rows, 1):
        index_text = cell_text(row, mapping["index"])
        match = re.fullmatch(r"\s*(\d+)\s*[、.]?\s*", index_text)
        if match:
            numbers.append(int(match.group(1)))
        else:
            issues.append(f"第{row_number}项编号不是整数：{index_text!r}")
        row_text = "\n".join(cell.text for cell in row.cells)
        for phrase in PROHIBITED_SUMMARY_PHRASES:
            if phrase.casefold() in row_text.casefold():
                issues.append(f"第{row_number}项含禁用占位语：{phrase}")
        for key, limit in (("technology", 180), ("effect", 240)):
            value = cell_text(row, mapping[key])
            if len(value.replace("\n", "")) > limit:
                issues.append(f"第{row_number}项{key}超过{limit}字，疑似误填正文")
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        issues.append(f"序号不连续：{numbers}")
    return {
        "kind": "achievement-summary",
        "table_index": table_index,
        "row_count": len(rows),
        "numbers": numbers,
        "issues": issues,
    }


def audit_ip_table(table, mapping: dict[str, int], table_index: int) -> dict[str, Any]:
    issues: list[str] = []
    rows = nonempty_rows(table)
    if not rows:
        issues.append("汇总表没有已填写数据行")
    numbers: list[int] = []
    for row_number, row in enumerate(rows, 1):
        index_text = cell_text(row, mapping["index"])
        match = re.fullmatch(r"\s*IP\s*0*(\d+)\s*", index_text, re.IGNORECASE)
        if match:
            numbers.append(int(match.group(1)))
        else:
            issues.append(f"第{row_number}项知识产权编号格式错误：{index_text!r}")
        row_text = "\n".join(cell.text for cell in row.cells)
        for phrase in PROHIBITED_SUMMARY_PHRASES:
            if phrase.casefold() in row_text.casefold():
                issues.append(f"第{row_number}项含禁用占位语：{phrase}")
        name = cell_text(row, mapping["name"])
        if len(name.replace("\n", "")) > 100:
            issues.append(f"第{row_number}项知识产权名称超过100字，疑似追加说明正文")
        category = cell_text(row, mapping["category"])
        if not category:
            issues.append(f"第{row_number}项知识产权类别为空")
        method = cell_text(row, mapping["method"])
        if method and method not in {"自主研发", "受让", "受赠", "并购", "独占许可", "其他"}:
            issues.append(f"第{row_number}项取得方式不在标准口径内：{method}")
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        issues.append(f"IP编号不连续：{numbers}")
    return {
        "kind": "ip-summary",
        "table_index": table_index,
        "row_count": len(rows),
        "numbers": numbers,
        "issues": issues,
    }


def command_template_copy(args: argparse.Namespace) -> int:
    errors: list[str] = []
    if not args.template.is_file():
        errors.append(f"模板不存在：{args.template}")
    if not args.working.is_file():
        errors.append(f"工作副本不存在：{args.working}")
    if not errors and args.template.resolve() == args.working.resolve():
        errors.append("模板与工作副本不得为同一路径")
    template_hash = sha256(args.template) if args.template.is_file() else None
    working_hash = sha256(args.working) if args.working.is_file() else None
    if not errors and template_hash != working_hash:
        errors.append("初始工作副本不是模板的字节级复制；请先复制母版再开始填写")
    payload = receipt(
        "template-copy",
        "pass" if not errors else "fail",
        template={"path": str(args.template.resolve()), "sha256": template_hash},
        working_copy={"path": str(args.working.resolve()), "sha256": working_hash},
        errors=errors,
    )
    atomic_json(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def command_summary_lint(args: argparse.Namespace) -> int:
    document = Document(args.docx)
    found: list[dict[str, Any]] = []
    for index, table in enumerate(document.tables, 1):
        headers = table_headers(table)
        ps_mapping = header_mapping(headers, PS_HEADER_GROUPS)
        result_mapping = header_mapping(headers, RESULT_HEADER_GROUPS)
        ip_mapping = header_mapping(headers, IP_HEADER_GROUPS)
        if ip_mapping:
            found.append(audit_ip_table(table, ip_mapping, index))
        elif ps_mapping:
            found.append(audit_ps_table(table, ps_mapping, index))
        elif result_mapping:
            found.append(audit_result_table(table, result_mapping, index))
    issues = [issue for table in found for issue in table["issues"]]
    achievement_tables = [item for item in found if item["kind"] == "achievement-summary"]
    if len(achievement_tables) > 1:
        issues.append(
            f"科技成果转化汇总表被拆成{len(achievement_tables)}张表；必须保持一张连续表并自然跨页"
        )
    if not found:
        issues.append("未识别到受支持的高新产品或科技成果转化汇总表表头，禁止跳过字段粒度检查")
    payload = receipt(
        "summary-lint",
        "pass" if not issues else "fail",
        docx={"path": str(args.docx.resolve()), "sha256": sha256(args.docx)},
        tables=found,
        issues=issues,
    )
    atomic_json(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not issues else 2


def command_record_wps_review(args: argparse.Namespace) -> int:
    checklist = load_json(args.checklist)
    errors: list[str] = []
    if checklist.get("engine") != "WPS Office":
        errors.append('checklist.engine必须精确为"WPS Office"')
    page_count = checklist.get("page_count")
    pages = checklist.get("pages")
    if not isinstance(page_count, int) or page_count < 1:
        errors.append("page_count必须是正整数")
    if not isinstance(pages, list):
        errors.append("pages必须是数组")
        pages = []
    page_numbers = [item.get("page") for item in pages if isinstance(item, dict)]
    if isinstance(page_count, int) and page_numbers != list(range(1, page_count + 1)):
        errors.append(f"逐页清单不连续或不完整：{page_numbers}")
    required_checks = {
        "header_footer",
        "table_boundaries",
        "repeated_header",
        "overflow",
        "overlap",
        "blank_page",
        "continuous_numbering",
        "missing_fields",
    }
    page_evidence: list[dict[str, Any]] = []
    for item in pages:
        if not isinstance(item, dict):
            errors.append("pages中的每项必须是对象")
            continue
        checks = item.get("checks")
        if not isinstance(checks, dict) or any(checks.get(name) != "pass" for name in required_checks):
            errors.append(f"第{item.get('page')}页检查项未全部通过")
        screenshot_value = item.get("screenshot")
        if not isinstance(screenshot_value, str):
            errors.append(f"第{item.get('page')}页缺少截图路径")
            continue
        screenshot = (args.checklist.parent / screenshot_value).resolve()
        if not screenshot.is_file():
            errors.append(f"第{item.get('page')}页截图不存在：{screenshot}")
            continue
        dimensions = png_dimensions(screenshot)
        if dimensions is None:
            errors.append(f"第{item.get('page')}页截图不是有效PNG图像：{screenshot}")
            continue
        if dimensions[0] < 640 or dimensions[1] < 480:
            errors.append(
                f"第{item.get('page')}页截图分辨率过低：{dimensions[0]}×{dimensions[1]}，至少640×480"
            )
            continue
        page_evidence.append(
            {
                "page": item.get("page"),
                "path": str(screenshot),
                "sha256": sha256(screenshot),
                "width": dimensions[0],
                "height": dimensions[1],
            }
        )
    screenshot_hashes = [item["sha256"] for item in page_evidence]
    if len(screenshot_hashes) != len(set(screenshot_hashes)):
        errors.append("不同页重复使用了同一张截图")
    payload = receipt(
        "wps-review",
        "pass" if not errors else "fail",
        docx={"path": str(args.docx.resolve()), "sha256": sha256(args.docx)},
        engine=checklist.get("engine"),
        reviewer=checklist.get("reviewer"),
        page_count=page_count,
        pages=page_evidence,
        checklist={"path": str(args.checklist.resolve()), "sha256": sha256(args.checklist)},
        errors=errors,
    )
    atomic_json(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def validate_bound_receipt(
    label: str, path: Path, expected_stage: str, docx_hash: str | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        value = load_json(path)
    except ValueError as exc:
        return None, [str(exc)]
    if value.get("stage") != expected_stage or value.get("status") != "pass":
        errors.append(f"{label}不是通过状态的{expected_stage}回执")
    if docx_hash is not None and value.get("docx", {}).get("sha256") != docx_hash:
        errors.append(f"{label}绑定的DOCX哈希与当前终稿不一致")
    return value, errors


def command_finalize(args: argparse.Namespace) -> int:
    errors: list[str] = []
    current_hash = sha256(args.docx)
    copy_value, copy_errors = validate_bound_receipt("模板复制回执", args.copy_receipt, "template-copy")
    lint_value, lint_errors = validate_bound_receipt(
        "字段粒度回执", args.summary_receipt, "summary-lint", current_hash
    )
    wps_value, wps_errors = validate_bound_receipt(
        "WPS验收回执", args.wps_receipt, "wps-review", current_hash
    )
    errors.extend(copy_errors + lint_errors + wps_errors)
    if wps_value:
        for page in wps_value.get("pages", []):
            screenshot = Path(page.get("path", ""))
            if not screenshot.is_file() or sha256(screenshot) != page.get("sha256"):
                errors.append(f"WPS第{page.get('page')}页截图缺失或哈希变化")
    if copy_value:
        template = Path(copy_value.get("template", {}).get("path", ""))
        template_hash = copy_value.get("template", {}).get("sha256")
        initial_working = Path(copy_value.get("working_copy", {}).get("path", ""))
        if initial_working.resolve() != args.docx.resolve():
            errors.append("模板复制回执中的初始工作副本路径不是当前终稿路径")
        if not template.is_file() or sha256(template) != template_hash:
            errors.append("原模板缺失或哈希已变化")
    brand_evidence = None
    if args.brand_receipt:
        brand_evidence = load_json(args.brand_receipt)
        if brand_evidence.get("status") != "passed":
            errors.append("品牌交付闸门未通过")
        artifacts = brand_evidence.get("artifacts", [])
        if not any(Path(item.get("path", "")).resolve() == args.docx.resolve() for item in artifacts if isinstance(item, dict)):
            errors.append("品牌交付闸门回执未绑定当前DOCX路径")
        if args.brand_receipt.stat().st_mtime_ns < args.docx.stat().st_mtime_ns:
            errors.append("品牌交付闸门回执早于当前DOCX修改时间，可能已失效")
    else:
        errors.append("缺少品牌交付闸门JSON回执")
    payload = receipt(
        "finalize",
        "pass" if not errors else "fail",
        docx={"path": str(args.docx.resolve()), "sha256": current_hash},
        template_copy_receipt={"path": str(args.copy_receipt.resolve()), "sha256": sha256(args.copy_receipt)},
        summary_lint_receipt={"path": str(args.summary_receipt.resolve()), "sha256": sha256(args.summary_receipt)},
        wps_review_receipt={"path": str(args.wps_receipt.resolve()), "sha256": sha256(args.wps_receipt)},
        brand_receipt=(
            {"path": str(args.brand_receipt.resolve()), "sha256": sha256(args.brand_receipt)}
            if args.brand_receipt
            else None
        ),
        copy=copy_value,
        summary=lint_value,
        wps=wps_value,
        errors=errors,
    )
    atomic_json(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="高企申请书模板、汇总表、WPS视觉与哈希闭环门禁")
    commands = root.add_subparsers(dest="command", required=True)

    copy_cmd = commands.add_parser("template-copy", help="记录模板字节级复制回执")
    copy_cmd.add_argument("template", type=Path)
    copy_cmd.add_argument("working", type=Path)
    copy_cmd.add_argument("--report", type=Path, required=True)
    copy_cmd.set_defaults(function=command_template_copy)

    lint_cmd = commands.add_parser("summary-lint", help="检查汇总表字段粒度")
    lint_cmd.add_argument("docx", type=Path)
    lint_cmd.add_argument("--report", type=Path, required=True)
    lint_cmd.set_defaults(function=command_summary_lint)

    wps_cmd = commands.add_parser("record-wps-review", help="生成绑定截图和DOCX哈希的WPS逐页回执")
    wps_cmd.add_argument("docx", type=Path)
    wps_cmd.add_argument("checklist", type=Path)
    wps_cmd.add_argument("--report", type=Path, required=True)
    wps_cmd.set_defaults(function=command_record_wps_review)

    final_cmd = commands.add_parser("finalize", help="核对全部回执并生成最终哈希闭环")
    final_cmd.add_argument("docx", type=Path)
    final_cmd.add_argument("--copy-receipt", type=Path, required=True)
    final_cmd.add_argument("--summary-receipt", type=Path, required=True)
    final_cmd.add_argument("--wps-receipt", type=Path, required=True)
    final_cmd.add_argument("--brand-receipt", type=Path)
    final_cmd.add_argument("--report", type=Path, required=True)
    final_cmd.set_defaults(function=command_finalize)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.function(args)


if __name__ == "__main__":
    sys.exit(main())

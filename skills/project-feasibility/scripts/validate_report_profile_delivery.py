#!/usr/bin/env python3
"""Validate a report profile and write a current-turn Stop Hook receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


VALIDATOR_ID = "gongchuang-report-profile/v1"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _default_state_root(plugin_root: Path) -> Path:
    explicit = os.environ.get("GONGCHUANG_BEHAVIOR_STATE_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    plugin_data = os.environ.get("CODEBUDDY_PLUGIN_DATA", "").strip()
    if plugin_data and not plugin_data.startswith("${"):
        return Path(plugin_data).expanduser().resolve() / "behavior-hook"
    resolved = plugin_root.expanduser().resolve()
    plugin_container = resolved.parent
    marketplace = plugin_container.parent
    marketplaces = marketplace.parent
    host_plugins = marketplaces.parent
    host_home = host_plugins.parent
    safe_component = re.compile(r"[A-Za-z0-9._-]{1,128}")
    if (
        plugin_container.name == "plugins"
        and marketplaces.name == "marketplaces"
        and host_plugins.name == "plugins"
        and host_home.name in {".workbuddy", ".codebuddy"}
        and safe_component.fullmatch(resolved.name)
        and safe_component.fullmatch(marketplace.name)
    ):
        return (
            host_plugins
            / "data"
            / f"{resolved.name}-{marketplace.name}"
            / "behavior-hook"
        )
    raise ValueError("无法定位WorkBuddy行为状态目录，请显式传入--state-root")


def _canonical_state_root(plugin_root: Path) -> Path:
    return _default_state_root(plugin_root).expanduser().resolve()


def _docx_blocks(path: Path) -> tuple[list[str], list[list[str]]]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = [
        "".join(node.text or "" for node in paragraph.findall(f".//{{{WORD_NS}}}t")).strip()
        for paragraph in root.findall(f".//{{{WORD_NS}}}p")
    ]
    tables: list[list[str]] = []
    for table in root.findall(f".//{{{WORD_NS}}}tbl"):
        rows: list[str] = []
        for row in table.findall(f"./{{{WORD_NS}}}tr"):
            cells = [
                "".join(node.text or "" for node in cell.findall(f".//{{{WORD_NS}}}t")).strip()
                for cell in row.findall(f"./{{{WORD_NS}}}tc")
            ]
            rows.append(" | ".join(cells))
        if rows:
            tables.append(rows)
    return [item for item in paragraphs if item], tables


def _pdf_text(path: Path) -> str:
    import fitz

    document = fitz.open(path)
    try:
        return "\n".join(page.get_text("text", sort=True) for page in document)
    finally:
        document.close()


def _has_cjk_text(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", value or ""))


_CJK_FONT_MARKERS = (
    "gb18030",
    "heiti",
    "hiragino",
    "kaiti",
    "mingliu",
    "msung",
    "notosanscjk",
    "notoserifcjk",
    "pingfang",
    "simsun",
    "simhei",
    "songti",
    "sourcehansans",
    "sourcehanserif",
    "yahei",
)


def _normalized_font_name(value: str) -> str:
    name = str(value or "").split("+", 1)[-1].casefold()
    return re.sub(r"[^a-z0-9]", "", name)


def _font_record_supports_cjk(font: tuple[Any, ...]) -> bool:
    """Return whether an embedded PDF font record can plausibly draw CJK.

    A Latin font can still carry the original Chinese Unicode mapping while
    rendering tofu boxes.  Accept a record only when it is an embedded
    composite Identity-H font or its base name identifies a CJK family.
    """
    extension = str(font[1] or "").casefold()
    font_type = str(font[2] or "").casefold()
    base_font = _normalized_font_name(str(font[3] or ""))
    encoding = str(font[5] or "").casefold()
    if extension in {"", "n/a"}:
        return False
    if font_type == "type0" and encoding == "identity-h":
        return True
    return any(marker in base_font for marker in _CJK_FONT_MARKERS)


def _validate_pdf_portability(path: Path) -> tuple[list[str], dict[str, Any]]:
    """Render every page and reject CJK PDFs that rely on absent host fonts.

    Text extraction alone is insufficient: a Type0 ``china-s`` font can expose
    Chinese text to PyMuPDF while Poppler and other readers render blank glyphs.
    Requiring embedded fonts for pages containing CJK text makes the PDF
    portable across the two WorkBuddy hosts and ordinary customer readers.
    """
    import fitz

    errors: list[str] = []
    details: dict[str, Any] = {"page_count": 0, "rendered_page_count": 0, "fonts": []}
    document = fitz.open(path)
    try:
        details["page_count"] = document.page_count
        if document.needs_pass:
            errors.append("PDF已加密，无法执行逐页内容与字体校验")
            return errors, details
        if document.page_count < 1:
            errors.append("PDF没有可渲染页面")
            return errors, details
        seen_fonts: set[tuple[str, str, str, str]] = set()
        seen_cjk_span_fonts: set[str] = set()
        for index, page in enumerate(document, start=1):
            page_text = page.get_text("text", sort=True)
            if len(_compact_text(page_text)) < 10:
                errors.append(f"PDF第{index}页缺少可核验正文")
            try:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), colorspace=fitz.csGRAY, alpha=False)
                samples = pixmap.samples
                if not samples or min(samples) >= 250:
                    errors.append(f"PDF第{index}页渲染为空白页")
                details["rendered_page_count"] += 1
            except Exception as exc:
                errors.append(f"PDF第{index}页渲染失败:{exc}")
            page_has_cjk = _has_cjk_text(page_text)
            page_fonts = page.get_fonts(full=True)
            for font in page_fonts:
                extension = str(font[1] or "").casefold()
                font_type = str(font[2] or "")
                base_font = str(font[3] or "")
                encoding = str(font[5] or "")
                seen_fonts.add((extension, font_type, base_font, encoding))
                if page_has_cjk and extension in {"", "n/a"}:
                    errors.append(
                        f"PDF第{index}页中文字体未嵌入:{base_font or 'unknown'}:{encoding or 'unknown'}"
                    )
            if page_has_cjk:
                cjk_span_fonts = {
                    str(span.get("font") or "")
                    for block in page.get_text("dict").get("blocks", [])
                    for line in block.get("lines", [])
                    for span in line.get("spans", [])
                    if _has_cjk_text(str(span.get("text") or ""))
                }
                seen_cjk_span_fonts.update(cjk_span_fonts)
                supported_records = [font for font in page_fonts if _font_record_supports_cjk(font)]
                supported_names = {
                    _normalized_font_name(str(font[3] or "")) for font in supported_records
                }
                unsupported_span_fonts = sorted(
                    name
                    for name in cjk_span_fonts
                    if not any(
                        marker in _normalized_font_name(name)
                        for marker in _CJK_FONT_MARKERS
                    )
                    and _normalized_font_name(name) not in supported_names
                )
                if not supported_records or unsupported_span_fonts:
                    names = ",".join(unsupported_span_fonts or sorted(cjk_span_fonts)) or "unknown"
                    errors.append(f"PDF第{index}页中文文本未绑定可用中文字体:{names}")
        details["fonts"] = [
            {
                "extension": item[0],
                "type": item[1],
                "base_font": item[2],
                "encoding": item[3],
            }
            for item in sorted(seen_fonts)
        ]
        details["cjk_span_fonts"] = sorted(seen_cjk_span_fonts)
    finally:
        document.close()
    return errors, details


def _load_receipt(path: Path | None, *, label: str, schema: str) -> tuple[dict[str, Any], list[str]]:
    if path is None:
        return {}, [f"缺少{label}"]
    try:
        value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"{label}不可读取:{exc}"]
    if not isinstance(value, dict) or value.get("schema") != schema:
        return {}, [f"{label}格式无效"]
    return value, []


def _validate_template_provenance(
    *,
    plugin_root: Path,
    profile_id: str,
    docx: Path | None,
    template_selection_receipt: Path | None,
    completion_receipt: Path | None,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    selection, selection_errors = _load_receipt(
        template_selection_receipt,
        label="受控模板选型回执",
        schema="gongchuang-project-report-template-selection/v1",
    )
    completion, completion_errors = _load_receipt(
        completion_receipt,
        label="受控模板成稿回执",
        schema="gongchuang-completed-project-report/v1",
    )
    errors.extend(selection_errors)
    errors.extend(completion_errors)
    if errors or docx is None:
        if docx is None:
            errors.append("受控模板来源无法绑定：缺少DOCX")
        return errors, {}

    expected_hashes = {
        str(selection.get("template_sha256") or "").lower(),
        str(selection.get("output_sha256") or "").lower(),
        str(completion.get("template_sha256") or "").lower(),
    }
    if any(len(item) != 64 for item in expected_hashes) or len(expected_hashes) != 1:
        errors.append("受控模板哈希链不一致")

    master = Path(str(selection.get("output_path") or "")).expanduser().resolve()
    completion_template = Path(str(completion.get("template_path") or "")).expanduser().resolve()
    completion_output = Path(str(completion.get("output_path") or "")).expanduser().resolve()
    if master != completion_template:
        errors.append("成稿回执未引用本轮选型复制出的Word母版")
    if completion_output != docx.resolve():
        errors.append("成稿回执未绑定当前DOCX")
    if not master.is_file():
        errors.append("选型复制出的Word母版不存在")
    elif sha256_file(master) not in expected_hashes:
        errors.append("选型复制出的Word母版已变化")
    if str(completion.get("output_sha256") or "").lower() != sha256_file(docx):
        errors.append("成稿回执与当前DOCX哈希不一致")
    if completion.get("status") != "pass":
        errors.append("受控模板成稿回执未通过")
    if str(selection.get("profile_id") or "") != profile_id:
        errors.append("选型回执的报告画像与当前校验画像不一致")
    if str(selection.get("project_id") or "") != str(completion.get("project_id") or ""):
        errors.append("选型与成稿回执的项目类型不一致")
    if str(selection.get("report_type") or "") != str(completion.get("report_type") or ""):
        errors.append("选型与成稿回执的报告类型不一致")

    registry_path = (
        plugin_root
        / "skills/project-feasibility/references/report-template-registry.json"
    )
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        project = next(
            item
            for item in registry.get("projects", [])
            if str(item.get("id") or "") == str(selection.get("project_id") or "")
        )
        template = project.get("templates", {}).get(str(selection.get("report_type") or ""), {})
        registry_hash = str(template.get("sha256") or "").lower()
        if registry_hash not in expected_hashes:
            errors.append("选型回执未绑定当前技能包登记的受控母版")
    except (OSError, ValueError, StopIteration, json.JSONDecodeError):
        errors.append("无法从当前技能包模板索引复核选型回执")

    return errors, {
        "selection_receipt": str(template_selection_receipt.resolve()),
        "completion_receipt": str(completion_receipt.resolve()),
        "project_id": selection.get("project_id"),
        "report_type": selection.get("report_type"),
        "template_sha256": next(iter(expected_hashes), ""),
    }


def _compact_text(value: str) -> str:
    """Normalize extractor glyph fragmentation without hiding missing text."""
    return re.sub(r"\s+", "", value or "")


def _validate_branding(plugin_root: Path, artifacts: list[Path]) -> list[str]:
    scripts = plugin_root / "skills/_runtime/gongchuang-branding/scripts"
    sys.path.insert(0, str(scripts))
    try:
        from delivery_gate import validate_artifact

        errors: list[str] = []
        for artifact in artifacts:
            try:
                validate_artifact(artifact, check_stamp=False)
            except Exception as exc:
                errors.append(f"{artifact.name}品牌校验失败:{exc}")
        return errors
    finally:
        if sys.path and sys.path[0] == str(scripts):
            sys.path.pop(0)


def validate_profile(
    *,
    plugin_root: Path,
    profile_id: str,
    artifacts: list[Path],
    template_selection_receipt: Path | None = None,
    completion_receipt: Path | None = None,
) -> dict[str, Any]:
    contract = json.loads(
        (plugin_root / "skills/delivery-contracts.json").read_text(encoding="utf-8")
    )
    profile = contract.get("delivery_profiles", {}).get(profile_id)
    if not isinstance(profile, dict):
        raise ValueError(f"未知报告画像:{profile_id}")
    errors: list[str] = []
    by_format = {path.suffix.casefold().lstrip("."): path for path in artifacts if path.is_file()}
    for requirement in profile.get("required_artifacts", []):
        for suffix in requirement.get("formats", []):
            if str(suffix).casefold() not in by_format:
                errors.append(f"缺少要求格式:{suffix}")
    docx = by_format.get("docx")
    pdf = by_format.get("pdf")
    provenance_errors, template_provenance = _validate_template_provenance(
        plugin_root=plugin_root,
        profile_id=profile_id,
        docx=docx,
        template_selection_receipt=template_selection_receipt,
        completion_receipt=completion_receipt,
    )
    errors.extend(provenance_errors)
    paragraphs: list[str] = []
    tables: list[list[str]] = []
    if docx:
        try:
            paragraphs, tables = _docx_blocks(docx)
        except Exception as exc:
            errors.append(f"DOCX结构读取失败:{exc}")
    else:
        errors.append("缺少可检查结构的DOCX")
    docx_text = "\n".join(paragraphs + [line for table in tables for line in table])
    for section in profile.get("required_sections", []):
        if str(section) not in docx_text:
            errors.append(f"缺少必备章节:{section}")
    for table_requirement in profile.get("required_tables", []):
        columns = [str(item) for item in table_requirement.get("required_columns", [])]
        min_rows = int(table_requirement.get("min_rows", 1))
        matching = [
            table
            for table in tables
            if table and all(column in table[0] for column in columns)
        ]
        if not matching:
            errors.append(f"缺少必备表格:{table_requirement.get('id')}")
        elif len(matching[0]) - 1 < min_rows:
            errors.append(f"表格数据行不足:{table_requirement.get('id')}")
    if pdf:
        try:
            pdf_text = _pdf_text(pdf)
            compact_pdf_text = _compact_text(pdf_text)
            for section in profile.get("required_sections", []):
                if _compact_text(str(section)) not in compact_pdf_text:
                    errors.append(f"PDF缺少必备章节:{section}")
        except Exception as exc:
            errors.append(f"PDF文本读取失败:{exc}")
        try:
            portability_errors, pdf_render = _validate_pdf_portability(pdf)
            errors.extend(portability_errors)
        except Exception as exc:
            pdf_render = {}
            errors.append(f"PDF逐页渲染与字体校验失败:{exc}")
    else:
        pdf_render = {}
    errors.extend(_validate_branding(plugin_root, [path for path in (docx, pdf) if path]))
    return {
        "status": "pass" if not errors else "fail",
        "profile_id": profile_id,
        "checks": [
            "required-formats",
            "required-sections",
            "required-tables",
            "docx-pdf-structure",
            "controlled-template-provenance",
            "pdf-all-pages-rendered",
            "pdf-cjk-fonts-embedded",
            "branding",
        ],
        "errors": errors,
        "template_provenance": template_provenance,
        "pdf_render": pdf_render,
        "artifacts": [
            {
                "name": path.name,
                "type": path.suffix.casefold().lstrip("."),
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
            for path in artifacts
            if path.is_file()
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--artifact", type=Path, action="append", required=True)
    parser.add_argument("--template-selection-receipt", type=Path, required=True)
    parser.add_argument("--completion-receipt", type=Path, required=True)
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args()
    plugin_root = args.plugin_root.expanduser().resolve()
    root = (
        args.state_root.expanduser().resolve()
        if args.state_root
        else _default_state_root(plugin_root)
    )
    if (plugin_root / ".codebuddy-plugin/plugin.json").is_file():
        canonical = _canonical_state_root(plugin_root)
        if root != canonical:
            raise ValueError("WorkBuddy正式画像回执必须写入宿主行为状态目录")
    current = json.loads((root / "current-turn.json").read_text(encoding="utf-8"))
    turn_id = str(current.get("turn_id") or "").strip()
    if not turn_id:
        raise ValueError("current-turn.json缺少turn_id")
    result = validate_profile(
        plugin_root=plugin_root,
        profile_id=args.profile_id,
        artifacts=[item.expanduser().resolve() for item in args.artifact],
        template_selection_receipt=args.template_selection_receipt.expanduser().resolve(),
        completion_receipt=args.completion_receipt.expanduser().resolve(),
    )
    receipt = {
        "schema_version": 1,
        "validator_id": VALIDATOR_ID,
        "turn_id": turn_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **result,
    }
    target = root / "validator-receipts" / turn_id / f"report-profile-{args.profile_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**receipt, "receipt_path": str(target)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

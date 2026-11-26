#!/usr/bin/env python3
"""Extract Chinese patent-application structure directly from OOXML."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
O = "urn:schemas-microsoft-com:office:office"
NS = {"w": W, "m": M, "r": R, "o": O}
SECTION_TITLES = {
    "摘要": "abstract_text",
    "说明书摘要": "abstract_text",
    "权利要求书": "claims",
    "说明书": "description",
    "说明书附图": "description_figs",
    "摘要附图": "abstract_fig",
}
REQUIRED_SECTIONS = {
    "abstract_text": "摘要",
    "claims": "权利要求书",
    "description": "说明书",
    "figure_description": "附图说明",
}
SPECIFICATION_HEADINGS = {
    "技术领域", "背景技术", "发明内容", "实用新型内容", "附图说明", "具体实施方式",
}
CLAIM_NUMBER = re.compile(r"(?m)^[ \t]*(\d+)[ \t]*(?:[、．]|\.(?!\d))[ \t]*")
RANGE_SEPARATORS = "—–－~～至到-"
CLAIM_REFERENCE = re.compile(
    rf"权利要求\s*(\d+(?:\s*(?:[、,，{RANGE_SEPARATORS}]|或者|或|和|及|与)\s*\d+)*)"
)
REFERENCE_NUMBER = re.compile(rf"(\d+)(?:\s*[{RANGE_SEPARATORS}]\s*(\d+))?")


def qname(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def xml_root(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(name))
    except KeyError:
        return None


def node_text(node: ET.Element) -> str:
    values = []
    for child in node.iter():
        if child.tag in {qname(W, "t"), qname(M, "t"), qname(W, "instrText")}:
            values.append(child.text or "")
        elif child.tag == qname(W, "tab"):
            values.append("\t")
        elif child.tag in {qname(W, "br"), qname(W, "cr")}:
            values.append("\n")
    return "".join(values)


def paragraphs(root: ET.Element | None) -> list[str]:
    if root is None:
        return []
    result = []
    for paragraph in root.findall(".//w:p", NS):
        value = re.sub(r"[ \t]+", " ", node_text(paragraph)).strip()
        if value:
            result.append(value)
    return result


def notes(root: ET.Element | None, item_name: str) -> list[dict[str, str]]:
    if root is None:
        return []
    result = []
    for item in root.findall(f".//w:{item_name}", NS):
        note_id = item.get(qname(W, "id"), "")
        if note_id.startswith("-"):
            continue
        value = "\n".join(paragraphs(item))
        if value:
            result.append({"id": note_id, "text": value})
    return result


def equations(parts: dict[str, ET.Element | None]) -> list[dict[str, str]]:
    result = []
    for part_name, root in parts.items():
        if root is None:
            continue
        for index, equation in enumerate(root.findall(".//m:oMath", NS), 1):
            result.append(
                {"part": part_name, "index": str(index), "text": node_text(equation)}
            )
    return result


def normalize_section_title(value: str) -> str:
    return re.sub(r"[\s：:]+", "", value)


def sectionize(values: list[str]) -> dict[str, str]:
    headings = [normalize_section_title(value) for value in values]
    inferred_claim_start = None
    if "权利要求书" not in headings:
        following_headings = SPECIFICATION_HEADINGS | {"说明书", "说明书附图", "摘要附图"}
        boundary = next((i for i, heading in enumerate(headings) if heading in following_headings), None)
        if boundary is not None:
            for index, value in enumerate(values[:boundary]):
                match = CLAIM_NUMBER.match(value)
                if match and int(match[1]) == 1:
                    inferred_claim_start = index
                    break

    buckets = {section: [] for section in SECTION_TITLES.values()}
    buckets["figure_description"] = []
    active = "abstract_text" if inferred_claim_start is not None else "description"
    in_figure_description = False
    for index, (value, heading) in enumerate(zip(values, headings)):
        if index == inferred_claim_start:
            active = "claims"
        if heading in SECTION_TITLES:
            active = SECTION_TITLES[heading]
            in_figure_description = False
            continue
        if active == "claims" and heading in SPECIFICATION_HEADINGS:
            claims = buckets["claims"]
            # 省略“说明书”标题的稿件，也可能在“技术领域”前保留一行发明名称。
            if (
                heading == "技术领域"
                and len(claims) > 1
                and claims[-2].endswith(("。", "."))
                and re.fullmatch(r"[^\W\d][\w \t]*", claims[-1])
            ):
                buckets["description"].append(claims.pop())
            active = "description"
        if active == "description":
            if heading in SPECIFICATION_HEADINGS:
                in_figure_description = heading == "附图说明"
            elif in_figure_description:
                buckets["figure_description"].append(value)
        buckets[active].append(value)
    return {key: "\n".join(items) for key, items in buckets.items()}


def claim_items(claims: str) -> list[dict[str, object]]:
    matches = list(CLAIM_NUMBER.finditer(claims))
    items = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(claims)
        references = []
        for group in CLAIM_REFERENCE.finditer(claims, match.end(), end):
            for first, last in REFERENCE_NUMBER.findall(group[1]):
                start = int(first)
                stop = int(last) if last else start
                step = 1 if start <= stop else -1
                references.extend(range(start, stop + step, step))
        item = {"number": int(match[1]), "type": "dependent" if references else "independent"}
        if references:
            item["references"] = list(dict.fromkeys(references))
        items.append(item)
    return items


def extract(path: Path) -> dict[str, object]:
    if path.suffix.lower() != ".docx":
        raise ValueError("仅支持 OOXML .docx 文件；旧 .doc 请先转换为 .docx")
    with zipfile.ZipFile(path) as archive:
        document = xml_root(archive, "word/document.xml")
        if document is None:
            raise ValueError("缺少 word/document.xml")
        footnote_root = xml_root(archive, "word/footnotes.xml")
        endnote_root = xml_root(archive, "word/endnotes.xml")
        parts = {
            "word/document.xml": document,
            "word/footnotes.xml": footnote_root,
            "word/endnotes.xml": endnote_root,
        }
        body_paragraphs = paragraphs(document)
        sections = sectionize(body_paragraphs)
        missing_sections = [
            title for key, title in REQUIRED_SECTIONS.items()
            if not any(normalize_section_title(line) not in SPECIFICATION_HEADINGS
                       for line in sections[key].splitlines() if line.strip())
        ]
        table_count = len(document.findall(".//w:tbl", NS)) if document is not None else 0
        text_box_count = (
            len(document.findall(".//w:txbxContent", NS))
            if document is not None
            else 0
        )
        drawing_count = (
            len(document.findall(".//w:drawing", NS))
            + len(document.findall(".//w:pict", NS))
            if document is not None
            else 0
        )
        object_nodes = []
        if document is not None:
            object_nodes = document.findall(".//w:object", NS)
        embedded = [
            {
                "index": index,
                "relationship_id": (
                    node.find(".//o:OLEObject", NS).get(qname(R, "id"), "")
                    if node.find(".//o:OLEObject", NS) is not None
                    else ""
                ),
                "text": node_text(node),
            }
            for index, node in enumerate(object_nodes, 1)
        ]
        media = sorted(name for name in archive.namelist() if name.startswith("word/media/"))
        relationships = sorted(
            name
            for name in archive.namelist()
            if name.startswith("word/_rels/") or name.endswith(".rels")
        )
    return {
        **sections,
        "missing_sections": missing_sections,
        "claim_items": claim_items(sections["claims"]),
        "full_text": "\n".join(body_paragraphs),
        "paragraphs": body_paragraphs,
        "footnotes": notes(footnote_root, "footnote"),
        "endnotes": notes(endnote_root, "endnote"),
        "equations": equations(parts),
        "embedded_objects": embedded,
        "tables": {"count": table_count},
        "text_boxes": {"count": text_box_count},
        "drawings": {"count": drawing_count, "media": media},
        "relationships": relationships,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_docx", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--extract-only", action="store_true")
    parser.add_argument("--allow-partial", action="store_true", help="允许提取片段并报告缺失章节")
    args = parser.parse_args()
    try:
        result = extract(args.input_docx)
    except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError) as error:
        try:
            size_bytes = args.input_docx.stat().st_size
        except OSError:
            size_bytes = None
        reason = str(error)
        if isinstance(error, zipfile.BadZipFile):
            reason = "文件为空" if size_bytes == 0 else "文件不是有效的 DOCX 压缩包"
        elif isinstance(error, ET.ParseError):
            reason = f"XML 无法解析：{error}"
        print(json.dumps({"error": reason, "size_bytes": size_bytes}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.extract_only or not args.output_json:
        print(result["full_text"])
    if result["missing_sections"]:
        print(json.dumps({"missing_sections": result["missing_sections"]}, ensure_ascii=False), file=sys.stderr)
        if not args.allow_partial:
            raise SystemExit(1)


if __name__ == "__main__":
    main()

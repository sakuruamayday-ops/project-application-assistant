#!/usr/bin/env python3
"""Extract Chinese patent-application structure directly from OOXML."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
O = "urn:schemas-microsoft-com:office:office"
NS = {"w": W, "m": M, "r": R, "o": O}


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


def sectionize(values: list[str]) -> dict[str, str]:
    aliases = {
        "摘要": "abstract_text",
        "权利要求书": "claims",
        "说明书": "description",
        "说明书附图": "description_figs",
        "摘要附图": "abstract_fig",
    }
    buckets = {value: [] for value in aliases.values()}
    active = "description"
    for value in values:
        normalized = re.sub(r"[\s：:]+", "", value)
        matched = next(
            (key for title, key in aliases.items() if normalized == title), None
        )
        if matched:
            active = matched
            continue
        buckets[active].append(value)
    result = {key: "\n".join(items) for key, items in buckets.items()}
    if not result["claims"]:
        claim_start = next(
            (
                index
                for index, value in enumerate(values)
                if re.match(r"^\s*1\s*[、.．]\s*", value)
            ),
            None,
        )
        description_heading = next(
            (
                index
                for index, value in enumerate(values)
                if re.sub(r"\s+", "", value) == "技术领域"
            ),
            None,
        )
        if (
            claim_start is not None
            and description_heading is not None
            and claim_start < description_heading
        ):
            description_start = max(claim_start + 1, description_heading - 1)
            result["abstract_text"] = "\n".join(values[:claim_start])
            result["claims"] = "\n".join(values[claim_start:description_start])
            result["description"] = "\n".join(values[description_start:])
    return result


def extract(path: Path) -> dict[str, object]:
    if path.suffix.lower() != ".docx":
        raise ValueError("仅支持 OOXML .docx 文件；旧 .doc 请先转换为 .docx")
    with zipfile.ZipFile(path) as archive:
        document = xml_root(archive, "word/document.xml")
        footnote_root = xml_root(archive, "word/footnotes.xml")
        endnote_root = xml_root(archive, "word/endnotes.xml")
        parts = {
            "word/document.xml": document,
            "word/footnotes.xml": footnote_root,
            "word/endnotes.xml": endnote_root,
        }
        body_paragraphs = paragraphs(document)
        sections = sectionize(body_paragraphs)
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
    args = parser.parse_args()
    result = extract(args.input_docx)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.extract_only or not args.output_json:
        print(result["full_text"])


if __name__ == "__main__":
    main()

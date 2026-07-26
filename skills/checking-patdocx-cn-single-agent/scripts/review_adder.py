#!/usr/bin/env python3
"""Add traceable Word comments without changing the source text."""

from __future__ import annotations

import argparse
import copy
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W}
ET.register_namespace("w", W)
ET.register_namespace("r", R)


def qname(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.findall(".//w:t", NS))


def plain_run_text(run: ET.Element) -> str | None:
    allowed = {qname(W, "rPr"), qname(W, "t")}
    if any(child.tag not in allowed for child in run):
        return None
    return "".join(node.text or "" for node in run.findall("w:t", NS))


def run_text(run: ET.Element) -> str:
    return "".join(node.text or "" for node in run.findall(".//w:t", NS))


def cloned_text_run(run: ET.Element, text: str) -> ET.Element:
    cloned = ET.Element(qname(W, "r"), dict(run.attrib))
    properties = run.find("w:rPr", NS)
    if properties is not None:
        cloned.append(copy.deepcopy(properties))
    value = ET.SubElement(cloned, qname(W, "t"))
    if text[:1].isspace() or text[-1:].isspace():
        value.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    value.text = text
    return cloned


def replace_run(
    paragraph: ET.Element,
    run: ET.Element,
    segments: list[str],
) -> list[ET.Element]:
    index = list(paragraph).index(run)
    paragraph.remove(run)
    replacements = []
    for text in segments:
        if not text:
            continue
        replacement = cloned_text_run(run, text)
        paragraph.insert(index + len(replacements), replacement)
        replacements.append(replacement)
    return replacements


def occurrence_start(text: str, anchor: str, occurrence: int) -> int:
    start = -1
    for _ in range(occurrence):
        start = text.find(anchor, start + 1)
        if start < 0:
            return -1
    return start


def exact_range_runs(
    paragraph: ET.Element,
    anchor: str,
    occurrence: int,
) -> tuple[ET.Element, ET.Element] | None:
    runs = [child for child in list(paragraph) if child.tag == qname(W, "r")]
    texts = [run_text(run) for run in runs]
    if not runs:
        return None
    joined = "".join(texts)
    if joined != paragraph_text(paragraph):
        return None
    start = occurrence_start(joined, anchor, occurrence)
    if start < 0:
        return None
    end = start + len(anchor)
    cursor = 0
    start_run = end_run = None
    start_offset = end_offset = 0
    for run, value in zip(runs, texts):
        next_cursor = cursor + len(value)
        if start_run is None and cursor <= start < next_cursor:
            start_run, start_offset = run, start - cursor
        if cursor < end <= next_cursor:
            end_run, end_offset = run, end - cursor
            break
        cursor = next_cursor
    if start_run is None or end_run is None:
        return None
    if plain_run_text(start_run) is None or plain_run_text(end_run) is None:
        return None
    if start_run is end_run:
        value = plain_run_text(start_run) or ""
        parts = replace_run(
            paragraph,
            start_run,
            [value[:start_offset], value[start_offset:end_offset], value[end_offset:]],
        )
        selected = next(run for run in parts if plain_run_text(run) == anchor)
        return selected, selected
    start_value = plain_run_text(start_run) or ""
    start_parts = replace_run(
        paragraph,
        start_run,
        [start_value[:start_offset], start_value[start_offset:]],
    )
    selected_start = start_parts[-1]
    end_value = plain_run_text(end_run) or ""
    end_parts = replace_run(
        paragraph,
        end_run,
        [end_value[:end_offset], end_value[end_offset:]],
    )
    selected_end = end_parts[0]
    return selected_start, selected_end


def add_markers(
    paragraph: ET.Element,
    comment_id: str,
    anchor: str,
    occurrence: int,
) -> str:
    selected = exact_range_runs(paragraph, anchor, occurrence)
    if selected is None:
        runs = [child for child in list(paragraph) if child.tag == qname(W, "r")]
        if not runs:
            return "unavailable"
        selected = runs[0], runs[-1]
        precision = "paragraph"
    else:
        precision = "exact"
    start_run, end_run = selected
    start_index = list(paragraph).index(start_run)
    paragraph.insert(start_index, ET.Element(qname(W, "commentRangeStart"), {qname(W, "id"): comment_id}))
    end_index = list(paragraph).index(end_run)
    paragraph.insert(end_index + 1, ET.Element(qname(W, "commentRangeEnd"), {qname(W, "id"): comment_id}))
    reference_run = ET.Element(qname(W, "r"))
    properties = ET.SubElement(reference_run, qname(W, "rPr"))
    ET.SubElement(properties, qname(W, "rStyle"), {qname(W, "val"): "CommentReference"})
    ET.SubElement(reference_run, qname(W, "commentReference"), {qname(W, "id"): comment_id})
    paragraph.insert(end_index + 2, reference_run)
    return precision


def comments_xml(reviews: list[dict[str, object]]) -> bytes:
    root = ET.Element(qname(W, "comments"))
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for index, review in enumerate(reviews):
        comment = ET.SubElement(
            root,
            qname(W, "comment"),
            {
                qname(W, "id"): str(index),
                qname(W, "author"): "焦糖专利核稿",
                qname(W, "initials"): "焦糖",
                qname(W, "date"): now,
            },
        )
        paragraph = ET.SubElement(comment, qname(W, "p"))
        run = ET.SubElement(paragraph, qname(W, "r"))
        text = ET.SubElement(run, qname(W, "t"))
        text.text = str(review.get("comment") or review.get("suggestion") or review.get("issue") or "请复核")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def ensure_relationship(root: ET.Element) -> None:
    if any(item.get("Type", "").endswith("/comments") for item in root):
        return
    used = {item.get("Id", "") for item in root}
    number = 1
    while f"rId{number}" in used:
        number += 1
    ET.SubElement(
        root,
        qname(PR, "Relationship"),
        {
            "Id": f"rId{number}",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
            "Target": "comments.xml",
        },
    )


def ensure_content_type(root: ET.Element) -> None:
    if any(item.get("PartName") == "/word/comments.xml" for item in root):
        return
    ET.SubElement(
        root,
        qname(CT, "Override"),
        {
            "PartName": "/word/comments.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
        },
    )


def add_comments(source: Path, target: Path, reviews: list[dict[str, object]]) -> dict[str, object]:
    with TemporaryDirectory(prefix="jiaotang-comment-") as directory:
        root_dir = Path(directory)
        with zipfile.ZipFile(source) as archive:
            archive.extractall(root_dir)
        document_path = root_dir / "word/document.xml"
        document = ET.parse(document_path)
        paragraphs = document.getroot().findall(".//w:p", NS)
        applied = []
        skipped = []
        for review in reviews:
            anchor = str(review.get("highlight_text") or review.get("context") or "").strip()
            occurrence = int(review.get("occurrence") or 1)
            matches = [paragraph for paragraph in paragraphs if anchor and anchor in paragraph_text(paragraph)]
            if len(matches) < occurrence:
                skipped.append({"anchor": anchor, "reason": "未定位到指定 occurrence"})
                continue
            comment_id = str(len(applied))
            precision = add_markers(
                matches[occurrence - 1],
                comment_id,
                anchor,
                1,
            )
            if precision == "unavailable":
                skipped.append({"anchor": anchor, "reason": "目标段落没有可批注文本"})
                continue
            applied.append({**review, "_anchor_precision": precision})
        document.write(document_path, encoding="utf-8", xml_declaration=True)

        comments_path = root_dir / "word/comments.xml"
        comments_path.write_bytes(comments_xml(applied))
        rels_path = root_dir / "word/_rels/document.xml.rels"
        rels = ET.parse(rels_path)
        ensure_relationship(rels.getroot())
        rels.write(rels_path, encoding="utf-8", xml_declaration=True)
        content_types_path = root_dir / "[Content_Types].xml"
        content_types = ET.parse(content_types_path)
        ensure_content_type(content_types.getroot())
        content_types.write(content_types_path, encoding="utf-8", xml_declaration=True)

        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root_dir).as_posix())
    return {
        "applied": len(applied),
        "exact_anchors": sum(
            item.get("_anchor_precision") == "exact" for item in applied
        ),
        "paragraph_anchors": sum(
            item.get("_anchor_precision") == "paragraph" for item in applied
        ),
        "skipped": skipped,
        "output": str(target),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_docx", type=Path)
    parser.add_argument("output_docx", type=Path)
    parser.add_argument("--reviews-file", required=True, type=Path)
    args = parser.parse_args()
    reviews = json.loads(args.reviews_file.read_text(encoding="utf-8"))
    if isinstance(reviews, dict):
        reviews = reviews.get("reviews", [])
    print(json.dumps(add_comments(args.input_docx, args.output_docx, reviews), ensure_ascii=False))


if __name__ == "__main__":
    main()

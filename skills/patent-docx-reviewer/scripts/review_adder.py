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
# Word 的 mc:Ignorable 引用的是前缀名称，即使正文没有使用这些命名空间，
# 也必须保留声明。ElementTree 会丢弃它们，产生可解压却无法被 Office 打开的文件。
from lxml import etree as ET

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


def _format_comment_body(review: dict[str, object]) -> str:
    body = str(review.get("comment") or review.get("suggestion") or review.get("issue") or "请复核")
    scope = str(review.get("保护范围影响") or review.get("scope_impact") or "").strip()
    if scope and "保护范围影响" not in body:
        body = f"{body}\n保护范围影响：{scope}"
    return body


def _has_scope_impact(review: dict[str, object]) -> bool:
    if str(review.get("保护范围影响") or review.get("scope_impact") or "").strip():
        return True
    body = str(review.get("comment") or review.get("suggestion") or review.get("issue") or "")
    return ("保护范围影响" in body) or ("缺范围判断依据" in body)


def comments_xml(
    reviews: list[dict[str, object]], root: ET.Element | None = None, first_id: int = 0
) -> bytes:
    if root is None:
        root = ET.Element(qname(W, "comments"))
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for comment_id, review in enumerate(reviews, first_id):
        comment = ET.SubElement(
            root,
            qname(W, "comment"),
            {
                qname(W, "id"): str(comment_id),
                qname(W, "author"): "专利核稿",
                qname(W, "initials"): "核稿",
                qname(W, "date"): now,
            },
        )
        paragraph = ET.SubElement(comment, qname(W, "p"))
        run = ET.SubElement(paragraph, qname(W, "r"))
        text = ET.SubElement(run, qname(W, "t"))
        text.text = _format_comment_body(review)
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


def read_reviews(path: Path) -> list[dict[str, object]]:
    reviews = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(reviews, dict):
        reviews = reviews.get("reviews")
    if not isinstance(reviews, list) or any(not isinstance(review, dict) for review in reviews):
        raise ValueError("批注意见须为对象数组，或包含 reviews 数组的对象")
    return reviews


def add_comments(
    source: Path,
    target: Path,
    reviews: list[dict[str, object]],
    *,
    require_scope_impact: bool = False,
    overwrite: bool = False,
    abort_on_skip: bool = False,
) -> dict[str, object]:
    if source.resolve() == target.resolve():
        raise ValueError("输出路径不得与原专利申请 DOCX 相同，请指定新路径防止覆盖原稿")
    if target.exists() and not overwrite:
        raise ValueError(f"目标文件已存在；如需覆盖请显式传入 --overwrite：{target}")
    occurrences = [review.get("occurrence", 1) for review in reviews]
    if any(type(occurrence) is not int or occurrence < 1 for occurrence in occurrences):
        raise ValueError("occurrence 必须是从 1 开始的正整数（1、2、3……）")
    if require_scope_impact:
        missing_scope = [
            idx for idx, rev in enumerate(reviews)
            if not _has_scope_impact(rev)
        ]
        if missing_scope:
            raise ValueError(f"以下审核意见缺少必填字段「保护范围影响」：{missing_scope}")

    with TemporaryDirectory(prefix="patent-comment-") as directory:
        root_dir = Path(directory)
        with zipfile.ZipFile(source) as archive:
            archive.extractall(root_dir)
        document_path = root_dir / "word/document.xml"
        document = ET.parse(document_path)
        paragraphs = document.getroot().findall(".//w:p", NS)
        comments_path = root_dir / "word/comments.xml"
        existing_comments = ET.parse(comments_path).getroot() if comments_path.exists() else None
        first_id = 0
        if existing_comments is not None:
            first_id = 1 + max(
                (int(comment.get(qname(W, "id"))) for comment in existing_comments.findall("w:comment", NS)),
                default=-1,
            )
        applied = []
        skipped = []
        for review, occurrence in zip(reviews, occurrences):
            anchor = str(review.get("highlight_text") or review.get("context") or "").strip()
            in_para_occ = review.get("occurrence_in_paragraph", 1)
            if type(in_para_occ) is not int or in_para_occ < 1:
                raise ValueError("occurrence_in_paragraph 必须是从 1 开始的正整数")
            matches = [paragraph for paragraph in paragraphs if anchor and anchor in paragraph_text(paragraph)]
            if len(matches) < occurrence:
                skipped.append({"anchor": anchor, "reason": "未定位到指定 occurrence"})
                continue
            target_para = matches[occurrence - 1]
            if in_para_occ > 1 and paragraph_text(target_para).count(anchor) < in_para_occ:
                skipped.append({"anchor": anchor, "reason": f"段内仅出现 {paragraph_text(target_para).count(anchor)} 次，越界请求第 {in_para_occ} 次"})
                continue
            comment_id = str(first_id + len(applied))
            precision = add_markers(
                target_para,
                comment_id,
                anchor,
                in_para_occ,
            )
            if precision == "unavailable":
                skipped.append({"anchor": anchor, "reason": "目标段落没有可批注文本"})
                continue
            applied.append({**review, "_anchor_precision": precision})

        # Do NOT overwrite/commit target when skipped items trigger abort_on_skip (or an existing target would be clobbered)
        if skipped and (abort_on_skip or target.exists()):
            return {
                "expected": len(reviews),
                "applied": len(applied),
                "exact_anchors": sum(item.get("_anchor_precision") == "exact" for item in applied),
                "paragraph_anchors": sum(item.get("_anchor_precision") == "paragraph" for item in applied),
                "skipped": skipped,
                "output": str(target),
                "output_written": False,
            }

        document.write(document_path, encoding="utf-8", xml_declaration=True)

        if applied or existing_comments is None:
            comments_path.write_bytes(comments_xml(applied, existing_comments, first_id))
        rels_path = root_dir / "word/_rels/document.xml.rels"
        rels = ET.parse(rels_path)
        ensure_relationship(rels.getroot())
        rels.write(rels_path, encoding="utf-8", xml_declaration=True)
        content_types_path = root_dir / "[Content_Types].xml"
        content_types = ET.parse(content_types_path)
        ensure_content_type(content_types.getroot())
        content_types.write(content_types_path, encoding="utf-8", xml_declaration=True)

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_zip = target.with_name(f".{target.name}.tmp")
        try:
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(root_dir.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(root_dir).as_posix())
            tmp_zip.replace(target)
        except Exception:
            if tmp_zip.exists():
                tmp_zip.unlink()
            raise
    return {
        "expected": len(reviews),
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
    parser.add_argument("--require-scope-impact", action="store_true", default=True, help="强制每条意见包含「保护范围影响」（正式CLI默认开启）")
    parser.add_argument("--allow-missing-scope-impact", action="store_true", help="仅草稿模式允许缺少「保护范围影响」")
    parser.add_argument("--overwrite", action="store_true", help="显式允许覆盖已存在的输出文件")
    args = parser.parse_args()
    try:
        if args.reviews_file.resolve() == args.output_docx.resolve():
            raise ValueError("输出路径不得与 --reviews-file 相同")
        reviews = read_reviews(args.reviews_file)
        result = add_comments(
            args.input_docx,
            args.output_docx,
            reviews,
            require_scope_impact=not args.allow_missing_scope_impact,
            overwrite=args.overwrite,
            abort_on_skip=True,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    if result["skipped"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

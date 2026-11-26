#!/usr/bin/env python3
"""Verify that a commented DOCX preserves source content and package assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

from lxml import etree as ET

from patent_extractor import SECTION_TITLES, normalize_section_title
from review_adder import read_reviews

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
DOCUMENT_XML = "word/document.xml"
COMMENTS_XML = "word/comments.xml"
RELATIONSHIPS_XML = "word/_rels/document.xml.rels"
COMMENT_ID = f"{{{W}}}id"


def package_inventory(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
        }


def visible_text(root: ET.Element) -> str:
    return "".join(node.text or "" for node in root.findall(".//w:t", NS))


def section_titles(document: ET.Element) -> set[str]:
    titles = {
        normalize_section_title(visible_text(paragraph))
        for paragraph in document.findall(".//w:p", NS)
    }
    return titles.intersection(SECTION_TITLES)


def comment_ids(root: ET.Element | None) -> set[str]:
    return {node.get(COMMENT_ID, "") for node in root.findall("w:comment", NS)} if root is not None else set()


def comment_id_report(document: ET.Element, comments: ET.Element) -> dict[str, object]:
    records = Counter(node.get(COMMENT_ID, "") for node in comments.findall("w:comment", NS))
    references = Counter(node.get(COMMENT_ID, "") for node in document.findall(".//w:commentReference", NS))
    starts = Counter(node.get(COMMENT_ID, "") for node in document.findall(".//w:commentRangeStart", NS))
    ends = Counter(node.get(COMMENT_ID, "") for node in document.findall(".//w:commentRangeEnd", NS))
    errors = []
    for name, ids in (
        ("comments.xml", records), ("commentReference", references),
        ("commentRangeStart", starts), ("commentRangeEnd", ends),
    ):
        if "" in ids:
            errors.append(f"{name} 缺少批注 ID")
        duplicates = sorted(value for value, count in ids.items() if count > 1)
        if duplicates:
            errors.append(f"{name} 批注 ID 重复：{duplicates}")
    if references.keys() != records.keys():
        errors.append(
            f"正文批注引用与批注记录 ID 不一致："
            f"缺记录 {sorted(references.keys() - records.keys())}，"
            f"缺引用 {sorted(records.keys() - references.keys())}"
        )
    if starts != ends:
        errors.append("正文 commentRangeStart 与 commentRangeEnd 的 ID 不一致")
    if (starts.keys() | ends.keys()) - references.keys():
        errors.append("正文批注范围的 ID 缺少对应的 commentReference")

    report = {}
    if errors:
        report["comment_reference_errors"] = errors
    reference_count, record_count = sum(references.values()), sum(records.values())
    if reference_count != record_count:
        report["comment_count_mismatch"] = {"references": reference_count, "comments": record_count}
    return report


def comment_relationship_errors(
    relationships: ET.Element | None, target_files: dict[str, str], missing: list[str]
) -> list[str]:
    links = [] if relationships is None else [
        item for item in relationships if item.get("Type", "").endswith("/comments")
    ]
    errors = []
    if len(links) != 1:
        errors.append(f"{RELATIONSHIPS_XML} 需要 1 条批注关系，实际 {len(links)} 条")
    for link in links:
        target = link.get("Target", "")
        if not target or link.get("TargetMode", "Internal") != "Internal":
            errors.append("批注关系必须指向包内的批注部件")
            continue
        part = posixpath.normpath(posixpath.join("word", unquote(target))).lstrip("/")
        if part not in target_files:
            if part not in missing:
                missing.append(part)
            errors.append(f"批注关系目标部件不存在：{part}")
        elif part != COMMENTS_XML:
            errors.append(f"批注关系指向 {part}，预期 {COMMENTS_XML}")
    return errors


def verify(source: Path, target: Path, *, expected_comments: int | None = None) -> dict[str, object]:
    try:
        source_files = package_inventory(source)
        target_files = package_inventory(target)
    except (OSError, zipfile.BadZipFile) as error:
        return {
            "valid": False, "text_equal": False, "comments_present": False,
            "missing_parts": [], "changed_assets": [], "unbound_namespace_prefixes": [],
            "structure_errors": [f"DOCX 无法读取：{error}"],
        }
    protected_prefixes = ("word/media/", "word/embeddings/")
    protected = [
        name
        for name in source_files
        if name.startswith(protected_prefixes)
    ]
    missing = [name for name in source_files if name not in target_files]
    changed_assets = [
        name
        for name in protected
        if target_files.get(name) != source_files[name]
    ]
    invalid_xml_parts = []
    structure_errors = []

    def parse_part(archive: zipfile.ZipFile, name: str, *, required: bool = False) -> ET.Element | None:
        try:
            return ET.fromstring(archive.read(name))
        except KeyError:
            if required:
                if name not in missing:
                    missing.append(name)
                structure_errors.append(f"{archive.filename} 缺少 {name}")
        except ET.XMLSyntaxError as error:
            if name not in invalid_xml_parts:
                invalid_xml_parts.append(name)
            structure_errors.append(f"{archive.filename} 的 {name} XML 无法解析：{error}")
        return None

    with zipfile.ZipFile(source) as source_archive, zipfile.ZipFile(target) as target_archive:
        source_document = parse_part(source_archive, DOCUMENT_XML, required=True)
        target_document = parse_part(target_archive, DOCUMENT_XML, required=True)
        comments = parse_part(target_archive, COMMENTS_XML)
        original_comments = parse_part(source_archive, COMMENTS_XML) if expected_comments is not None else None
        relationships = parse_part(target_archive, RELATIONSHIPS_XML)

    text_equal = False
    missing_sections = []
    if source_document is not None and target_document is not None:
        text_equal = visible_text(source_document) == visible_text(target_document)
        lost_titles = section_titles(source_document) - section_titles(target_document)
        missing_sections = [title for title in SECTION_TITLES if title in lost_titles]

    comments_present = COMMENTS_XML in target_files
    diagnostics = {}
    if comments is not None and comments.tag != f"{{{W}}}comments":
        structure_errors.append(f"{COMMENTS_XML} 的根元素应为 w:comments")
    if target_document is not None and comments is not None:
        diagnostics.update(comment_id_report(target_document, comments))
    comment_counts = {}
    if expected_comments is not None:
        original_ids = comment_ids(original_comments)
        target_ids = comment_ids(comments)
        actual = len(target_ids - original_ids)
        comment_counts = {"expected_comment_count": expected_comments, "actual_comment_count": actual}
        if actual != expected_comments:
            diagnostics["expected_comment_count_mismatch"] = {"expected": expected_comments, "actual": actual}
        if original_ids - target_ids:
            diagnostics["missing_original_comment_ids"] = sorted(original_ids - target_ids)
    relationship_errors = comment_relationship_errors(relationships, target_files, missing)
    for key, value in (
        ("missing_sections", missing_sections),
        ("invalid_xml_parts", invalid_xml_parts),
        ("structure_errors", structure_errors),
        ("comment_relationship_errors", relationship_errors),
    ):
        if value:
            diagnostics[key] = value

    # ZIP 能解压、正文相同并不代表 Office 能打开；Ignorable 的前缀也必须有声明。
    namespace_errors = []
    for name, root in ((DOCUMENT_XML, target_document), (COMMENTS_XML, comments)):
        if root is None:
            continue
        for node in root.iter():
            prefixes = node.get("{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable", "").split()
            namespace_errors.extend(f"{name}: {prefix}" for prefix in prefixes if prefix not in node.nsmap)
    valid = text_equal and comments_present and not (missing or changed_assets or namespace_errors or diagnostics)
    return {
        "valid": valid,
        "text_equal": text_equal,
        "comments_present": comments_present,
        "missing_parts": missing,
        "changed_assets": changed_assets,
        "unbound_namespace_prefixes": namespace_errors,
        **comment_counts,
        **diagnostics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--output-json", type=Path)
    count_source = parser.add_mutually_exclusive_group(required=True)
    count_source.add_argument("--reviews-file", type=Path, help="本次应写入的原批注意见清单")
    count_source.add_argument("--expected-comments", type=int, help="本次应新增的批注条数")
    count_source.add_argument("--structure-only", action="store_true", help="只诊断 OOXML 结构")
    args = parser.parse_args()
    expected = args.expected_comments
    if args.reviews_file:
        try:
            expected = len(read_reviews(args.reviews_file))
        except (OSError, ValueError) as error:
            parser.error(str(error))
    if expected is not None and expected < 0:
        parser.error("--expected-comments 须为非负整数")
    result = verify(args.source, args.target, expected_comments=expected)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json:
        args.output_json.write_text(payload, encoding="utf-8")
    print(payload)
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()

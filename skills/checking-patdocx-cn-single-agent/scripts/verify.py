#!/usr/bin/env python3
"""Verify that a commented DOCX preserves source content and package assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from lxml import etree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def package_inventory(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
        }


def visible_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    return "".join(node.text or "" for node in root.findall(".//w:t", NS))


def verify(source: Path, target: Path) -> dict[str, object]:
    source_files = package_inventory(source)
    target_files = package_inventory(target)
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
    text_equal = visible_text(source) == visible_text(target)
    comments_present = "word/comments.xml" in target_files
    # ZIP 能解压、正文相同并不代表 Office 能打开；Ignorable 的前缀也必须有声明。
    namespace_errors = []
    with zipfile.ZipFile(target) as archive:
        for name in ("word/document.xml", "word/comments.xml"):
            if name not in target_files:
                continue
            root = ET.fromstring(archive.read(name))
            for node in root.iter():
                prefixes = node.get("{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable", "").split()
                namespace_errors.extend(f"{name}: {prefix}" for prefix in prefixes if prefix not in node.nsmap)
    valid = not missing and not changed_assets and text_equal and comments_present and not namespace_errors
    return {
        "valid": valid,
        "text_equal": text_equal,
        "comments_present": comments_present,
        "missing_parts": missing,
        "changed_assets": changed_assets,
        "unbound_namespace_prefixes": namespace_errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    result = verify(args.source, args.target)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json:
        args.output_json.write_text(payload, encoding="utf-8")
    print(payload)
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()

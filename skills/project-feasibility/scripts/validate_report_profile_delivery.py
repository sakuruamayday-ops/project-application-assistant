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
    errors.extend(_validate_branding(plugin_root, [path for path in (docx, pdf) if path]))
    return {
        "status": "pass" if not errors else "fail",
        "profile_id": profile_id,
        "checks": [
            "required-formats",
            "required-sections",
            "required-tables",
            "docx-pdf-structure",
            "branding",
        ],
        "errors": errors,
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

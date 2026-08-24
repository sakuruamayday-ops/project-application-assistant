#!/usr/bin/env python3
"""Fail closed when public release surfaces leak the private legacy brand."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable


PUBLIC_BRAND = "共创研究院"
ALLOWED_IDENTIFIERS = ("jiaotang-kb", "zshjiaotang.cn")
ALLOWED_COMPATIBILITY_COMPONENTS = (
    "skills/_runtime/jiaotang-kb/jiaotang-agent.mjs",
)
HISTORICAL_RELEASE_POLICY = "preserve_immutable"
PUBLIC_SOURCE_PATHS = (
    Path("README.md"),
    Path("docs/config"),
    Path("docs/product"),
    Path("docs/user-guide"),
    Path("services/knowledge-portal/app/assistant_runtime.py"),
    Path("services/knowledge-portal/docs"),
    Path("services/knowledge-portal/mockups"),
    Path("services/knowledge-portal/static"),
    Path("services/knowledge-portal/templates"),
)
PUBLIC_SKILL_RUNTIME = Path("skills/_runtime/gongchuang-branding")
PORTAL_MAIN = Path("services/knowledge-portal/app/main.py")
LEGACY_PUBLIC_ROUTE = re.compile(
    r'^\s*@app\.(?:get|post|put|patch|delete)\(\s*["\']([^"\']*jiaotang[^"\']*)',
    re.IGNORECASE | re.MULTILINE,
)
ALLOWED_TEXT_PATTERNS = (
    re.compile(
        r"(?<![A-Za-z0-9_./-])"
        r"skills/_runtime/jiaotang-kb/jiaotang-agent\.mjs"
        r"(?![A-Za-z0-9_./-])"
    ),
    re.compile(r"(?<![A-Za-z0-9_-])jiaotang-kb(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9.-])zshjiaotang\.cn(?![A-Za-z0-9.-])"),
)


def _remove_allowed_text(text: str) -> str:
    cleaned = text
    for pattern in ALLOWED_TEXT_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned


def has_legacy_brand(blob: bytes) -> bool:
    for encoding in ("utf-8", "utf-16le", "utf-16be"):
        decoded = blob.decode(encoding, errors="ignore")
        cleaned = _remove_allowed_text(decoded)
        if "焦糖" in cleaned or re.search("jiaotang", cleaned, re.IGNORECASE):
            return True
    return False


def _path_has_legacy_brand(value: str) -> bool:
    cleaned = _remove_allowed_text(value)
    return "焦糖" in cleaned or "jiaotang" in cleaned.lower()


def _files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        return
    for candidate in sorted(path.rglob("*")):
        if candidate.is_file() and "__pycache__" not in candidate.parts:
            yield candidate


def audit_sources(root: Path) -> tuple[list[dict[str, str]], int]:
    findings: list[dict[str, str]] = []
    checked = 0
    source_roots = list(PUBLIC_SOURCE_PATHS)
    suite_path = root / "skills/suite-manifest.json"
    if suite_path.is_file():
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        source_roots.extend(
            Path("skills") / str(skill_name)
            for skill_name in suite.get("skills", [])
        )
        source_roots.extend((Path("skills/suite-manifest.json"), PUBLIC_SKILL_RUNTIME))
    for relative_root in source_roots:
        for path in _files(root / relative_root):
            checked += 1
            relative = path.relative_to(root).as_posix()
            if _path_has_legacy_brand(relative):
                findings.append({"kind": "public_path", "source": relative})
            if has_legacy_brand(path.read_bytes()):
                findings.append({"kind": "public_content", "source": relative})

    main_path = root / PORTAL_MAIN
    if main_path.is_file():
        checked += 1
        main_text = main_path.read_text(encoding="utf-8")
        if "焦糖" in main_text:
            findings.append(
                {"kind": "portal_python_visible_brand", "source": PORTAL_MAIN.as_posix()}
            )
        for match in LEGACY_PUBLIC_ROUTE.finditer(main_text):
            findings.append(
                {
                    "kind": "legacy_public_route",
                    "source": PORTAL_MAIN.as_posix(),
                    "detail": match.group(1),
                }
            )
    return findings, checked


def audit_archive(path: Path) -> tuple[list[dict[str, str]], int]:
    findings: list[dict[str, str]] = []
    checked = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            checked += 1
            if any(
                info.filename == component
                or info.filename.endswith("/" + component)
                for component in ALLOWED_COMPATIBILITY_COMPONENTS
            ):
                continue
            if _path_has_legacy_brand(info.filename):
                findings.append(
                    {
                        "kind": "archive_path",
                        "source": f"{path.name}:{info.filename}",
                    }
                )
            if has_legacy_brand(archive.read(info)):
                findings.append(
                    {
                        "kind": "archive_content",
                        "source": f"{path.name}:{info.filename}",
                    }
                )
    return findings, checked


def audit_asset_names(names: Iterable[str]) -> tuple[list[dict[str, str]], int]:
    findings = []
    checked = 0
    for name in names:
        checked += 1
        if "焦糖" in name or "jiaotang" in name.lower():
            findings.append({"kind": "release_asset_name", "source": name})
    return findings, checked


def verify_public_namespace(
    *,
    source_root: Path | None = None,
    archives: Iterable[Path] = (),
    asset_names: Iterable[str] = (),
) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    checked = 0
    scopes: list[str] = []
    if source_root is not None:
        source_findings, source_checked = audit_sources(source_root)
        findings.extend(source_findings)
        checked += source_checked
        scopes.append("public_sources")
    archive_paths = list(archives)
    for archive in archive_paths:
        archive_findings, archive_checked = audit_archive(archive)
        findings.extend(archive_findings)
        checked += archive_checked
    if archive_paths:
        scopes.append("release_archives")
    names = list(asset_names)
    asset_findings, asset_checked = audit_asset_names(names)
    findings.extend(asset_findings)
    checked += asset_checked
    if names:
        scopes.append("release_asset_names")
    return {
        "schema": "gongchuang-public-namespace-gate/v1",
        "status": "pass" if not findings else "fail",
        "public_brand": PUBLIC_BRAND,
        "allowed_identifiers": list(ALLOWED_IDENTIFIERS),
        "allowed_compatibility_components": list(
            ALLOWED_COMPATIBILITY_COMPONENTS
        ),
        "historical_release_policy": HISTORICAL_RELEASE_POLICY,
        "scopes": scopes,
        "checked": checked,
        "finding_count": len(findings),
        "findings": findings,
    }


def require_public_namespace(**kwargs: object) -> dict[str, object]:
    report = verify_public_namespace(**kwargs)
    if report["status"] != "pass":
        detail = "\n- ".join(
            f"{item['kind']}: {item['source']}"
            + (f" ({item['detail']})" if item.get("detail") else "")
            for item in report["findings"][:30]
        )
        raise RuntimeError("公开命名空间门禁失败：\n- " + detail)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="校验共创研究院公开命名空间")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument("--asset-name", action="append", default=[])
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    if (
        arguments.source_root is None
        and not arguments.archive
        and not arguments.asset_name
    ):
        parser.error("至少提供 --source-root、--archive 或 --asset-name")
    report = verify_public_namespace(
        source_root=arguments.source_root,
        archives=arguments.archive,
        asset_names=arguments.asset_name,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.report is not None:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

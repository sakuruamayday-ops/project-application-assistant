#!/usr/bin/env python3
"""Declarative WorkBuddy standalone single-skill bundler with strict isolation checks.

Builds self-contained single-skill directories and ZIP archives into dist/workbuddy/
directly from the single-source Git tree (zero duplicated runtime files committed to Git).
Automatically vendors lightweight shared references/policy MDs referenced via ../ links
and enforces strict commercial, link, and persona isolation gates on every built skill.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills"
DEFAULT_MANIFEST = REPO_ROOT / "config" / "workbuddy-bundles.json"
DEFAULT_OUT = REPO_ROOT / "dist" / "workbuddy"
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:<)?([^)\n>]+)(?:>)?\)")
INTERNAL_PERSONA = re.compile(r"主人")


def _matches_any(rel_posix: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(rel_posix, pattern):
            return True
        if pattern.endswith("/**") and (rel_posix == pattern[:-3] or rel_posix.startswith(pattern[:-2])):
            return True
    return False


def _relpath_posix(from_dir: Path, to_file: Path) -> str:
    return Path(os.path.relpath(to_file, from_dir)).as_posix()


def _format_link_target(target: str, fragment: str) -> str:
    full = f"{target}#{fragment}" if fragment else target
    return f"<{full}>" if " " in full else full


def _auto_vendor_and_rewrite(
    md_dest: Path,
    md_src: Path,
    skill_dir: Path,
    src_skill_dir: Path,
    rewrites: dict[str, str],
    tier: str,
) -> None:
    content = md_dest.read_text(encoding="utf-8")
    for old, new in sorted(rewrites.items(), key=lambda kv: -len(kv[0])):
        content = content.replace(old, new)

    resolved_skill = skill_dir.resolve()
    resolved_src_skill = src_skill_dir.resolve()
    resolved_skills_root = SKILLS_ROOT.resolve()

    def replace_match(match: re.Match[str]) -> str:
        label, raw_target = match.group(1), match.group(2).strip()
        if not raw_target or raw_target.startswith(("http://", "https://", "mailto:", "file://", "#")):
            return match.group(0)
        target_part, _, fragment = raw_target.partition("#")
        target_part = target_part.strip()
        if not target_part:
            return match.group(0)

        # Already inside built skill and exists? Keep as-is.
        dest_candidate = (md_dest.parent / target_part).resolve()
        try:
            dest_candidate.relative_to(resolved_skill)
            if dest_candidate.exists():
                return match.group(0)
        except ValueError:
            pass

        # Resolve against original source location in Git repo.
        src_candidate = (md_src.parent / target_part).resolve()
        # Check if it points to another skill's SKILL.md -> convert to non-linking skill badge
        if src_candidate.name == "SKILL.md" and src_candidate.parent != resolved_src_skill:
            return f"`{label}`"

        # If free tier references an excluded commercial .docx/.xlsx/.doc asset -> replace with plain text
        if tier in {"free-checkup", "free-data-mcp"} and src_candidate.suffix.lower() in {".docx", ".xlsx", ".doc"}:
            return f"《{label}》（收费 MCP 端提供）"

        # If link points to an excluded .pdf/.doc policy binary whose sibling .md exists -> point to .md
        if src_candidate.suffix.lower() in {".pdf", ".doc"}:
            sibling_md = src_candidate.with_suffix(".md")
            if sibling_md.is_file():
                src_candidate = sibling_md

        # If target is a lightweight readable file inside skills/ -> auto-vendor into references/_shared/
        try:
            rel_in_skills = src_candidate.relative_to(resolved_skills_root)
        except ValueError:
            rel_in_skills = None

        if rel_in_skills is not None and src_candidate.is_file() and src_candidate.suffix.lower() in {".md", ".json", ".py", ".txt"}:
            if src_candidate.suffix.lower() == ".py":
                vendored = skill_dir / "scripts" / src_candidate.name
            else:
                flat_name = rel_in_skills.name
                vendored = skill_dir / "references" / "_shared" / flat_name
            vendored.parent.mkdir(parents=True, exist_ok=True)
            if not vendored.exists():
                shutil.copy2(src_candidate, vendored)
                if vendored.suffix.lower() == ".md":
                    _auto_vendor_and_rewrite(vendored, src_candidate, skill_dir, src_skill_dir, rewrites, tier)
            new_rel = _relpath_posix(md_dest.parent, vendored)
            return f"[{label}]({_format_link_target(new_rel, fragment)})"

        # If it pointed to a non-existent or excluded large binary -> render as plain text without dead link
        if not src_candidate.exists() or src_candidate.suffix.lower() in {".pdf", ".doc", ".docx", ".xlsx"}:
            return f"`{label}`"

        return match.group(0)

    updated = MD_LINK_RE.sub(replace_match, content)
    md_dest.write_text(updated, encoding="utf-8")


def _build_skillhub_meta(bundle: dict[str, Any], version: str) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    return {
        "name": bundle["displayName"],
        "installedAt": now_ms,
        "source": "local",
        "version": version,
        "skillId": bundle["skillId"],
        "tier": bundle["tier"],
        "examples_zh": bundle["examplesZh"],
        "examples_en": bundle["examplesEn"],
        "description_zh": bundle["descriptionZh"],
        "description_en": bundle["descriptionEn"],
        "iconSource": "letter:auto",
        "skillName": bundle["skillName"],
    }


def _verify_built_skill(skill_dir: Path, bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    # 1. Exactly one SKILL.md at root (prevents WorkBuddy recursive dependency leaks).
    skill_mds = list(skill_dir.rglob("SKILL.md"))
    if skill_mds != [skill_dir / "SKILL.md"]:
        errors.append(f"必须且仅允许顶层存在 1 份 SKILL.md，实际发现：{[str(p.relative_to(skill_dir)) for p in skill_mds]}")

    # 2. Zero _runtime directory or portable_skill_runtime bloat.
    if (skill_dir / "_runtime").exists():
        errors.append("不得携带 _runtime 目录到单技能包")
    if list(skill_dir.rglob("portable_skill_runtime.py")):
        errors.append("不得携带冗余的 422 行 portable_skill_runtime.py")

    # 3. Free tiers commercial isolation: zero DOCX/XLSX/DOC commercial master assets.
    if bundle["tier"] in {"free-checkup", "free-data-mcp"}:
        leaked_masters = [
            str(p.relative_to(skill_dir))
            for p in skill_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in {".docx", ".xlsx", ".doc"}
        ]
        if leaked_masters:
            errors.append(f"免费技能包严禁泄露商业母版/受保护工作簿：{leaked_masters}")

    # 4. Every relative markdown link must resolve strictly inside skill_dir AND exist;
    #    zero internal persona leaks ("主人").
    resolved_root = skill_dir.resolve()
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".md", ".py", ".json"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = str(path.relative_to(skill_dir))
            if path.suffix.lower() == ".md":
                for _, raw_target in MD_LINK_RE.findall(text):
                    target = raw_target.strip().split("#", 1)[0].strip()
                    if not target or target.startswith(("http://", "https://", "mailto:", "file://")):
                        continue
                    resolved = (path.parent / target).resolve()
                    try:
                        resolved.relative_to(resolved_root)
                    except ValueError:
                        errors.append(f"{rel} 存在越出单技能根目录的链接：{raw_target}")
                        continue
                    if not resolved.exists():
                        errors.append(f"{rel} 存在死链（文件不存在）：{raw_target}")
            if INTERNAL_PERSONA.search(text):
                errors.append(f"{rel} 存在内部称呼「主人」泄露")

    # 5. Valid _skillhub_meta.json present.
    meta_path = skill_dir / "_skillhub_meta.json"
    if not meta_path.is_file():
        errors.append("缺少 WorkBuddy _skillhub_meta.json")
    else:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("skillId") != bundle["skillId"]:
            errors.append("_skillhub_meta.json 的 skillId 不匹配")

    return errors


def _pack_zip(skill_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path, "w") as archive:
        for path in sorted(skill_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(skill_dir).as_posix()
            data = path.read_bytes()
            info = ZipInfo(rel, (2026, 11, 24, 0, 0, 0))
            info.create_system = 3
            perms = 0o755 if data.startswith(b"#!") else 0o644
            info.external_attr = (stat.S_IFREG | perms) << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)


def build_all(manifest_path: Path, output_dir: Path, *, strict: bool = True) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("version", "2.0.0"))
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    all_errors: list[str] = []
    for bundle in manifest["bundles"]:
        src_dir = REPO_ROOT / bundle["sourceSkill"]
        if not src_dir.is_dir():
            raise FileNotFoundError(f"源技能目录不存在：{src_dir}")

        tier_dir = output_dir / bundle["tier"] / bundle["displayName"]
        tier_dir.mkdir(parents=True, exist_ok=True)
        excludes = list(bundle.get("excludeGlobs", [])) + [".DS_Store", "**/__pycache__/**", "**/*.pyc"]
        rewrites = dict(bundle.get("linkRewrites", {}))

        copied_mds: list[tuple[Path, Path]] = []
        for item in sorted(src_dir.rglob("*")):
            if item.is_dir():
                continue
            rel = item.relative_to(src_dir).as_posix()
            if _matches_any(rel, excludes):
                continue
            dest = tier_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            if item.suffix.lower() == ".md":
                copied_mds.append((dest, item))

        # Vendor explicit shared files from single-source tree.
        for vendor in bundle.get("vendorFiles", []):
            src_file = REPO_ROOT / vendor["from"]
            if not src_file.is_file():
                raise FileNotFoundError(f"内联共享文件不存在：{src_file}")
            dest_file = tier_dir / vendor["to"]
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_file)
            if src_file.suffix.lower() == ".md":
                copied_mds.append((dest_file, src_file))

        # Rewrite and auto-vendor any remaining relative markdown links cleanly.
        for md_dest, md_src in copied_mds:
            _auto_vendor_and_rewrite(md_dest, md_src, tier_dir, src_dir, rewrites, bundle["tier"])

        # Write WorkBuddy _skillhub_meta.json.
        meta = _build_skillhub_meta(bundle, version)
        (tier_dir / "_skillhub_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        # Verify built skill isolation and integrity.
        errors = _verify_built_skill(tier_dir, bundle)
        zip_path = output_dir / "zips" / f"{bundle['tier']}_{bundle['displayName']}.zip"
        _pack_zip(tier_dir, zip_path)
        size_kb = round(zip_path.stat().st_size / 1024, 1)
        file_count = sum(1 for p in tier_dir.rglob("*") if p.is_file())
        results.append(
            {
                "displayName": bundle["displayName"],
                "skillName": bundle["skillName"],
                "tier": bundle["tier"],
                "dir": str(tier_dir),
                "zip": str(zip_path),
                "file_count": file_count,
                "zip_size_kb": size_kb,
                "errors": errors,
            }
        )
        all_errors.extend(f"[{bundle['displayName']}] {err}" for err in errors)

    summary = {
        "status": "pass" if not all_errors else "fail",
        "version": version,
        "built_count": len(results),
        "tier_counts": {
            tier: sum(1 for r in results if r["tier"] == tier)
            for tier in ("free-checkup", "free-data-mcp", "paid-mcp-engine")
        },
        "bundles": results,
        "errors": all_errors,
    }
    if strict and all_errors:
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 WorkBuddy 自包含单技能目录与 ZIP 包")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-strict", action="store_true")
    args = parser.parse_args()
    summary = build_all(args.manifest, args.output, strict=not args.no_strict)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

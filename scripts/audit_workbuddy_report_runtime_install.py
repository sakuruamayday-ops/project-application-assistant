#!/usr/bin/env python3
"""Audit the active WorkBuddy report runtime before a real-host test."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"不可读取JSON:{path}:{exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"JSON根节点不是对象:{path}")
        return {}
    return value


def audit_install(
    plugin_root: Path,
    *,
    expected_release_tag: str,
    expected_skill_count: int = 50,
    expected_template_count: int = 24,
) -> dict[str, Any]:
    plugin_root = plugin_root.expanduser().resolve()
    errors: list[str] = []
    required = [
        plugin_root / ".codebuddy-plugin/plugin.json",
        plugin_root / "hooks/hooks.json",
        plugin_root / "scripts/workbuddy_behavior_hook.py",
        plugin_root / "skills/suite-manifest.json",
        plugin_root / "skills/project-feasibility/SKILL.md",
        plugin_root / "skills/project-feasibility/references/report-template-registry.json",
        plugin_root / "skills/project-feasibility/scripts/select_report_template.py",
        plugin_root / "skills/project-feasibility/scripts/fill_report_template.py",
        plugin_root / "skills/project-feasibility/scripts/validate_report_profile_delivery.py",
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"活动插件缺文件:{path.relative_to(plugin_root)}")

    plugin = _read_json(required[0], errors) if required[0].is_file() else {}
    suite_path = plugin_root / "skills/suite-manifest.json"
    suite = _read_json(suite_path, errors) if suite_path.is_file() else {}
    registry_path = plugin_root / "skills/project-feasibility/references/report-template-registry.json"
    registry = _read_json(registry_path, errors) if registry_path.is_file() else {}
    marketplace_path = plugin_root.parents[1] / ".codebuddy-plugin/marketplace.json"
    marketplace = _read_json(marketplace_path, errors) if marketplace_path.is_file() else {}

    expected_version = expected_release_tag.removeprefix("V")
    plugin_version = str(plugin.get("version") or "")
    suite_release_tag = str(suite.get("release", {}).get("tag") or "")
    registry_release_tag = str(registry.get("release_tag") or "")
    market_entries = marketplace.get("plugins") if isinstance(marketplace.get("plugins"), list) else []
    market_entry = next(
        (item for item in market_entries if str(item.get("name") or "") == plugin_root.name),
        {},
    )
    marketplace_version = str(market_entry.get("version") or "")
    for label, actual, expected in (
        ("plugin.json", plugin_version, expected_version),
        ("marketplace.json", marketplace_version, expected_version),
        ("suite-manifest.json", suite_release_tag, expected_release_tag),
        ("report-template-registry.json", registry_release_tag, expected_release_tag),
    ):
        if actual != expected:
            errors.append(f"版本漂移:{label}:{actual or 'missing'}!={expected}")

    skill_files = sorted((plugin_root / "skills").glob("*/SKILL.md"))
    manifest_skills = suite.get("skills") if isinstance(suite.get("skills"), list) else []
    if len(skill_files) != expected_skill_count:
        errors.append(f"活动Skill数量异常:{len(skill_files)}!={expected_skill_count}")
    if len(manifest_skills) != expected_skill_count:
        errors.append(f"清单Skill数量异常:{len(manifest_skills)}!={expected_skill_count}")

    project_skill_path = plugin_root / "skills/project-feasibility/SKILL.md"
    if project_skill_path.is_file():
        project_skill = project_skill_path.read_text(encoding="utf-8")
        if "<!-- BEGIN WORKBUDDY BEHAVIOR HOOK -->" not in project_skill:
            errors.append("project-feasibility缺WorkBuddy行为激活桥")
        if "workbuddy_behavior_hook.py" not in project_skill:
            errors.append("project-feasibility未指向当前Hook运行时")
        if "portable_skill_runtime.py" in project_skill:
            errors.append("project-feasibility仍引用已从WorkBuddy包移除的旧便携运行时")

    template_results: list[dict[str, Any]] = []
    for project in registry.get("projects", []):
        if not isinstance(project, dict):
            continue
        for report_type, template in (project.get("templates") or {}).items():
            if not isinstance(template, dict):
                continue
            path = plugin_root / "skills/project-feasibility" / str(template.get("path") or "")
            expected_hash = str(template.get("sha256") or "").lower()
            actual_hash = sha256_file(path) if path.is_file() else ""
            status = "pass" if len(expected_hash) == 64 and actual_hash == expected_hash else "fail"
            if status != "pass":
                errors.append(f"受控模板缺失或哈希漂移:{project.get('id')}/{report_type}")
            template_results.append(
                {
                    "project_id": project.get("id"),
                    "report_type": report_type,
                    "path": str(path),
                    "sha256": actual_hash,
                    "status": status,
                }
            )
    if len(template_results) != expected_template_count:
        errors.append(f"受控模板数量异常:{len(template_results)}!={expected_template_count}")

    return {
        "schema": "gongchuang-workbuddy-report-runtime-install-audit/v1",
        "status": "pass" if not errors else "fail",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "plugin_root": str(plugin_root),
        "expected_release_tag": expected_release_tag,
        "versions": {
            "plugin": plugin_version,
            "marketplace": marketplace_version,
            "suite": suite_release_tag,
            "template_registry": registry_release_tag,
        },
        "skill_count": len(skill_files),
        "manifest_skill_count": len(manifest_skills),
        "template_count": len(template_results),
        "template_results": template_results,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--expected-release-tag", required=True)
    parser.add_argument("--expected-skill-count", type=int, default=50)
    parser.add_argument("--expected-template-count", type=int, default=24)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_install(
        args.plugin_root,
        expected_release_tag=args.expected_release_tag,
        expected_skill_count=args.expected_skill_count,
        expected_template_count=args.expected_template_count,
    )
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        target = args.output.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

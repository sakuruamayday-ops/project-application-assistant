#!/usr/bin/env python3
"""Require deterministic behavior and exact-candidate gates for every Skill."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "skills" / "suite-manifest.json"


def discovered_skills() -> set[str]:
    """Return actual distributable skill directories instead of a stale count."""
    return {
        path.parent.name
        for path in (ROOT / "skills").glob("*/SKILL.md")
        if not path.parent.name.startswith("_")
    }


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    declared = set(manifest.get("skills") or [])
    discovered = discovered_skills()
    errors = []
    if declared != discovered:
        errors.append(
            "套件清单与实际可分发技能目录漂移："
            f"清单缺少{sorted(discovered - declared)}；"
            f"清单多出{sorted(declared - discovered)}"
        )
    plugin = manifest.get("workbuddy_plugin") or {}
    distribution = (manifest.get("release") or {}).get("distribution_protocol") or {}
    workbuddy_released = (
        distribution.get("workbuddy_specific_package") is True
        and plugin.get("package_mode") == "skills_minimal_behavior_hook"
    )
    generic_only = (
        distribution.get("workbuddy_specific_package") is False
        and plugin.get("package_mode") == "not-released"
    )
    if not (workbuddy_released or generic_only):
        errors.append("套件清单中的宿主专用包声明互相矛盾")
    post_package_gates = manifest.get("post_package_release_gates")
    post_gate_names = {
        str(item.get("name") or "")
        for item in post_package_gates or []
        if isinstance(item, dict)
    }
    expected_post_gate_names = {"generic-suite-isolated-installation"}
    if workbuddy_released:
        expected_post_gate_names.update(
            {
                "macos-platform-server-release-contract",
                "macos-platform-all-skill-coverage",
                "windows-platform-server-release-contract",
                "windows-platform-all-skill-coverage",
            }
        )
    if post_gate_names != expected_post_gate_names:
        errors.append("发布后门禁与套件清单声明的产物不一致")
    if distribution.get("generic_skill_package") != "signed-universal-zip":
        errors.append("缺少签名通用 Skills 包发布合同")
    if distribution.get("first_party_client") != "bundled-signed-skill-suite":
        errors.append("缺少共创独立客户端内置签名技能包合同")
    adversarial = json.loads(
        (ROOT / "tests" / "adversarial-expected.json").read_text(
            encoding="utf-8"
        )
    )
    routed = {
        str(item.get("expected_primary_skill") or "")
        for item in adversarial.get("answers") or []
        if isinstance(item, dict)
    }
    unknown = sorted(routed - declared)
    if unknown:
        errors.append(f"对抗路由包含套件外技能：{unknown}")
    result = {
        "status": "pass" if not errors else "fail",
        "declared_skills": len(declared),
        "discovered_skills": len(discovered),
        "adversarial_primary_skills": len(routed & declared),
        "distribution": "generic-signed-zip-plus-first-party-client",
        "workbuddy_specific_package": "released" if workbuddy_released else "not-released",
        "real_client_acceptance": "separate-client-release-required",
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

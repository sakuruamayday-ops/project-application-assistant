#!/usr/bin/env python3
"""Require deterministic behavior and exact-candidate gates for every Skill."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "skills" / "suite-manifest.json"
EXPECTED_SKILLS = {
    "agriculture-and-rural-projects",
    "application-version-diff",
    "application-writing",
    "checking-patdocx-cn-single-agent",
    "consistency-check",
    "digitalization-projects",
    "enterprise-panorama-analysis",
    "enterprise-profile",
    "evidence-ledger",
    "evolution-governance",
    "experience-recorder",
    "financial-verification",
    "first-run-configuration",
    "graphify",
    "green-development-projects",
    "high-tech-enterprise-application-drafting",
    "high-tech-enterprise-preassessment",
    "industrialization-projects",
    "industry-chain-foundation-matcher",
    "industry-positioning",
    "intellectual-property-projects",
    "investment-subsidy-projects",
    "ip-assessment",
    "gongchuang-humanizer-zh",
    "legal-regulations",
    "patent-router",
    "local-knowledge-retrieval",
    "manufacturing-tax-risk-analysis",
    "peer-benchmarking",
    "policy-retrieval",
    "project-application-assistant",
    "project-deliverable-archive",
    "project-feasibility",
    "project-matching",
    "project-memory",
    "project-rule-manager",
    "project-task-router",
    "quality-brand-projects",
    "regional-special-projects",
    "skill-authoring",
    "skill-curator",
    "skill-evolution",
    "sme-development-projects",
    "sme-score-preassessment",
    "standard-drafting",
    "talent-projects",
    "technology-innovation-projects",
    "third-party-data-indexing",
    "trade-and-open-economy-projects",
    "web-task-operator",
}


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    declared = set(manifest.get("skills") or [])
    errors = []
    if declared != EXPECTED_SKILLS:
        errors.append(
            "正式技能行为基线与套件清单漂移："
            f"缺少{sorted(EXPECTED_SKILLS - declared)}；"
            f"新增{sorted(declared - EXPECTED_SKILLS)}"
        )
    post_gates = {
        str(item.get("name") or ""): item
        for item in manifest.get("post_package_release_gates") or []
        if isinstance(item, dict)
    }
    required_platform_gates = {
        "workbuddy-macos-server-release-candidate-contract": (
            "{workbuddy_macos_archive}"
        ),
        "workbuddy-macos-all-skill-package-coverage": (
            "{workbuddy_macos_archive}"
        ),
        "workbuddy-windows-server-release-candidate-contract": (
            "{workbuddy_windows_archive}"
        ),
        "workbuddy-windows-all-skill-package-coverage": (
            "{workbuddy_windows_archive}"
        ),
    }
    for required, artifact_placeholder in required_platform_gates.items():
        gate = post_gates.get(required)
        command = gate.get("command") if isinstance(gate, dict) else None
        if not isinstance(command, list) or artifact_placeholder not in command:
            errors.append(f"缺少真实候选包门禁：{required}")
        if isinstance(command, list) and "{workbuddy_cli}" in command:
            errors.append(f"发布前候选包门禁不得启动真实 WorkBuddy CLI：{required}")
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
        "explicit_behavior_baseline": len(EXPECTED_SKILLS),
        "adversarial_primary_skills": len(routed & declared),
        "workbuddy_candidate_package_gates": "declared",
        "real_host_acceptance": "post-release-required",
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

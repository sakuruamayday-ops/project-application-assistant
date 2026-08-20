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
    "deep-clarification",
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
    plugin = manifest.get("workbuddy_plugin") or {}
    if plugin.get("package_mode") != "not-released":
        errors.append("V1.6.6 不得重新启用 WorkBuddy 专用包")
    post_package_gates = manifest.get("post_package_release_gates")
    if not isinstance(post_package_gates, list) or len(post_package_gates) != 1:
        errors.append("V1.6.7 必须声明唯一的通用包真实产物门禁")
    elif post_package_gates[0].get("name") != "generic-suite-isolated-installation":
        errors.append("V1.6.7 的发布后门禁必须验证通用包隔离安装")
    distribution = (manifest.get("release") or {}).get("distribution_protocol") or {}
    if distribution.get("generic_skill_package") != "signed-universal-zip":
        errors.append("缺少签名通用 Skills 包发布合同")
    if distribution.get("first_party_client") != "bundled-signed-skill-suite":
        errors.append("缺少共创独立客户端内置签名技能包合同")
    if distribution.get("workbuddy_specific_package") is not False:
        errors.append("WorkBuddy 专用包必须显式关闭")
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
        "distribution": "generic-signed-zip-plus-first-party-client",
        "workbuddy_specific_package": "not-released",
        "real_client_acceptance": "separate-v0.1-release-required",
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

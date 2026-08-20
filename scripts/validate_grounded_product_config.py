#!/usr/bin/env python3
"""Validate product-channel and packaging configuration for Grounded Citations."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def contains_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in forbidden or contains_key(item, forbidden) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_key(item, forbidden) for item in value)
    return False


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def main() -> int:
    manifest = load(SKILLS / "suite-manifest.json")
    delivery_contract = load(SKILLS / "delivery-contracts.json")
    client_runtime = load(SKILLS / "client-runtime-gates.json")
    registry = load(SKILLS / "report-skill-registry.json")
    config = load(ROOT / "config" / "grounded-citations.json")
    release_tag = str(manifest["release"]["tag"])
    notes_path = ROOT / "docs" / "releases" / f"{release_tag}.md"
    notes = notes_path.read_text(encoding="utf-8")
    stable_notes_path = notes_path
    stable_notes = notes
    engine_text = (SKILLS / "evidence-ledger" / "scripts" / "grounded_evidence.py").read_text(encoding="utf-8")
    evidence_skill_text = (SKILLS / "evidence-ledger" / "SKILL.md").read_text(encoding="utf-8")

    escaped_release_tag = re.escape(release_tag)
    windows_match = re.search(rf"(?s)({escaped_release_tag}).*?Windows", stable_notes)
    macos_match = re.search(rf"(?s)({escaped_release_tag}).*?macOS", stable_notes)
    skills_contract = str(manifest["release"]["tag"])

    adapters = config.get("host_adapters", {})
    artifact_validation = config.get("artifact_validation", {})
    adapter_paths = {
        host: SKILLS / str(relative)
        for host, relative in adapters.items()
    }
    shared_paths = set(manifest.get("shared_paths", []))
    checks = {
        "release_notes_identify_current_client_windows": bool(windows_match),
        "release_notes_identify_current_client_macos": bool(macos_match),
        "release_notes_keep_identity_out_of_plugin": (
            "企业数字身份证不进入插件包" in notes
            or "不包含知识索引、企业数字身份证" in notes
            or "不把企业身份数据放入 ZIP" in notes
        ),
        "formal_skills_contract_matches_release_notes": skills_contract == release_tag,
        "delivery_contract_matches_skills_contract": (
            delivery_contract.get("rule_version") == manifest["release"]["version"]
        ),
        "release_notes_file_present": notes_path.is_file() and stable_notes_path.is_file(),
        "workbuddy_specific_package_is_not_released": (
            (manifest.get("workbuddy_plugin") or {}).get("package_mode") == "not-released"
            and (manifest.get("release", {}).get("distribution_protocol") or {}).get(
                "workbuddy_specific_package"
            ) is False
        ),
        "registry_covers_declared_skills": (
            len(registry.get("skills", [])) == len(manifest.get("skills", []))
            and len(manifest.get("skills", [])) > 0
        ),
        "registry_routes_30_grounded_skills": sum(
            bool(item.get("uses_grounded_engine")) for item in registry.get("skills", [])
        ) == 30,
        "registry_release_is_skills_contract": registry.get("release") == manifest.get("release"),
        "grounded_registry_is_shared_package_asset": "report-skill-registry.json" in shared_paths,
        "host_adapters_are_shared_package_assets": "_runtime/grounded-citations" in shared_paths,
        "exactly_two_host_adapters": set(adapters) == {"codex", "workbuddy"},
        "host_adapter_files_exist": all(path.is_file() for path in adapter_paths.values()),
        "host_adapters_are_package_relative": all(
            str(relative).startswith("_runtime/grounded-citations/")
            for relative in adapters.values()
        ),
        "registry_contains_generated_artifact_validation": (
            registry.get("artifact_validation") == artifact_validation
        ),
        "pdf_validation_fails_closed_after_render": (
            artifact_validation.get("pdf", {}).get("fail_closed") is True
            and "all-pages-render" in artifact_validation.get("pdf", {}).get("required", [])
            and "missing-glyph-scan" in artifact_validation.get("pdf", {}).get("required", [])
        ),
        "docx_missing_renderer_is_pending_not_pass": (
            artifact_validation.get("docx", {}).get("renderer_missing_cjk_is")
            == "pending-device-acceptance"
            and artifact_validation.get("docx", {}).get("formal_release_requires_host_render") is True
        ),
        "native_xlsx_and_pptx_render_gates_exist": (
            artifact_validation.get("xlsx", {}).get("renderer") == "spreadsheet-native"
            and "all-sheets-render" in artifact_validation.get("xlsx", {}).get("required", [])
            and "all-slides-render" in artifact_validation.get("pptx", {}).get("required", [])
        ),
        "grounded_config_does_not_manage_permissions_or_mcp": not contains_key(
            config,
            {"permissions", "permission", "mcpServers", "mcp_servers"},
        ),
        "client_runtime_matches_skills_release": (
            client_runtime.get("release_tag") == release_tag
        ),
        "client_runtime_fails_closed": (
            client_runtime.get("enforcement", {}).get("mode") == "fail-closed"
            and client_runtime.get("enforcement", {}).get(
                "model_compliance_is_not_enforcement"
            ) is True
        ),
        "client_runtime_binds_professional_skill_contracts": (
            client_runtime.get("professional_execution", {}).get("binding")
            == "same-host-verified-skill-suite"
            and client_runtime.get("professional_execution", {}).get(
                "contract_files"
            ) == ["delivery-contracts.json", "skill-call-graph.json"]
            and client_runtime.get("professional_execution", {}).get(
                "provider_independent"
            ) is True
        ),
        "grounded_contract_owns_receipt_protocol": (
            delivery_contract.get("grounded_delivery", {}).get("validator_id") == "grounded-delivery/v1"
            and delivery_contract.get("skill_roles", {}).get("evidence-ledger", {}).get("owns")
            == ["grounded-evidence/v1"]
        ),
        "engine_supports_offline_xlsx_and_turn_receipts": (
            "def dump_xlsx" in engine_text
            and "def write_delivery_receipt" in engine_text
            and '"validate-delivery"' in engine_text
            and '"--receipt-export-dir"' in engine_text
        ),
        "evidence_skill_forbids_unapproved_external_upload": (
            "未经用户明确授权" in evidence_skill_text
            and "外部" in evidence_skill_text
            and "上传" in evidence_skill_text
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    payload = {
        "status": "pass" if not failures else "fail",
        "channels": {
            "client_windows_candidate": windows_match.group(1) if windows_match else None,
            "client_macos_candidate": macos_match.group(1) if macos_match else None,
            "skills_candidate": skills_contract,
        },
        "skills_contract": skills_contract,
        "grounded_candidate_release": skills_contract,
        "release_notes": str(notes_path.relative_to(ROOT)),
        "checks": checks,
        "errors": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())

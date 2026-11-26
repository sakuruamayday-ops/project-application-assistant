#!/usr/bin/env python3
"""Validate V3 10-skill product-channel and grounded-citations runtime configuration."""

from __future__ import annotations

import json
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


def main() -> int:
    manifest = load(SKILLS / "suite-manifest.json")
    bundles_cfg = load(ROOT / "config" / "workbuddy-bundles.json")
    config = load(ROOT / "config" / "grounded-citations.json")
    engine_path = SKILLS / "manufacturing-tax-risk" / "scripts" / "grounded_evidence.py"
    engine_text = engine_path.read_text(encoding="utf-8") if engine_path.is_file() else ""

    declared_skills = list(manifest.get("skills", []))
    bundled_skills = [str(b.get("skillName") or "") for b in bundles_cfg.get("bundles", [])]
    adapters = config.get("host_adapters", {})
    adapter_paths = {host: SKILLS / str(rel) for host, rel in adapters.items()}

    checks = {
        "suite_has_10_v3_skills": len(declared_skills) == 10,
        "all_declared_skills_exist": all((SKILLS / s / "SKILL.md").is_file() for s in declared_skills),
        "bundles_match_declared_10_skills": set(bundled_skills) == set(declared_skills) and len(bundled_skills) == 10,
        "grounded_engine_present": engine_path.is_file(),
        "engine_supports_offline_xlsx_and_turn_receipts": (
            "def dump_xlsx" in engine_text
            and "def write_delivery_receipt" in engine_text
            and '"validate-delivery"' in engine_text
            and '"--receipt-export-dir"' in engine_text
        ),
        "exactly_two_host_adapters": set(adapters) == {"codex", "first_party_client"},
        "host_adapter_files_exist": all(p.is_file() for p in adapter_paths.values()),
        "host_adapters_point_to_existing_engine": all(
            "manufacturing-tax-risk" in p.read_text(encoding="utf-8")
            for p in adapter_paths.values()
            if p.is_file()
        ),
        "grounded_config_does_not_manage_permissions_or_mcp": not contains_key(
            config, {"permissions", "permission", "mcpServers", "mcp_servers"}
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    payload = {
        "status": "pass" if not failures else "fail",
        "release": manifest.get("release", {}),
        "skill_count": len(declared_skills),
        "checks": checks,
        "errors": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())

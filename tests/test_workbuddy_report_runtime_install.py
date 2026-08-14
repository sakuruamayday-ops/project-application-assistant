from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_workbuddy_report_runtime_install.py"
SPEC = importlib.util.spec_from_file_location("workbuddy_install_audit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def build_fixture(tmp_path: Path) -> Path:
    marketplace = tmp_path / "marketplace"
    plugin = marketplace / "plugins/plugin"
    template_root = plugin / "skills/project-feasibility/assets/report-templates/demo"
    template_root.mkdir(parents=True)
    templates = {}
    for report_type in ("preassessment", "feasibility"):
        path = template_root / f"{report_type}.docx"
        path.write_bytes(f"template-{report_type}".encode())
        templates[report_type] = {
            "path": f"assets/report-templates/demo/{report_type}.docx",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    write_json(plugin / ".codebuddy-plugin/plugin.json", {"version": "1.6.5.2"})
    write_json(
        marketplace / ".codebuddy-plugin/marketplace.json",
        {"plugins": [{"name": "plugin", "version": "1.6.5.2"}]},
    )
    write_json(
        plugin / "skills/suite-manifest.json",
        {"release": {"tag": "V1.6.5.2"}, "skills": [{"name": "project-feasibility"}]},
    )
    write_json(
        plugin / "skills/project-feasibility/references/report-template-registry.json",
        {
            "release_tag": "V1.6.5.2",
            "projects": [{"id": "demo", "templates": templates}],
        },
    )
    skill = plugin / "skills/project-feasibility/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: project-feasibility\n---\n"
        "<!-- BEGIN WORKBUDDY BEHAVIOR HOOK -->\nworkbuddy_behavior_hook.py\n",
        encoding="utf-8",
    )
    for path in (
        plugin / "hooks/hooks.json",
        plugin / "scripts/workbuddy_behavior_hook.py",
        plugin / "skills/project-feasibility/scripts/select_report_template.py",
        plugin / "skills/project-feasibility/scripts/fill_report_template.py",
        plugin / "skills/project-feasibility/scripts/validate_report_profile_delivery.py",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    return plugin


def test_install_audit_passes_exact_active_runtime_and_rejects_version_drift(tmp_path):
    plugin = build_fixture(tmp_path)
    result = MODULE.audit_install(
        plugin,
        expected_release_tag="V1.6.5.2",
        expected_skill_count=1,
        expected_template_count=2,
    )
    assert result["status"] == "pass"
    write_json(plugin / ".codebuddy-plugin/plugin.json", {"version": "1.6.5"})
    result = MODULE.audit_install(
        plugin,
        expected_release_tag="V1.6.5.2",
        expected_skill_count=1,
        expected_template_count=2,
    )
    assert result["status"] == "fail"
    assert "版本漂移:plugin.json:1.6.5!=1.6.5.2" in result["errors"]

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "skills" / "suite-manifest.json").read_text(encoding="utf-8"))


def test_v167_releases_one_signed_generic_suite_and_verifies_isolated_installation():
    distribution = MANIFEST["release"]["distribution_protocol"]
    assert distribution["generic_skill_package"] == "signed-universal-zip"
    assert distribution["workbuddy_specific_package"] is False
    assert MANIFEST["workbuddy_plugin"]["package_mode"] == "not-released"
    assert MANIFEST["post_package_release_gates"] == [
        {
            "name": "generic-suite-isolated-installation",
            "command": [
                "{python}",
                "scripts/post_release_skill_gate.py",
                "--development-root",
                "skills",
                "--release-archive",
                "{generic_archive}",
                "--install-root",
                "{gate_output}/installed-skills",
                "--config-dir",
                "{gate_output}/config",
                "--audit-dir",
                "{gate_output}/audit",
                "--report",
                "{gate_output}/report.json",
            ],
            "timeout_seconds": 180,
        }
    ]


def test_generic_only_builder_does_not_create_disabled_workbuddy_assets():
    script = (ROOT / "scripts" / "package_generic_skill_suite.py").read_text(
        encoding="utf-8"
    )
    assert "package_skill_suite.py" in script
    assert "package_workbuddy_suite.py" not in script
    assert "suite-manifest disables WorkBuddy assets" in script

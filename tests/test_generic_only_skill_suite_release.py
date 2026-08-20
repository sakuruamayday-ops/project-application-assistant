from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "skills" / "suite-manifest.json").read_text(encoding="utf-8"))


def test_v167_releases_signed_generic_and_platform_pair_with_real_artifact_gates():
    distribution = MANIFEST["release"]["distribution_protocol"]
    assert distribution["generic_skill_package"] == "signed-universal-zip"
    assert distribution["workbuddy_specific_package"] is True
    assert (
        MANIFEST["workbuddy_plugin"]["package_mode"]
        == "skills_minimal_behavior_hook"
    )
    assert MANIFEST["workbuddy_plugin"]["release_matrix"]["hosts"] == [
        "macos",
        "windows",
    ]
    assert {
        item["name"] for item in MANIFEST["post_package_release_gates"]
    } == {
        "generic-suite-isolated-installation",
        "macos-platform-server-release-contract",
        "macos-platform-all-skill-coverage",
        "windows-platform-server-release-contract",
        "windows-platform-all-skill-coverage",
    }


def test_collection_builder_creates_both_platform_assets():
    script = (
        Path.home()
        / ".codex/skills/skill-release-manager/scripts/package_skill_collection.py"
    ).read_text(
        encoding="utf-8"
    )
    assert "package_skill_suite.py" in script
    assert "package_workbuddy_suite.py" in script
    assert 'for platform in ("macos", "windows")' in script

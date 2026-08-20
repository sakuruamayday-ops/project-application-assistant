from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "skills" / "suite-manifest.json").read_text(encoding="utf-8"))


def test_v168_releases_signed_generic_and_platform_pair_with_real_artifact_gates():
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
    generic_gate = next(
        item
        for item in MANIFEST["post_package_release_gates"]
        if item["name"] == "generic-suite-isolated-installation"
    )
    assert generic_gate["command"][-2:] == ["--workspace-root", "{gate_output}"]
    assert MANIFEST["generic_shared_paths"] == ["_runtime/jiaotang-kb"]
    assert "_runtime/jiaotang-kb" not in MANIFEST["shared_paths"]


def test_collection_builder_creates_both_platform_assets():
    manager_root = Path(
        os.environ.get(
            "JIAOTANG_RELEASE_MANAGER_ROOT",
            Path.home() / ".codex/skills/skill-release-manager",
        )
    )
    script_path = manager_root / "scripts/package_skill_collection.py"
    if not script_path.is_file():
        pytest.skip("skill-release-manager 是独立管理员工具，CI 不安装本机技能")
    script = script_path.read_text(
        encoding="utf-8"
    )
    assert "package_skill_suite.py" in script
    assert "package_workbuddy_suite.py" in script
    assert 'for platform in ("macos", "windows")' in script
    generic_builder = script_path.with_name("package_skill_suite.py").read_text(
        encoding="utf-8"
    )
    assert 'suite_manifest.get("generic_shared_paths", [])' in generic_builder

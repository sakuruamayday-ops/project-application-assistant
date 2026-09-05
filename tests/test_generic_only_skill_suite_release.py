from __future__ import annotations

import json
import os
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "skills" / "suite-manifest.json").read_text(encoding="utf-8"))


def load_generic_builder():
    path = ROOT / "scripts" / "package_generic_skill_suite.py"
    spec = importlib.util.spec_from_file_location("generic_skill_suite_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_release_uses_generic_and_first_party_client_without_platform_plugin_assets():
    distribution = MANIFEST["release"]["distribution_protocol"]
    assert distribution["generic_skill_package"] == "signed-universal-zip"
    assert distribution["platform_specific_package"] is False
    assert "workbuddy_plugin" not in MANIFEST
    assert {
        item["name"] for item in MANIFEST["post_package_release_gates"]
    } == {
        "generic-suite-isolated-installation",
    }
    generic_gate = next(
        item
        for item in MANIFEST["post_package_release_gates"]
        if item["name"] == "generic-suite-isolated-installation"
    )
    assert generic_gate["command"][-2:] == ["--workspace-root", "{gate_output}"]
    assert MANIFEST["generic_shared_paths"] == []
    assert "_runtime/jiaotang-kb" not in MANIFEST["shared_paths"]


def test_generic_only_builder_is_the_active_collection_path():
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
    generic_only = (ROOT / "scripts" / "package_generic_skill_suite.py").read_text(encoding="utf-8")
    assert 'distribution.get("platform_specific_package") is False' in generic_only
    assert 'manifest.get("workbuddy_plugin"' not in generic_only
    generic_builder = script_path.with_name("package_skill_suite.py").read_text(
        encoding="utf-8"
    )
    assert 'suite_manifest.get("generic_shared_paths", [])' in generic_builder


def test_generic_only_builder_detects_existing_immutable_gate_evidence(tmp_path: Path):
    builder = load_generic_builder()
    report = tmp_path / "release-gates-V1.6.17.json"
    signature = report.with_name(report.name + ".sig")
    signature.write_text("occupied", encoding="utf-8")

    assert builder.existing_gate_attestation_paths(report) == [signature]

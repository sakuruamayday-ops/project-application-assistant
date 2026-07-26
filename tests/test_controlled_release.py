from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "controlled_release.py"
SPEC = importlib.util.spec_from_file_location("controlled_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_normalize_version_uses_one_public_version_model() -> None:
    assert MODULE.normalize_version("V1.2") == ("1.2", "1.2.0", "V1.2")
    assert MODULE.normalize_version("1.2.0") == ("1.2", "1.2.0", "V1.2")
    with pytest.raises(ValueError):
        MODULE.normalize_version("1.2.3")


def test_prepare_assets_contains_only_release_files(tmp_path) -> None:
    generic = tmp_path / "generic.zip"
    workbuddy = tmp_path / "workbuddy.zip"
    gate = tmp_path / "gate.json"
    for path in (generic, workbuddy, gate):
        path.write_text(path.name, encoding="utf-8")

    assets = MODULE.prepare_ascii_assets(
        tmp_path / "assets",
        "V1.3",
        generic,
        workbuddy,
        gate,
    )

    assert [path.name for path in assets] == [
        "jiaotang-skills-V1.3.zip",
        "jiaotang-skills-V1.3-WorkBuddy.zip",
        "jiaotang-skills-V1.3-release-gate.json",
    ]

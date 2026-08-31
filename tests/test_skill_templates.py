from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from docx import Document


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_skill_templates.py"
SPEC = importlib.util.spec_from_file_location("validate_skill_templates", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_current_suite_templates_complete_initial_baseline() -> None:
    result = MODULE.validate_templates(
        ROOT,
        expected_office_count=29,
        expected_source_count=4,
    )

    assert result["status"] == "pass"
    assert result["office_template_count"] == 29
    assert result["source_template_count"] == 4
    assert len(result["templates"]) == 33


def test_discovery_rejects_legacy_template_even_when_other_template_is_valid(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "skills" / "demo" / "assets"
    assets.mkdir(parents=True)
    Document().save(assets / "formal.docx")
    (assets / "legacy.doc").write_bytes(b"legacy")

    with pytest.raises(MODULE.TemplateValidationError, match="旧式"):
        MODULE.discover_templates(tmp_path)


def test_validation_rejects_corrupt_ooxml_template(tmp_path: Path) -> None:
    assets = tmp_path / "skills" / "demo" / "assets"
    assets.mkdir(parents=True)
    (assets / "broken.docx").write_bytes(b"not-a-docx")

    with pytest.raises(Exception):
        MODULE.validate_templates(tmp_path, expected_office_count=1)

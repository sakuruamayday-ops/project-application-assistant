import importlib.util
import json
from pathlib import Path


VALIDATOR_PATH = (
    Path.home()
    / ".codex"
    / "skills"
    / "skill-release-manager"
    / "scripts"
    / "suite_validation.py"
)
SPEC = importlib.util.spec_from_file_location("suite_validation", VALIDATOR_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_skill(root: Path, name: str, body: str) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\n---\n\n{body}\n",
        encoding="utf-8",
    )


def write_manifest(root: Path, external_services: list[str]) -> None:
    (root / "suite-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product_name": "test",
                "product_slug": "test-suite",
                "install_mode": "bundle-only",
                "expected_skill_count": 1,
                "shared_paths": [],
                "dependencies": {},
                "allowed_external_skills": [],
                "external_services": external_services,
                "ignored_reference_tokens": [],
            }
        ),
        encoding="utf-8",
    )


def test_declared_external_service_is_not_treated_as_missing_skill(tmp_path):
    write_skill(tmp_path, "example-skill", "连接 `jiaotang-kb` MCP。")
    write_manifest(tmp_path, ["jiaotang-kb"])
    result = MODULE.validate_suite(tmp_path)
    assert result["status"] == "pass", result["errors"]
    assert result["external_services"] == ["jiaotang-kb"]


def test_undeclared_external_service_is_still_blocked(tmp_path):
    write_skill(tmp_path, "example-skill", "连接 `jiaotang-kb` MCP。")
    write_manifest(tmp_path, [])
    result = MODULE.validate_suite(tmp_path)
    assert result["status"] == "fail"
    assert "jiaotang-kb" in result["unresolved_references"]

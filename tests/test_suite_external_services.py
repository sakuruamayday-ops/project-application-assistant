import importlib.util
import json
import re
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
RELEASE_SCRIPT = VALIDATOR_PATH.with_name("package_skill_release.py")


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
                "release": {"tag": "V1.0", "version": "1.0.0"},
                "skills": ["example-skill"],
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


def test_managed_portable_runtime_template_stays_compact():
    text = RELEASE_SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r'block = f"""([\s\S]*?)"""',
        text,
    )
    assert match is not None
    template = match.group(1)
    assert len(template) < 850
    assert "portable_skill_runtime.py" in template
    assert "workbuddy_preference_bridge.py" in template
    assert "真实性、安全、验签和质量门禁" in template

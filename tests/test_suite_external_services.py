import importlib.util
import json
import re
import unittest
from pathlib import Path


VALIDATOR_PATH = (
    Path.home()
    / ".codex"
    / "skills"
    / "skill-release-manager"
    / "scripts"
    / "suite_validation.py"
)
if not VALIDATOR_PATH.is_file():
    raise unittest.SkipTest(
        "requires the separately installed skill-release-manager host integration"
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


def test_source_skills_keep_one_host_neutral_portable_protocol():
    repository = Path(__file__).resolve().parents[1]
    protocols = []
    for path in sorted((repository / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        assert "<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->" not in text, path
        assert "portable_skill_runtime.py prepare" not in text, path
        protocol = path.parent / "references/portable-runtime-protocol.md"
        assert protocol.is_file(), path
        protocols.append(protocol.read_text(encoding="utf-8"))
    assert len(protocols) == 51
    assert len(set(protocols)) == 1
    protocol = protocols[0]
    for field in ("宿主", "签名", "偏好", "用户资料", "直接输出"):
        assert field in protocol

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


def test_distributed_portable_runtime_blocks_are_compact_and_host_neutral():
    repository = Path(__file__).resolve().parents[1]
    blocks = []
    for path in sorted((repository / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(
            r"<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->([\s\S]*?)<!-- END MANAGED PORTABLE SKILL RUNTIME -->",
            text,
        )
        assert match is not None, path
        block = match.group(1)
        assert len(block) < 700, path
        assert "portable_skill_runtime.py" in block
        assert "workbuddy_preference_bridge.py" not in block
        assert "真实性、安全、验签和质量门禁" in block
        assert "await tools.<name>(...)" in block
        assert "不得为理解用法预读脚本、模板、示例或测试" in block
        blocks.append(block)
    # 中文注释：这是发布器托管的公共说明，任何单项技能漂移都会让
    # Agent 在不同业务中采用不同的工具调用和源码读取策略。
    assert len(set(blocks)) == 1

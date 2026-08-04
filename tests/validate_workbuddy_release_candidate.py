#!/usr/bin/env python3
"""Validate the exact WorkBuddy candidate without launching a real host.

Real macOS and Windows WorkBuddy installation and tool-call acceptance are
deliberately post-release checks. These pre-release gates inspect the exact
server-verified candidate that will be published.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PORTAL_SCRIPTS = ROOT / "services" / "knowledge-portal" / "scripts"
sys.path.insert(0, str(PORTAL_SCRIPTS))

from publish_skill_release import validate_release_packages  # noqa: E402


OFFICIAL_FINGERPRINT = "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
EXPECTED_SKILL_COUNT = 49
EXPECTED_VERSION = json.loads(
    (ROOT / "skills/suite-manifest.json").read_text(encoding="utf-8")
)["release"]["version"]
FORBIDDEN_PATH_SUFFIXES = (
    "/.mcp.json",
    "/bin/run-node",
    "/bin/run-node.cmd",
    "/mcp/jiaotang-agent.mjs",
    "/scripts/plugin_preference_bridge.py",
    "/plugin-release-manifest.json",
    "/plugin-release-manifest.sig",
)
FORBIDDEN_TEXT_MARKERS = (
    "jiaotang_kb_setup",
    "bootstrap_url",
    "macOS 钥匙串",
    "Windows DPAPI",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校验正式 WorkBuddy 候选包的服务端完整性、结构与技能覆盖"
    )
    parser.add_argument("--suite-zip", type=Path, required=True)
    parser.add_argument(
        "--check",
        choices=("server-release-contract", "all-skill-coverage"),
        required=True,
    )
    return parser.parse_args()


def unique_name(names: set[str], suffix: str) -> str:
    matches = sorted(name for name in names if name.endswith(suffix))
    if len(matches) != 1:
        raise RuntimeError(f"候选包必须且只能包含一个 {suffix}：{matches}")
    return matches[0]


def load_json(archive: zipfile.ZipFile, name: str) -> dict[str, object]:
    payload = json.loads(archive.read(name))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{name} 根节点必须是对象")
    return payload


def validate_server_release_contract(suite_zip: Path) -> dict[str, object]:
    validation = validate_release_packages({"workbuddy": suite_zip}, EXPECTED_VERSION)
    artifact = validation["artifacts"]["workbuddy"]
    integrity = artifact["integrity"]
    if integrity.get("status") != "verified":
        raise RuntimeError("WorkBuddy 候选包完整性未验证")
    if integrity.get("publisher_fingerprint") != OFFICIAL_FINGERPRINT:
        raise RuntimeError("WorkBuddy 候选包发布者指纹不匹配")
    if integrity.get("outer_fixed_installers") is not False:
        raise RuntimeError("WorkBuddy 候选包不得包含外层固定安装器")
    if integrity.get("verification_scope") != "server_release_channel":
        raise RuntimeError("WorkBuddy 候选包未经服务端发布通道验证")
    if integrity.get("hook_mode") != "behavior_only_fail_open":
        raise RuntimeError("WorkBuddy 必须使用失败放行的最小行为 Hook")
    if integrity.get("mcp_configuration_mode") != "user_remote_streamable_http":
        raise RuntimeError("WorkBuddy 必须使用用户级远程 HTTP MCP")
    if integrity.get("embedded_user_token") is not False:
        raise RuntimeError("WorkBuddy 公共候选包不得内置用户 Token")
    return {
        "status": "pass",
        "check": "server-release-contract",
        "sha256": artifact["sha256"],
        "publisher_fingerprint": integrity["publisher_fingerprint"],
        "verified_files": integrity["verified_files"],
        "verification_scope": integrity["verification_scope"],
        "hook_mode": integrity["hook_mode"],
        "mcp_configuration_mode": integrity["mcp_configuration_mode"],
    }


def validate_all_skill_coverage(suite_zip: Path) -> dict[str, object]:
    with zipfile.ZipFile(suite_zip) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("WorkBuddy 候选包 ZIP 完整性失败")
        names = set(archive.namelist())
        plugin_name = unique_name(names, "/.codebuddy-plugin/plugin.json")
        plugin_root = str(PurePosixPath(plugin_name).parent.parent)
        suite_name = f"{plugin_root}/skills/suite-manifest.json"
        hooks_name = f"{plugin_root}/hooks/hooks.json"
        plugin = load_json(archive, plugin_name)
        platform = str(plugin.get("platform") or "")
        behavior_hook_name = (
            f"{plugin_root}/scripts/workbuddy_behavior_hook_windows.exe"
            if platform == "windows"
            else f"{plugin_root}/scripts/workbuddy_behavior_hook.py"
        )
        forbidden_paths = sorted(
            name
            for name in names
            if any(name.endswith(suffix) for suffix in FORBIDDEN_PATH_SUFFIXES)
        )
        if forbidden_paths:
            raise RuntimeError(f"候选包含已停用组件：{forbidden_paths}")
        missing_minimal_files = sorted(
            {suite_name, hooks_name, behavior_hook_name} - names
        )
        if missing_minimal_files:
            raise RuntimeError(f"候选包缺少最小运行文件：{missing_minimal_files}")

        suite = load_json(archive, suite_name)
        hooks = load_json(archive, hooks_name)
        declared_skills = list(suite.get("skills") or [])
        plugin_skills = [
            str(item).removeprefix("./skills/")
            for item in list(plugin.get("skills") or [])
        ]
        if len(declared_skills) != EXPECTED_SKILL_COUNT:
            raise RuntimeError(f"套件技能数量不是 {EXPECTED_SKILL_COUNT}")
        if len(set(declared_skills)) != EXPECTED_SKILL_COUNT:
            raise RuntimeError("套件技能存在重复项")
        if plugin_skills != declared_skills:
            raise RuntimeError("插件技能清单与套件清单不一致")
        missing_skills = sorted(
            skill
            for skill in declared_skills
            if f"{plugin_root}/skills/{skill}/SKILL.md" not in names
        )
        if missing_skills:
            raise RuntimeError(f"候选包缺少技能入口：{missing_skills}")
        skill_names_from_frontmatter = []
        for skill in declared_skills:
            entry = f"{plugin_root}/skills/{skill}/SKILL.md"
            content = archive.read(entry).decode("utf-8")
            if not content.startswith("---\n"):
                raise RuntimeError(f"技能frontmatter不是首字节内容：{skill}")
            frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", content, re.DOTALL)
            if not frontmatter:
                raise RuntimeError(f"技能frontmatter不完整：{skill}")
            names_in_entry = [
                line.split(":", 1)[1].strip().strip("'\"")
                for line in frontmatter.group(1).splitlines()
                if line.startswith("name:")
            ]
            if names_in_entry != [skill]:
                raise RuntimeError(f"技能名称与目录不一致：{skill}")
            hook_position = content.find("<!-- BEGIN WORKBUDDY BEHAVIOR HOOK -->")
            if hook_position < frontmatter.end():
                raise RuntimeError(f"行为Hook未位于frontmatter之后：{skill}")
            skill_names_from_frontmatter.append(names_in_entry[0])
        if len(set(skill_names_from_frontmatter)) != EXPECTED_SKILL_COUNT:
            raise RuntimeError("技能frontmatter名称不是49项唯一值")
        if plugin.get("hook_mode") != "behavior_only_fail_open":
            raise RuntimeError("插件未声明最小行为 Hook 模式")
        if plugin.get("mcp_configuration_mode") != "user_remote_streamable_http":
            raise RuntimeError("插件未声明用户级远程 MCP 模式")
        if "mcpServers" in plugin:
            raise RuntimeError("公共插件清单不得内嵌用户 MCP 配置")
        if platform == "windows":
            if not archive.read(behavior_hook_name).startswith(b"MZ"):
                raise RuntimeError("Windows原生Hook不是有效PE文件")
            forbidden_runtime = (
                f"{plugin_root}/scripts/workbuddy_behavior_hook.py"
            )
        else:
            forbidden_runtime = (
                f"{plugin_root}/scripts/workbuddy_behavior_hook_windows.exe"
            )
        if forbidden_runtime in names:
            raise RuntimeError("候选包混入其他平台行为运行时")
        hook_events = set(dict(hooks.get("hooks") or {}))
        if hook_events != {"UserPromptSubmit", "Stop"}:
            raise RuntimeError(f"最小行为 Hook 事件不合规：{sorted(hook_events)}")

        scanned_text = []
        executable_text = []
        for name in sorted(names):
            if not name.endswith((".json", ".md", ".py", ".txt")):
                continue
            content = archive.read(name).decode("utf-8", errors="ignore")
            scanned_text.append(content)
            if name in {plugin_name, hooks_name, behavior_hook_name}:
                executable_text.append(content)
        joined_text = "\n".join(scanned_text)
        joined_executable_text = "\n".join(executable_text)
        forbidden_markers = [
            marker
            for marker in FORBIDDEN_TEXT_MARKERS
            if marker in joined_executable_text
        ]
        if forbidden_markers:
            raise RuntimeError(f"候选包含已停用流程标记：{forbidden_markers}")
        if re.search(r"jtk_[A-Za-z0-9_-]{16,}", joined_text):
            raise RuntimeError("公共候选包不得内置真实个人 Token")

    return {
        "status": "pass",
        "check": "all-skill-coverage",
        "skill_count": len(declared_skills),
        "hook_mode": plugin["hook_mode"],
        "mcp_configuration_mode": plugin["mcp_configuration_mode"],
        "forbidden_components": "absent",
        "real_host_acceptance": "post-release-required",
        "skill_entry_contract": "frontmatter-first-name-bound",
    }


def main() -> int:
    options = parse_args()
    suite_zip = options.suite_zip.expanduser().resolve()
    if not suite_zip.is_file():
        raise FileNotFoundError(suite_zip)
    result = (
        validate_server_release_contract(suite_zip)
        if options.check == "server-release-contract"
        else validate_all_skill_coverage(suite_zip)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

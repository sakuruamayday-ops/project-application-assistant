#!/usr/bin/env python3
"""Validate the signed WorkBuddy candidate without launching a real host.

Real macOS and Windows WorkBuddy installation, binding, restart, and tool-call
acceptance are deliberately post-release checks.  These pre-release gates only
inspect the exact signed candidate that will be published.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PORTAL_SCRIPTS = ROOT / "services" / "knowledge-portal" / "scripts"
sys.path.insert(0, str(PORTAL_SCRIPTS))

from publish_skill_release import validate_release_packages  # noqa: E402


OFFICIAL_FINGERPRINT = "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
EXPECTED_SKILL_COUNT = 49


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校验正式 WorkBuddy 候选包的签名、结构与技能覆盖"
    )
    parser.add_argument("--suite-zip", type=Path, required=True)
    parser.add_argument(
        "--check",
        choices=("signed-contract", "all-skill-coverage"),
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


def validate_signed_contract(suite_zip: Path) -> dict[str, object]:
    validation = validate_release_packages({"workbuddy": suite_zip}, "1.4.4")
    artifact = validation["artifacts"]["workbuddy"]
    integrity = artifact["integrity"]
    if integrity.get("status") != "verified":
        raise RuntimeError("WorkBuddy 候选包完整性未验证")
    if integrity.get("publisher_fingerprint") != OFFICIAL_FINGERPRINT:
        raise RuntimeError("WorkBuddy 候选包发布者指纹不匹配")
    if integrity.get("outer_fixed_installers") is not False:
        raise RuntimeError("WorkBuddy 候选包不得包含外层固定安装器")
    if integrity.get("mcp_configuration_mode") != "signed_external_plugin_mcp_file":
        raise RuntimeError("WorkBuddy MCP 必须由插件根签名 .mcp.json 配置")
    return {
        "status": "pass",
        "check": "signed-contract",
        "sha256": artifact["sha256"],
        "publisher_fingerprint": integrity["publisher_fingerprint"],
        "verified_files": integrity["verified_files"],
    }


def validate_all_skill_coverage(suite_zip: Path) -> dict[str, object]:
    with zipfile.ZipFile(suite_zip) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("WorkBuddy 候选包 ZIP 完整性失败")
        names = set(archive.namelist())
        plugin_name = unique_name(names, "/.codebuddy-plugin/plugin.json")
        plugin_root = str(PurePosixPath(plugin_name).parent.parent)
        suite_name = f"{plugin_root}/skills/suite-manifest.json"
        mcp_name = f"{plugin_root}/.mcp.json"
        required_runtime = {
            f"{plugin_root}/bin/run-node",
            f"{plugin_root}/bin/run-node.cmd",
            f"{plugin_root}/mcp/jiaotang-agent.mjs",
        }
        missing_runtime = sorted(required_runtime - names)
        if missing_runtime:
            raise RuntimeError(f"跨平台 MCP 运行时不完整：{missing_runtime}")

        plugin = load_json(archive, plugin_name)
        suite = load_json(archive, suite_name)
        mcp = load_json(archive, mcp_name)
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

        server = dict(mcp.get("mcpServers") or {}).get("jiaotang-kb")
        if not isinstance(server, dict):
            raise RuntimeError("插件根 .mcp.json 缺少 jiaotang-kb")
        if server.get("command") != "${CODEBUDDY_PLUGIN_ROOT}/bin/run-node":
            raise RuntimeError("MCP 启动器不是插件内跨平台 Node 启动器")
        if server.get("args") != [
            "${CODEBUDDY_PLUGIN_ROOT}/mcp/jiaotang-agent.mjs",
            "plugin-serve",
        ]:
            raise RuntimeError("MCP 启动参数与签名连接器契约不一致")

    return {
        "status": "pass",
        "check": "all-skill-coverage",
        "skill_count": len(declared_skills),
        "cross_platform_launchers": ["macos", "windows"],
        "real_host_acceptance": "post-release-required",
    }


def main() -> int:
    options = parse_args()
    suite_zip = options.suite_zip.expanduser().resolve()
    if not suite_zip.is_file():
        raise FileNotFoundError(suite_zip)
    result = (
        validate_signed_contract(suite_zip)
        if options.check == "signed-contract"
        else validate_all_skill_coverage(suite_zip)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

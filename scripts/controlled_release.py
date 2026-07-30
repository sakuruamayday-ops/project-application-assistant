#!/usr/bin/env python3
"""Fail-closed release command without self-hosted Runner dependencies."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], *, capture: bool = True) -> str:
    completed = subprocess.run(
        arguments,
        check=True,
        capture_output=capture,
        text=True,
    )
    return completed.stdout.strip() if capture else ""


def json_command(arguments: list[str]) -> object:
    return json.loads(run(arguments))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_version(value: str) -> tuple[str, str, str]:
    match = re.fullmatch(
        r"V?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?",
        value.strip(),
    )
    if not match:
        raise ValueError(
            "版本必须形如 1.3、1.3.1、1.3.1.1，或带V前缀"
        )
    major, minor = match.group(1), match.group(2)
    explicit_patch = match.group(3)
    patch = explicit_patch or "0"
    hotfix = match.group(4)
    if hotfix is not None:
        public = f"{major}.{minor}.{patch}.{hotfix}"
        semantic = public
    else:
        public = (
            f"{major}.{minor}.{patch}"
            if explicit_patch is not None
            else f"{major}.{minor}"
        )
        semantic = f"{major}.{minor}.{patch}"
    return public, semantic, f"V{public}"


def release_action(
    *,
    stage: bool,
    promote: bool,
    execute: bool,
    confirm_text: str,
) -> str:
    if execute:
        raise RuntimeError(
            "--execute一步直发已停用；请先使用--stage，收到独立确认后再使用--promote"
        )
    if promote:
        if confirm_text != "确认正式发布":
            raise RuntimeError(
                "缺少独立确认；--confirm-text必须逐字为“确认正式发布”"
            )
        return "promote"
    return "stage" if stage else "preflight"


def load_portal_publisher(root: Path):
    path = root / "services/knowledge-portal/scripts/publish_skill_release.py"
    specification = importlib.util.spec_from_file_location(
        "portal_release_publisher", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载网站发布校验器")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def load_release_companion_builder(root: Path):
    path = root / "scripts/release_companions.py"
    specification = importlib.util.spec_from_file_location(
        "release_companion_builder", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载发布伴随物生成器")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def validate_inputs(
    root: Path,
    version: str,
    packages: dict[str, Path],
    gate_report: Path,
    notes: Path,
    companions: dict[str, object],
) -> dict[str, object]:
    short, semantic, tag = normalize_version(version)
    manifest = json.loads(
        (root / "skills/suite-manifest.json").read_text(encoding="utf-8")
    )
    release = manifest.get("release", {})
    if release.get("tag") != tag or release.get("version") != semantic:
        raise RuntimeError("suite-manifest、发布标签和语义版本不一致")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    if f'version = "{semantic}"' not in pyproject:
        raise RuntimeError("pyproject.toml 组件版本未与产品语义版本对齐")
    readme = (root / "README.md").read_text(encoding="utf-8")
    if tag not in readme:
        raise RuntimeError("README 未声明当前发布版本")
    if not notes.is_file() or tag not in notes.read_text(encoding="utf-8"):
        raise RuntimeError("发布说明不存在或版本不一致")
    release_notes = notes.read_text(encoding="utf-8")
    for fact in [str(release.get("summary") or ""), *release.get("changes", [])]:
        if fact and fact not in release_notes:
            raise RuntimeError("发布说明未覆盖 suite-manifest 中的版本事实")
    gate = json.loads(gate_report.read_text(encoding="utf-8"))
    if (
        gate.get("status") != "pass"
        or gate.get("failed")
        or gate.get("passed") != gate.get("gate_count")
    ):
        raise RuntimeError("本地发布门禁报告未全部通过")
    publisher = load_portal_publisher(root)
    package_validation = publisher.validate_release_packages(packages, short)
    payload = companions.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("发布伴随物没有返回机器可读清单")
    if (
        payload.get("release_tag") != tag
        or payload.get("release_version") != semantic
        or payload.get("skill_count") != len(manifest.get("skills", []))
    ):
        raise RuntimeError("发布伴随物与 suite-manifest 不一致")
    return {
        "short_version": short,
        "semantic_version": semantic,
        "tag": tag,
        "skill_total": len(manifest.get("skills", [])),
        "targets": package_validation["targets"],
        "artifacts": package_validation["artifacts"],
        "gate_sha256": sha256(gate_report),
        "manual_sha256": payload["manual"]["sha256"],
        "companion_sha256": sha256(Path(str(companions["companion"]))),
    }


def validate_clean_default_branch(repository: str) -> str:
    if run(["git", "status", "--porcelain"]):
        raise RuntimeError("受控发布必须从无未提交改动的工作树执行")
    branch = run(["git", "branch", "--show-current"])
    repository_data = json_command(
        ["gh", "repo", "view", repository, "--json", "defaultBranchRef"]
    )
    default_branch = repository_data["defaultBranchRef"]["name"]
    if branch != default_branch:
        raise RuntimeError(
            f"受控发布必须从默认分支 {default_branch} 执行，当前为 {branch}"
        )
    run(["git", "fetch", "origin", default_branch])
    local = run(["git", "rev-parse", "HEAD"])
    remote = run(["git", "rev-parse", f"origin/{default_branch}"])
    if local != remote:
        raise RuntimeError("本地默认分支与 GitHub 默认分支不一致")
    return local


def prepare_ascii_assets(
    directory: Path,
    tag: str,
    packages: dict[str, Path],
    gate_report: Path,
    companions: dict[str, Path] | None = None,
) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    names = {
        "generic": f"jiaotang-skills-{tag}.zip",
        "workbuddy": f"jiaotang-skills-{tag}-WorkBuddy.zip",
    }
    targets: list[Path] = []
    for target_name, source in packages.items():
        target = directory / names[target_name]
        shutil.copy2(source, target)
        targets.append(target)
    gate_target = directory / f"jiaotang-skills-{tag}-release-gate.json"
    shutil.copy2(gate_report, gate_target)
    targets.append(gate_target)
    companion_names = {
        "manual": f"jiaotang-user-manual-{tag}.docx",
        "companion": f"jiaotang-release-companions-{tag}.json",
    }
    for companion_type, source in (companions or {}).items():
        if companion_type not in companion_names:
            raise RuntimeError(f"不支持的发布伴随物：{companion_type}")
        target = directory / companion_names[companion_type]
        shutil.copy2(source, target)
        targets.append(target)
    return targets


def ensure_prerelease(
    repository: str,
    tag: str,
    commit: str,
    notes: Path,
    assets: list[Path],
    *,
    create_if_missing: bool = True,
) -> str:
    existing = subprocess.run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "url,isPrerelease,targetCommitish,assets",
        ],
        capture_output=True,
        text=True,
    )
    if existing.returncode == 0:
        payload = json.loads(existing.stdout)
        if not payload.get("isPrerelease"):
            raise RuntimeError(f"GitHub {tag} 已是正式版，不能重新进入发布中")
        target = str(payload.get("targetCommitish") or "")
        if target != commit:
            raise RuntimeError("GitHub 预发布的目标提交与当前正式提交不一致")
        remote_assets = {
            str(item["name"]): str(item.get("digest") or "")
            for item in payload.get("assets", [])
        }
        expected_assets = {
            path.name: f"sha256:{sha256(path)}" for path in assets
        }
        if remote_assets != expected_assets:
            raise RuntimeError("GitHub 预发布资产与本地候选包不一致")
        return str(payload["url"])
    if not create_if_missing:
        raise RuntimeError(f"GitHub {tag} 尚未进入正式发布中，不能直接提升")
    return run(
        [
            "gh",
            "release",
            "create",
            tag,
            *(str(path) for path in assets),
            "--repo",
            repository,
            "--target",
            commit,
            "--title",
            f"企业全生命周期助手 {tag}",
            "--notes-file",
            str(notes),
            "--prerelease",
        ]
    )


def stage_portal(
    version: str,
    packages: dict[str, Path],
    notes: Path,
    commit: str,
    release_url: str,
) -> dict[str, object]:
    deploy_host = os.environ.get("JIAOTANG_DEPLOY_HOST")
    deploy_key = os.environ.get("JIAOTANG_DEPLOY_KEY")
    if not deploy_host or not deploy_key:
        raise RuntimeError("缺少 JIAOTANG_DEPLOY_HOST 或 JIAOTANG_DEPLOY_KEY")
    remote_stage = f"/tmp/jiaotang-release-{version}-{int(time.time())}"
    ssh = ["ssh", "-i", deploy_key, "-o", "IdentitiesOnly=yes", deploy_host]
    run([*ssh, f"install -d -m 0700 '{remote_stage}'"])
    run(
        [
            "scp",
            "-i",
            deploy_key,
            "-o",
            "IdentitiesOnly=yes",
            *(str(package) for package in packages.values()),
            str(notes),
            f"{deploy_host}:{remote_stage}/",
        ]
    )
    package_flags = " ".join(
        f"--workbuddy-package "
        f"{shlex.quote(f'{remote_stage}/{package.name}')}"
        if target != "generic"
        else f"--generic-package {shlex.quote(f'{remote_stage}/{package.name}')}"
        for target, package in packages.items()
    )
    remote_command = (
        "set -a; source /etc/jiaotang-kb.env; set +a; "
        "/opt/jiaotang-kb/.venv/bin/python "
        "/opt/jiaotang-kb/scripts/publish_skill_release.py "
        "--mode stage "
        f"--database \"$JIAOTANG_DATA_DIR/knowledge.db\" "
        f"--release-dir \"$JIAOTANG_SKILL_RELEASE_DIR\" "
        f"{package_flags} "
        f"--version {shlex.quote(version)} "
        f"--release-notes-file {shlex.quote(f'{remote_stage}/{notes.name}')} "
        f"--git-commit {shlex.quote(commit)} "
        f"--github-url {shlex.quote(release_url)}"
    )
    return json.loads(run([*ssh, remote_command]))


def promote_portal(version: str) -> dict[str, object]:
    deploy_host = os.environ.get("JIAOTANG_DEPLOY_HOST")
    deploy_key = os.environ.get("JIAOTANG_DEPLOY_KEY")
    if not deploy_host or not deploy_key:
        raise RuntimeError("缺少 JIAOTANG_DEPLOY_HOST 或 JIAOTANG_DEPLOY_KEY")
    ssh = ["ssh", "-i", deploy_key, "-o", "IdentitiesOnly=yes", deploy_host]
    remote_command = (
        "set -a; source /etc/jiaotang-kb.env; set +a; "
        "/opt/jiaotang-kb/.venv/bin/python "
        "/opt/jiaotang-kb/scripts/publish_skill_release.py "
        "--mode promote "
        f"--database \"$JIAOTANG_DATA_DIR/knowledge.db\" "
        f"--release-dir \"$JIAOTANG_SKILL_RELEASE_DIR\" "
        f"--version {shlex.quote(version)}"
    )
    return json.loads(run([*ssh, remote_command]))


def run_local_skill_deployment_gate(
    *,
    development_root: Path,
    generic_package: Path,
    install_root: Path,
    config_dir: Path,
    audit_dir: Path,
) -> dict[str, object]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "post_release_skill_gate.py"),
        "--development-root",
        str(development_root),
        "--release-archive",
        str(generic_package),
        "--install-root",
        str(install_root),
        "--config-dir",
        str(config_dir),
        "--audit-dir",
        str(audit_dir),
    ]
    process = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(process.stdout or process.stderr)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "本机Skills部署后门禁未返回有效JSON："
            + (process.stdout or process.stderr)[-2000:]
        ) from exc
    if process.returncode or payload.get("status") != "pass":
        raise RuntimeError(
            "本机Skills原子升级或部署后门禁失败："
            + str(payload.get("error") or payload)
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="两阶段受控发布：进入正式发布中 → 独立确认后正式发布"
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--generic-package", type=Path)
    parser.add_argument(
        "--workbuddy-package",
        type=Path,
        help="同时适用于macOS和Windows的WorkBuddy插件市场包",
    )
    parser.add_argument("--gate-report", type=Path, required=True)
    parser.add_argument("--release-notes", type=Path, required=True)
    parser.add_argument(
        "--repository",
        default="sakuruamayday-ops/project-application-assistant",
    )
    parser.add_argument(
        "--local-skills-target",
        type=Path,
        default=Path.home() / ".codex" / "skills",
        help="正式提升前必须完成原子升级和三方验签的本机Skills目录",
    )
    parser.add_argument(
        "--local-install-config-dir",
        type=Path,
        default=Path.home() / ".config" / "project-assistant",
        help="安装日志、备份和事务证据目录",
    )
    parser.add_argument(
        "--deployment-audit-dir",
        type=Path,
        default=Path.home()
        / ".config"
        / "project-assistant"
        / "deployment-audits",
        help="开发源、正式包、实际安装目录三方审计报告目录",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--stage",
        action="store_true",
        help="创建GitHub预发布并在网站登记为正式发布中，然后暂停",
    )
    action.add_argument(
        "--promote",
        action="store_true",
        help="将已处于正式发布中的版本提升为网站正式版和GitHub Latest",
    )
    action.add_argument(
        "--execute",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--confirm-text",
        default="",
        help="promote时必须逐字提供“确认正式发布”",
    )
    arguments = parser.parse_args()
    packages = {
        target: package.resolve()
        for target, package in (
            ("generic", arguments.generic_package),
            ("workbuddy", arguments.workbuddy_package),
        )
        if package is not None
    }
    if not packages:
        parser.error("至少提供一个发布包")
    if "generic" not in packages:
        parser.error(
            "受控发布必须提供--generic-package，"
            "用于正式提升前的本机原子升级、全量验签和三方哈希门禁"
        )
    action_name = release_action(
        stage=arguments.stage,
        promote=arguments.promote,
        execute=arguments.execute,
        confirm_text=arguments.confirm_text,
    )
    companion_workspace = tempfile.TemporaryDirectory(
        prefix="jiaotang-release-companions-"
    )
    companion_builder = load_release_companion_builder(ROOT)
    companion_result = companion_builder.generate(
        ROOT,
        Path(companion_workspace.name),
        apply_brand=True,
        render=True,
    )
    companion_files = {
        "manual": Path(str(companion_result["manual"])),
        "companion": Path(str(companion_result["companion"])),
    }
    validation = validate_inputs(
        ROOT,
        arguments.version,
        packages,
        arguments.gate_report.resolve(),
        arguments.release_notes.resolve(),
        companion_result,
    )
    commit = validate_clean_default_branch(arguments.repository)
    preflight = {
        "status": "preflight-pass",
        "release": validation,
        "commit": commit,
    }
    if action_name == "preflight":
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return

    if action_name == "promote":
        with tempfile.TemporaryDirectory(
            prefix="jiaotang-controlled-release-verify-"
        ) as directory:
            assets = prepare_ascii_assets(
                Path(directory) / "assets",
                validation["tag"],
                packages,
                arguments.gate_report.resolve(),
                companion_files,
            )
            release_url = ensure_prerelease(
                arguments.repository,
                validation["tag"],
                commit,
                arguments.release_notes.resolve(),
                assets,
                create_if_missing=False,
            )
        local_deployment = run_local_skill_deployment_gate(
            development_root=ROOT / "skills",
            generic_package=packages["generic"],
            install_root=arguments.local_skills_target.expanduser().resolve(),
            config_dir=arguments.local_install_config_dir.expanduser().resolve(),
            audit_dir=arguments.deployment_audit_dir.expanduser().resolve(),
        )
        portal_result = promote_portal(validation["short_version"])
        run(
            [
                "gh",
                "release",
                "edit",
                validation["tag"],
                "--repo",
                arguments.repository,
                "--prerelease=false",
                "--latest",
            ]
        )
        delivery = companion_builder.deliver(
            ROOT,
            Path(companion_workspace.name),
        )
        print(
            json.dumps(
                {
                    **preflight,
                    "status": "published",
                    "release_url": release_url,
                    "local_skill_deployment": local_deployment,
                    "portal": portal_result,
                    "delivery": delivery,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    with tempfile.TemporaryDirectory(
        prefix="jiaotang-controlled-release-stage-"
    ) as directory:
        assets = prepare_ascii_assets(
            Path(directory) / "assets",
            validation["tag"],
            packages,
            arguments.gate_report.resolve(),
            companion_files,
        )
        release_url = ensure_prerelease(
            arguments.repository,
            validation["tag"],
            commit,
            arguments.release_notes.resolve(),
            assets,
        )
        portal_result = stage_portal(
            validation["short_version"],
            packages,
            arguments.release_notes.resolve(),
            commit,
            release_url,
        )
        print(
            json.dumps(
                {
                    **preflight,
                    "status": "releasing",
                    "release_url": release_url,
                    "portal": portal_result,
                    "next_action": "等待主人明确说“确认正式发布”",
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(
            json.dumps(
                {"status": "blocked", "error": str(error)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

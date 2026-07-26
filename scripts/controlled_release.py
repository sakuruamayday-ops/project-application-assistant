#!/usr/bin/env python3
"""Single fail-closed release command for GitHub, real hosts, and the portal."""
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
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = "workbuddy-host-matrix.yml"
REQUIRED_HOST_LABELS = {
    "macos": {"self-hosted", "workbuddy", "macos"},
    "windows": {"self-hosted", "workbuddy", "windows"},
}


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
    match = re.fullmatch(r"V?(\d+)\.(\d+)(?:\.(\d+))?", value.strip())
    if not match:
        raise ValueError("版本必须形如 1.3、1.3.0 或 V1.3")
    major, minor, patch = match.group(1), match.group(2), match.group(3) or "0"
    if patch != "0":
        raise ValueError("产品发布只接受补丁位为 0 的版本")
    short = f"{major}.{minor}"
    return short, f"{short}.0", f"V{short}"


def load_portal_publisher(root: Path):
    path = root / "services/knowledge-portal/scripts/publish_skill_release.py"
    specification = importlib.util.spec_from_file_location("portal_release_publisher", path)
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载网站发布校验器")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def validate_inputs(
    root: Path,
    version: str,
    generic: Path,
    workbuddy: Path,
    gate_report: Path,
    notes: Path,
) -> dict[str, object]:
    short, semantic, tag = normalize_version(version)
    manifest = json.loads((root / "skills/suite-manifest.json").read_text(encoding="utf-8"))
    release = manifest.get("release", {})
    if release.get("tag") != tag or release.get("version") != semantic:
        raise RuntimeError("suite-manifest、发布标签和语义版本不一致")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    if f'version = "{semantic}"' not in pyproject:
        raise RuntimeError("pyproject.toml 组件版本未与产品语义版本对齐")
    readme = (root / "README.md").read_text(encoding="utf-8")
    if f"V{short}" not in readme:
        raise RuntimeError("README 未声明当前发布版本")
    if not notes.is_file() or tag not in notes.read_text(encoding="utf-8"):
        raise RuntimeError("发布说明不存在或版本不一致")
    gate = json.loads(gate_report.read_text(encoding="utf-8"))
    if (
        gate.get("status") != "pass"
        or gate.get("failed")
        or gate.get("passed") != gate.get("gate_count")
    ):
        raise RuntimeError("本地发布门禁报告未全部通过")
    package_validation = load_portal_publisher(root).validate_packages(
        generic, workbuddy, short
    )
    return {
        "short_version": short,
        "semantic_version": semantic,
        "tag": tag,
        "skill_total": len(manifest.get("skills", [])),
        "generic_sha256": package_validation["generic_sha256"],
        "workbuddy_sha256": package_validation["workbuddy_sha256"],
        "gate_sha256": sha256(gate_report),
    }


def validate_clean_default_branch(repository: str) -> str:
    status = run(["git", "status", "--porcelain"])
    if status:
        raise RuntimeError("受控发布必须从无未提交改动的工作树执行")
    branch = run(["git", "branch", "--show-current"])
    repository_data = json_command(["gh", "repo", "view", repository, "--json", "defaultBranchRef"])
    default_branch = repository_data["defaultBranchRef"]["name"]
    if branch != default_branch:
        raise RuntimeError(f"受控发布必须从默认分支 {default_branch} 执行，当前为 {branch}")
    run(["git", "fetch", "origin", default_branch])
    local = run(["git", "rev-parse", "HEAD"])
    remote = run(["git", "rev-parse", f"origin/{default_branch}"])
    if local != remote:
        raise RuntimeError("本地默认分支与 GitHub 默认分支不一致")
    return local


def validate_runners(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    runners = payload.get("runners")
    if not isinstance(runners, list):
        raise RuntimeError("GitHub Runner 返回结构无效")
    selected: dict[str, dict[str, object]] = {}
    for host, required in REQUIRED_HOST_LABELS.items():
        matches = []
        for runner in runners:
            labels = {str(item.get("name")) for item in runner.get("labels", [])}
            if required <= labels:
                matches.append(runner)
        online = [
            runner
            for runner in matches
            if runner.get("status") == "online" and runner.get("busy") is False
        ]
        if len(online) != 1:
            raise RuntimeError(
                f"{host} 需要且仅允许一个空闲在线 Runner，当前匹配 {len(matches)}、可用 {len(online)}"
            )
        selected[host] = online[0]
    return selected


def github_runners(repository: str) -> dict[str, dict[str, object]]:
    payload = json_command(["gh", "api", f"repos/{repository}/actions/runners"])
    return validate_runners(payload)


def prepare_ascii_assets(
    directory: Path,
    tag: str,
    generic: Path,
    workbuddy: Path,
    gate_report: Path,
) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    targets = [
        directory / f"jiaotang-skills-{tag}.zip",
        directory / f"jiaotang-skills-{tag}-WorkBuddy.zip",
        directory / f"jiaotang-skills-{tag}-release-gate.json",
    ]
    for source, target in zip((generic, workbuddy, gate_report), targets, strict=True):
        shutil.copy2(source, target)
    return targets


def create_prerelease(
    repository: str,
    tag: str,
    commit: str,
    notes: Path,
    assets: list[Path],
) -> str:
    existing = run(
        ["gh", "release", "view", tag, "--repo", repository, "--json", "url"],
    ) if subprocess.run(
        ["gh", "release", "view", tag, "--repo", repository],
        capture_output=True,
        text=True,
    ).returncode == 0 else ""
    if existing:
        raise RuntimeError(f"GitHub 已存在 {tag}，受控命令拒绝覆盖")
    output = run(
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
    return output


def find_release_run(repository: str, commit: str, started_at: datetime) -> int:
    for _ in range(30):
        runs = json_command(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                WORKFLOW,
                "--event",
                "release",
                "--limit",
                "20",
                "--json",
                "databaseId,headSha,createdAt",
            ]
        )
        candidates = [
            item
            for item in runs
            if item.get("headSha") == commit
            and datetime.fromisoformat(str(item["createdAt"]).replace("Z", "+00:00"))
            >= started_at
        ]
        if candidates:
            return int(candidates[0]["databaseId"])
        time.sleep(5)
    raise RuntimeError("未找到由 GitHub 预发布触发的双宿主门禁")


def wait_for_host_gate(repository: str, run_id: int, timeout_seconds: int) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = json_command(
            [
                "gh",
                "run",
                "view",
                str(run_id),
                "--repo",
                repository,
                "--json",
                "status,conclusion,url,jobs",
            ]
        )
        if payload.get("status") == "completed":
            if payload.get("conclusion") != "success":
                raise RuntimeError(f"双宿主门禁失败：{payload.get('url')}")
            jobs = payload.get("jobs", [])
            for host in REQUIRED_HOST_LABELS:
                matching = [
                    job
                    for job in jobs
                    if host in str(job.get("name", "")).lower()
                    and job.get("conclusion") == "success"
                ]
                if len(matching) != 1:
                    raise RuntimeError(f"门禁结果缺少成功的 {host} 实机任务")
            return payload
        time.sleep(15)
    raise RuntimeError("双宿主门禁等待超时；GitHub 预发布保持未提升状态")


def host_evidence(gate: dict[str, object], tag: str, run_id: int) -> dict[str, object]:
    hosts = {}
    for host in REQUIRED_HOST_LABELS:
        job = next(job for job in gate["jobs"] if host in job["name"].lower())
        hosts[host] = {
            "status": "pass",
            "job_id": job["databaseId"],
            "job_url": job["url"],
            "completed_at": job["completedAt"],
        }
    return {
        "schema": "jiaotang-workbuddy-host-matrix/v1",
        "status": "pass",
        "release_tag": tag,
        "run_id": run_id,
        "run_url": gate["url"],
        "hosts": hosts,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def publish_portal(
    version: str,
    generic: Path,
    workbuddy: Path,
    notes: Path,
    evidence_path: Path,
) -> None:
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
            str(generic),
            str(workbuddy),
            str(notes),
            str(evidence_path),
            f"{deploy_host}:{remote_stage}/",
        ]
    )
    remote_command = (
        "set -a; source /etc/jiaotang-kb.env; set +a; "
        "/opt/jiaotang-kb/.venv/bin/python "
        "/opt/jiaotang-kb/scripts/publish_skill_release.py "
        f"--database \"$JIAOTANG_DATA_DIR/knowledge.db\" "
        f"--release-dir \"$JIAOTANG_SKILL_RELEASE_DIR\" "
        f"--generic-package {shlex.quote(f'{remote_stage}/{generic.name}')} "
        f"--workbuddy-package {shlex.quote(f'{remote_stage}/{workbuddy.name}')} "
        f"--version {shlex.quote(version)} "
        f"--release-notes-file {shlex.quote(f'{remote_stage}/{notes.name}')} "
        f"--host-evidence {shlex.quote(f'{remote_stage}/{evidence_path.name}')}"
    )
    run([*ssh, remote_command])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="受控发布：版本一致性 → Runner 在线 → GitHub 预发布 → 双宿主 → 网站 → 正式版"
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--generic-package", type=Path, required=True)
    parser.add_argument("--workbuddy-package", type=Path, required=True)
    parser.add_argument("--gate-report", type=Path, required=True)
    parser.add_argument("--release-notes", type=Path, required=True)
    parser.add_argument(
        "--repository",
        default="sakuruamayday-ops/project-application-assistant",
    )
    parser.add_argument("--host-timeout", type=int, default=3600)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="未提供时只执行只读预检，不创建预发布或修改网站",
    )
    arguments = parser.parse_args()
    validation = validate_inputs(
        ROOT,
        arguments.version,
        arguments.generic_package.resolve(),
        arguments.workbuddy_package.resolve(),
        arguments.gate_report.resolve(),
        arguments.release_notes.resolve(),
    )
    commit = validate_clean_default_branch(arguments.repository)
    runners = github_runners(arguments.repository)
    preflight = {
        "status": "preflight-pass",
        "release": validation,
        "commit": commit,
        "runners": {host: runner["name"] for host, runner in runners.items()},
    }
    if not arguments.execute:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return

    with tempfile.TemporaryDirectory(prefix="jiaotang-controlled-release-") as directory:
        temporary = Path(directory)
        assets = prepare_ascii_assets(
            temporary / "assets",
            validation["tag"],
            arguments.generic_package.resolve(),
            arguments.workbuddy_package.resolve(),
            arguments.gate_report.resolve(),
        )
        started_at = datetime.now(timezone.utc)
        release_url = create_prerelease(
            arguments.repository,
            validation["tag"],
            commit,
            arguments.release_notes.resolve(),
            assets,
        )
        run_id = find_release_run(arguments.repository, commit, started_at)
        gate = wait_for_host_gate(arguments.repository, run_id, arguments.host_timeout)
        evidence = host_evidence(gate, validation["tag"], run_id)
        evidence_path = temporary / f"workbuddy-host-matrix-{validation['tag']}.json"
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        publish_portal(
            validation["short_version"],
            arguments.generic_package.resolve(),
            arguments.workbuddy_package.resolve(),
            arguments.release_notes.resolve(),
            evidence_path,
        )
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
        print(
            json.dumps(
                {
                    **preflight,
                    "status": "published",
                    "release_url": release_url,
                    "host_gate": evidence,
                    "portal": "published",
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
                {
                    "status": "blocked",
                    "reason": str(error),
                    "formal_release_promoted": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None

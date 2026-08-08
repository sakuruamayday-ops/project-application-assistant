#!/usr/bin/env python3
"""Run one resumable, server-owned application deployment transaction."""

from __future__ import annotations

import argparse
import fcntl
import grp
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

try:
    from scripts.release_retention import prune_release_generations
except ImportError:  # direct script execution
    from release_retention import prune_release_generations


REQUEST_SCHEMA = "jiaotang-application-deployment-request/v1"
STATE_SCHEMA = "jiaotang-application-deployment-state/v1"
DEPLOYMENT_ID_PATTERN = re.compile(
    r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}-[0-9a-f]{8}"
)
BUILD_KEYS = (
    "commit",
    "deployment_id",
    "built_at",
    "dependency_lock_sha256",
    "dependency_build_lock_sha256",
    "wheelhouse_install_lock_sha256",
    "wheelhouse_manifest_sha256",
    "wheelhouse_content_identity_sha256",
    "dependency_identity_sha256",
    "dependency_release_record_sha256",
    "private_overlay_identity_sha256",
)
ENV_BUILD_KEYS = {
    "commit": "JIAOTANG_BUILD_COMMIT",
    "deployment_id": "JIAOTANG_DEPLOYMENT_ID",
    "built_at": "JIAOTANG_BUILD_CREATED_AT",
    "dependency_lock_sha256": "JIAOTANG_DEPENDENCY_LOCK_SHA256",
    "dependency_build_lock_sha256": (
        "JIAOTANG_DEPENDENCY_BUILD_LOCK_SHA256"
    ),
    "wheelhouse_install_lock_sha256": (
        "JIAOTANG_WHEELHOUSE_INSTALL_LOCK_SHA256"
    ),
    "wheelhouse_manifest_sha256": "JIAOTANG_WHEELHOUSE_MANIFEST_SHA256",
    "wheelhouse_content_identity_sha256": (
        "JIAOTANG_WHEELHOUSE_CONTENT_IDENTITY_SHA256"
    ),
    "dependency_identity_sha256": "JIAOTANG_DEPENDENCY_IDENTITY_SHA256",
    "dependency_release_record_sha256": (
        "JIAOTANG_DEPENDENCY_RELEASE_RECORD_SHA256"
    ),
    "private_overlay_identity_sha256": (
        "JIAOTANG_PRIVATE_OVERLAY_IDENTITY_SHA256"
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_symlink(target: Path, link: Path) -> None:
    temporary = link.with_name(
        f".{link.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    temporary.symlink_to(target)
    os.replace(temporary, link)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON顶层必须是对象：{path}")
    return payload


def run_checked(command: list[str], *, timeout: int = 180) -> None:
    subprocess.run(command, check=True, timeout=timeout)


def fetch_json(url: str, *, timeout: int = 20) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "JiaotangDeployGate/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise RuntimeError(f"端点未返回JSON对象：{url}")
    return payload


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def rewrite_build_environment(path: Path, previous: dict[str, Any]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    replacements = {
        ENV_BUILD_KEYS[key]: previous.get(key)
        for key in ENV_BUILD_KEYS
    }
    retained = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key not in replacements:
            retained.append(line)
    for key, value in replacements.items():
        if value is not None:
            retained.append(f"{key}={value}")
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    temporary.write_text("\n".join(retained) + "\n", encoding="utf-8")
    os.chmod(temporary, path.stat().st_mode & 0o777)
    os.chown(temporary, path.stat().st_uid, path.stat().st_gid)
    os.replace(temporary, path)


def install_candidate_environment(
    request: dict[str, Any],
    *,
    state_dir: Path = Path("/var/lib/jiaotang-kb/deployments"),
    ops_target: Path = Path("/etc/jiaotang-kb-ops.env"),
    app_target: Path = Path("/etc/jiaotang-kb-app.env"),
    owner_id: int = 0,
    ops_group_id: int = 0,
    app_group_id: int | None = None,
) -> None:
    state_dir = state_dir.resolve(strict=True)
    if app_group_id is None:
        app_group_id = grp.getgrnam("jiaotang").gr_gid
    deployment_id = str(request["deployment_id"])
    candidates = (
        (
            Path(str(request["candidate_ops_env"])),
            state_dir / f"{deployment_id}.candidate-ops.env",
            ops_target,
            0o600,
            ops_group_id,
        ),
        (
            Path(str(request["candidate_app_env"])),
            state_dir / f"{deployment_id}.candidate-app.env",
            app_target,
            0o640,
            app_group_id,
        ),
    )
    for source, expected_source, target, mode, group_id in candidates:
        if source.is_symlink() or source.resolve(strict=True) != expected_source:
            raise RuntimeError(f"候选环境文件路径非法：{source}")
        if source.stat().st_size > 1024 * 1024:
            raise RuntimeError(f"候选环境文件异常过大：{source}")
        temporary = target.with_name(
            f".{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        temporary.write_bytes(source.read_bytes())
        os.chmod(temporary, mode)
        os.chown(temporary, owner_id, group_id)
        os.replace(temporary, target)


def validate_request(request: dict[str, Any]) -> None:
    required = {
        "schema",
        "deployment_id",
        "release_mode",
        "runtime_root",
        "release_root",
        "release_dir",
        "previous_release_dir",
        "expected_build",
        "previous_build",
        "candidate_ops_env",
        "candidate_app_env",
        "created_at",
    }
    if set(request) != required:
        raise RuntimeError("应用部署请求字段集不符合固定协议")
    if request["schema"] != REQUEST_SCHEMA:
        raise RuntimeError("应用部署请求schema不受支持")
    deployment_id = str(request["deployment_id"])
    if DEPLOYMENT_ID_PATTERN.fullmatch(deployment_id) is None:
        raise RuntimeError("应用部署编号格式非法")
    if request["release_mode"] not in {"code", "index"}:
        raise RuntimeError("应用部署模式只能是code或index")
    expected = request["expected_build"]
    previous = request["previous_build"]
    if not isinstance(expected, dict) or set(expected) != set(BUILD_KEYS):
        raise RuntimeError("预期构建身份字段集不符合固定协议")
    if not isinstance(previous, dict) or set(previous) != set(BUILD_KEYS):
        raise RuntimeError("上一构建身份字段集不符合固定协议")
    if expected["deployment_id"] != deployment_id:
        raise RuntimeError("部署编号与预期构建身份不一致")


def resolve_release_paths(request: dict[str, Any]) -> tuple[Path, Path, Path]:
    runtime = Path(str(request["runtime_root"])).resolve(strict=True)
    release_root = Path(str(request["release_root"])).resolve(strict=True)
    release = Path(str(request["release_dir"])).resolve(strict=True)
    if release.parent != release_root:
        raise RuntimeError("新应用release不在固定槽位根目录下")
    if release.name != request["deployment_id"]:
        raise RuntimeError("新应用release名称与部署编号不一致")
    for relative in (
        "app/main.py",
        ".venv/bin/python",
        "scripts/migrate_first_public_release.py",
        "scripts/verify_authenticated_portal.py",
    ):
        if not (release / relative).is_file():
            raise RuntimeError(f"新应用release缺少入口：{relative}")
    previous = Path(str(request["previous_release_dir"])).resolve(strict=True)
    if previous == release:
        raise RuntimeError("新应用release不能与上一release相同")
    return runtime, release, previous


def update_state(
    state_path: Path,
    request: dict[str, Any],
    phase: str,
    **extra: Any,
) -> dict[str, Any]:
    existing = load_json(state_path) if state_path.is_file() else {}
    started_at = existing.get("started_at") or utc_now()
    history = list(existing.get("history") or [])
    if not history or history[-1].get("phase") != phase:
        history.append({"phase": phase, "at": utc_now()})
    payload = {
        "schema": STATE_SCHEMA,
        "deployment_id": request["deployment_id"],
        "release_mode": request["release_mode"],
        "commit": request["expected_build"]["commit"],
        "release_dir": request["release_dir"],
        "previous_release_dir": request["previous_release_dir"],
        "phase": phase,
        "terminal": phase in {"completed", "failed", "rolled_back"},
        "success": phase == "completed",
        "started_at": started_at,
        "updated_at": utc_now(),
        "attempt": int(existing.get("attempt") or 1),
        "error": None,
        "rollback": existing.get("rollback") or "not-required",
        "history": history,
    }
    payload.update(extra)
    atomic_json(state_path, payload)
    print(
        "[application-deployment] "
        f"deployment_id={request['deployment_id']} phase={phase}",
        flush=True,
    )
    return payload


def verify_build(expected: dict[str, Any]) -> None:
    payload = fetch_json("http://127.0.0.1:8100/build")
    for key in BUILD_KEYS:
        if payload.get(key) != expected[key]:
            raise RuntimeError(f"生产/build {key}与部署请求不一致")


def verify_public_routes(public_host: str) -> None:
    resolve = f"{public_host}:443:127.0.0.1"
    expected_status = {
        "/login": "200",
        "/setup": "303",
        "/v1/me": "401",
        "/mcp/": "401",
    }
    for route, expected in expected_status.items():
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                "--resolve",
                resolve,
                f"https://{public_host}{route}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.stdout != expected:
            raise RuntimeError(
                f"生产固定路由异常：{route} "
                f"预期{expected}实际{result.stdout}"
            )
    run_checked(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--resolve",
            resolve,
            f"https://{public_host}/demo",
        ],
        timeout=20,
    )


def restore_previous_build(previous: dict[str, Any]) -> None:
    for path in (Path("/etc/jiaotang-kb-ops.env"), Path("/etc/jiaotang-kb-app.env")):
        if path.is_file():
            rewrite_build_environment(path, previous)


def rollback(
    request: dict[str, Any],
    runtime: Path,
    release: Path,
    previous: Path,
) -> str:
    current = runtime / "current"
    current_target = current.resolve(strict=True) if current.is_symlink() else None
    if current_target == release:
        atomic_symlink(previous, current)
    restore_previous_build(request["previous_build"])
    if request["release_mode"] == "index":
        run_checked(
            [
                str(release / ".venv/bin/python"),
                str(release / "scripts/refresh_index_from_oss.py"),
                "--rollback",
            ],
            timeout=300,
        )
    run_checked(["systemctl", "daemon-reload"])
    run_checked(["systemctl", "restart", "jiaotang-kb.service"], timeout=90)
    run_checked(["systemctl", "enable", "--now", "jiaotang-kb-health.timer"])
    run_checked(["systemctl", "enable", "--now", "jiaotang-kb-backup.timer"])
    run_checked(["systemctl", "enable", "--now", "jiaotang-kb-oss-verify.timer"])
    fetch_json("http://127.0.0.1:8100/readyz")
    return "completed"


def execute(request_path: Path, state_path: Path) -> int:
    request = load_json(request_path)
    validate_request(request)
    runtime, release, previous = resolve_release_paths(request)

    if state_path.is_file():
        state = load_json(state_path)
        if state.get("deployment_id") != request["deployment_id"]:
            raise RuntimeError("部署状态与请求编号不一致")
        if state.get("phase") == "completed":
            if (runtime / "current").resolve(strict=True) != release:
                raise RuntimeError("已完成回执与当前生产指针不一致")
            verify_build(request["expected_build"])
            return 0
        if state.get("phase") in {"failed", "rolled_back"}:
            raise RuntimeError("该部署事务已终止，拒绝重放")
        state["attempt"] = int(state.get("attempt") or 1) + 1
        atomic_json(state_path, state)

    update_state(state_path, request, "accepted")
    try:
        current = runtime / "current"
        current_target = current.resolve(strict=True)
        if current_target not in {previous, release}:
            raise RuntimeError(
                "生产current既不是请求记录的上一release，也不是新release"
            )
        run_checked(["systemctl", "stop", "jiaotang-kb-health.timer"])
        run_checked(["systemctl", "stop", "jiaotang-kb-backup.timer"])
        install_candidate_environment(request)
        if current_target == previous:
            atomic_symlink(previous, runtime / "previous")
            atomic_symlink(release, current)
        update_state(state_path, request, "switched")

        run_checked(["systemctl", "daemon-reload"])
        run_checked(["systemctl", "restart", "jiaotang-kb.service"], timeout=90)
        fetch_json("http://127.0.0.1:8100/readyz")
        verify_build(request["expected_build"])
        update_state(state_path, request, "service_ready")

        app_env = parse_env(Path("/etc/jiaotang-kb-app.env"))
        run_checked(
            [
                str(release / ".venv/bin/python"),
                str(release / "scripts/migrate_first_public_release.py"),
                "--database",
                str(Path(app_env["JIAOTANG_DATA_DIR"]) / "knowledge.db"),
                "--release-dir",
                app_env["JIAOTANG_SKILL_RELEASE_DIR"],
            ]
        )
        update_state(state_path, request, "migration_complete")

        run_checked(
            [
                str(release / ".venv/bin/python"),
                str(release / "scripts/verify_authenticated_portal.py"),
                "--base-url",
                "http://127.0.0.1:8100",
            ]
        )
        update_state(state_path, request, "portal_verified")

        verify_public_routes(app_env["JIAOTANG_PUBLIC_HOST"])
        verify_build(request["expected_build"])
        update_state(state_path, request, "routes_verified")

        for unit in (
            "jiaotang-kb-health.timer",
            "jiaotang-kb-backup.timer",
            "jiaotang-kb-oss-verify.timer",
        ):
            run_checked(["systemctl", "enable", "--now", unit])
        run_checked(["systemctl", "start", "jiaotang-kb-health.service"])
        retention_cleanup: dict[str, Any]
        try:
            retention_cleanup = prune_release_generations(
                Path(str(request["release_root"])),
                runtime,
                apply=True,
            )
        except Exception as cleanup_error:
            # Production is already healthy.  A retention warning must not
            # misreport a successful deployment as failed or trigger rollback.
            retention_cleanup = {
                "schema": "jiaotang-release-retention/v1",
                "applied": False,
                "error": str(cleanup_error)[:2000],
            }
        update_state(
            state_path,
            request,
            "completed",
            completed_at=utc_now(),
            retention_cleanup=retention_cleanup,
        )
        return 0
    except Exception as error:
        rollback_status = "failed"
        rollback_error: str | None = None
        try:
            rollback_status = rollback(request, runtime, release, previous)
        except Exception as rollback_failure:
            rollback_error = str(rollback_failure)[:2000]
        phase = "rolled_back" if rollback_status == "completed" else "failed"
        update_state(
            state_path,
            request,
            phase,
            completed_at=utc_now(),
            error=str(error)[:2000],
            rollback=rollback_status,
            rollback_error=rollback_error,
        )
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行可恢复的应用部署事务")
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("/var/lib/jiaotang-kb/deployments"),
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path("/run/lock/jiaotang-kb-application-deploy.lock"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if DEPLOYMENT_ID_PATTERN.fullmatch(args.deployment_id) is None:
        raise SystemExit(64)
    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("已有应用部署事务在运行", file=sys.stderr)
            return 75
        request_path = args.state_dir / f"{args.deployment_id}.request.json"
        state_path = args.state_dir / f"{args.deployment_id}.state.json"
        return execute(request_path, state_path)


if __name__ == "__main__":
    raise SystemExit(main())

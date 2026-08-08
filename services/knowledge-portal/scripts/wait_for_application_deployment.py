#!/usr/bin/env python3
"""Poll a server-owned application deployment receipt across SSH reconnects."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


STATE_SCHEMA = "jiaotang-application-deployment-state/v1"
TERMINAL_PHASES = {"completed", "failed", "rolled_back"}
DEPLOYMENT_ID_PATTERN = re.compile(
    r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}-[0-9a-f]{8}"
)


def fetch_remote_state(host: str, key: Path, deployment_id: str) -> dict[str, Any]:
    if DEPLOYMENT_ID_PATTERN.fullmatch(deployment_id) is None:
        raise RuntimeError("部署编号格式非法")
    path = f"/var/lib/jiaotang-kb/deployments/{deployment_id}.state.json"
    result = subprocess.run(
        [
            "ssh",
            "-i",
            str(key),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ConnectionAttempts=3",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=4",
            host,
            "cat",
            "--",
            path,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=70,
    )
    if result.returncode != 0:
        unit = f"jiaotang-kb-application-deploy@{deployment_id}.service"
        unit_result = subprocess.run(
            [
                "ssh",
                "-i",
                str(key),
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=15",
                "-o",
                "ConnectionAttempts=3",
                host,
                "systemctl",
                "show",
                unit,
                "--property=ActiveState",
                "--property=Result",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=70,
        )
        values = dict(
            line.split("=", 1)
            for line in unit_result.stdout.splitlines()
            if "=" in line
        )
        if unit_result.returncode == 0 and (
            values.get("ActiveState") == "failed" or values.get("Result") == "exit-code"
        ):
            return {
                "schema": STATE_SCHEMA,
                "deployment_id": deployment_id,
                "phase": "failed",
                "success": False,
                "error": "systemd deployment unit failed before writing state receipt",
                "systemd": values,
            }
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("部署回执顶层必须是JSON对象")
    return payload


def wait_for_terminal_state(
    fetcher: Callable[[], dict[str, Any]],
    *,
    deployment_id: str,
    timeout_seconds: int,
    poll_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], int]:
    started = clock()
    transport_failures = 0
    last_phase: str | None = None
    while clock() - started < timeout_seconds:
        try:
            state = fetcher()
            if state.get("schema") != STATE_SCHEMA:
                raise RuntimeError("服务器部署回执schema不受支持")
            if state.get("deployment_id") != deployment_id:
                raise RuntimeError("服务器部署回执编号不一致")
            phase = str(state.get("phase") or "unknown")
            if phase != last_phase:
                print(
                    "[application-deployment] "
                    f"elapsed_seconds={int(clock() - started)} phase={phase} "
                    f"transport_retries={transport_failures}",
                    flush=True,
                )
                last_phase = phase
            if phase in TERMINAL_PHASES:
                return state, transport_failures
        except (
            OSError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
        ) as error:
            transport_failures += 1
            print(
                "[application-deployment] "
                f"elapsed_seconds={int(clock() - started)} "
                f"transport_retry={transport_failures} error={type(error).__name__}",
                flush=True,
            )
        sleeper(poll_seconds)
    raise TimeoutError(
        f"等待服务器部署回执超时：{deployment_id}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="断线重连并续验应用部署回执")
    parser.add_argument("--host", required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--poll-seconds", type=float, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state, transport_failures = wait_for_terminal_state(
        lambda: fetch_remote_state(args.host, args.key, args.deployment_id),
        deployment_id=args.deployment_id,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(state, ensure_ascii=False, sort_keys=True))
    if state["phase"] == "completed" and state.get("success") is True:
        if transport_failures:
            print(
                f"控制端断线{transport_failures}次，"
                "已依据服务器回执恢复为成功。"
            )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stream stdin to a command with progress and bounded no-progress time."""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from typing import BinaryIO


def terminate(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def write_all(destination: BinaryIO, payload: bytes) -> int:
    """Write a complete payload even when an unbuffered pipe writes partially."""

    view = memoryview(payload)
    written_total = 0
    while written_total < len(view):
        written = destination.write(view[written_total:])
        if written is None or written <= 0:
            raise BrokenPipeError("目标管道未接受剩余数据")
        written_total += written
    return written_total


def stream(
    source: BinaryIO,
    command: list[str],
    *,
    label: str,
    stall_timeout_seconds: float,
    completion_timeout_seconds: float,
    report_interval_seconds: float,
) -> int:
    started = time.monotonic()
    state: dict[str, object] = {
        "bytes": 0,
        "last_progress": started,
        "input_complete": False,
        "input_completed_at": None,
        "error": None,
    }
    process = subprocess.Popen(command, stdin=subprocess.PIPE, bufsize=0)

    def pump() -> None:
        assert process.stdin is not None
        try:
            while chunk := source.read(256 * 1024):
                written = write_all(process.stdin, chunk)
                state["bytes"] = int(state["bytes"]) + written
                state["last_progress"] = time.monotonic()
            process.stdin.close()
            state["input_complete"] = True
            state["input_completed_at"] = time.monotonic()
        except (BrokenPipeError, OSError) as exc:
            state["error"] = exc

    worker = threading.Thread(target=pump, daemon=True)
    worker.start()
    next_report = started
    timed_out = False
    timeout_reason = ""
    while process.poll() is None:
        now = time.monotonic()
        if now >= next_report:
            elapsed = max(now - started, 0.001)
            transferred = int(state["bytes"])
            print(
                f"[{label}] elapsed_seconds={elapsed:.1f} "
                f"transferred_bytes={transferred} "
                f"average_mib_s={transferred / elapsed / 1024 / 1024:.2f}",
                file=sys.stderr,
                flush=True,
            )
            next_report = now + report_interval_seconds
        if not state["input_complete"]:
            idle = now - float(state["last_progress"])
            if idle > stall_timeout_seconds:
                timed_out = True
                timeout_reason = f"连续{idle:.1f}秒无传输进展"
                terminate(process)
                break
        else:
            completed_at = float(state["input_completed_at"] or now)
            if now - completed_at > completion_timeout_seconds:
                timed_out = True
                timeout_reason = "输入完成后远端命令未在限定时间内退出"
                terminate(process)
                break
        time.sleep(0.25)
    worker.join(timeout=1)
    elapsed = max(time.monotonic() - started, 0.001)
    transferred = int(state["bytes"])
    if timed_out:
        print(f"[{label}] timeout: {timeout_reason}", file=sys.stderr, flush=True)
        return 124
    return_code = int(process.returncode or 0)
    if state["error"] is not None and return_code == 0:
        print(f"[{label}] stream_error={state['error']}", file=sys.stderr, flush=True)
        return 1
    print(
        f"[{label}] completed elapsed_seconds={elapsed:.1f} "
        f"transferred_bytes={transferred} "
        f"average_mib_s={transferred / elapsed / 1024 / 1024:.2f} "
        f"command_exit={return_code}",
        file=sys.stderr,
        flush=True,
    )
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--stall-timeout-seconds", type=float, default=60)
    parser.add_argument("--completion-timeout-seconds", type=float, default=120)
    parser.add_argument("--report-interval-seconds", type=float, default=5)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("缺少目标命令")
    return stream(
        sys.stdin.buffer,
        command,
        label=args.label,
        stall_timeout_seconds=args.stall_timeout_seconds,
        completion_timeout_seconds=args.completion_timeout_seconds,
        report_interval_seconds=args.report_interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())

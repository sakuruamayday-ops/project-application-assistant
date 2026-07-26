#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="串行执行生产部署命令")
    parser.add_argument("--lock-file", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("缺少待执行命令")

    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            owner = lock.read().strip() or "未知部署任务"
            print(f"生产部署已被其他任务锁定：{owner}", file=sys.stderr)
            return 75

        lock.seek(0)
        lock.truncate()
        json.dump(
            {
                "pid": os.getpid(),
                "cwd": os.getcwd(),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "command": command[0],
            },
            lock,
            ensure_ascii=False,
        )
        lock.flush()
        os.fsync(lock.fileno())

        environment = dict(os.environ)
        environment["JIAOTANG_DEPLOY_LOCK_HELD"] = "true"
        try:
            return subprocess.run(command, env=environment, check=False).returncode
        finally:
            lock.seek(0)
            lock.truncate()
            lock.flush()
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main())

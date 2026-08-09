#!/usr/bin/env python3
"""Build the versioned WorkBuddy Windows Hook with the pinned contract."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "runtime/workbuddy/windows_hook"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--go", dest="go_binary", default="")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    options = arguments()
    go_binary = (
        options.go_binary
        or os.environ.get("JIAOTANG_GO", "").strip()
        or shutil.which("go")
    )
    if not go_binary:
        raise SystemExit("缺少固定 Go 工具链，请传入 --go 或 JIAOTANG_GO")
    destination = options.output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(
        {"GOOS": "windows", "GOARCH": "amd64", "CGO_ENABLED": "0"}
    )
    subprocess.run(
        [
            go_binary,
            "build",
            "-buildvcs=false",
            "-trimpath",
            "-ldflags",
            "-s -w",
            "-o",
            str(destination),
            ".",
        ],
        cwd=SOURCE,
        env=environment,
        check=True,
    )
    if destination.read_bytes()[:2] != b"MZ":
        raise SystemExit("输出不是有效的 Windows PE 文件")
    print(f"{sha256(destination)}  {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Regenerate portal dependency locks with the pinned uv toolchain.

This maintenance command contacts the configured Python package index. It is
not used by production or by ordinary CI runs. Review the resulting lock diff
before committing it; this command does not perform vulnerability lookups.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from python_supply_chain import (
    LOCK_GENERATOR_VERSION,
    LOCK_TARGET_PYTHON,
    SupplyChainError,
    validate_hash_lock,
    write_lock_metadata,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portal-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser.parse_args()


def find_uv() -> str:
    configured = os.environ.get("JIAOTANG_UV_BIN", "").strip()
    candidate = configured or shutil.which("uv")
    if not candidate:
        raise SupplyChainError(
            f"缺少 uv {LOCK_GENERATOR_VERSION}；请先安装并显式评审工具链"
        )
    completed = subprocess.run(
        [candidate, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    expected_prefix = f"uv {LOCK_GENERATOR_VERSION} "
    if completed.returncode != 0 or not completed.stdout.startswith(
        expected_prefix
    ):
        observed = completed.stdout.strip() or completed.stderr.strip()
        raise SupplyChainError(
            f"uv 版本不匹配：要求 {LOCK_GENERATOR_VERSION}，实际 {observed!r}"
        )
    return candidate


def compile_lock(uv_bin: str, portal_dir: Path, source: str, output: str) -> None:
    custom_command = (
        f"uv pip compile {source} --universal "
        f"--python-version {LOCK_TARGET_PYTHON} --generate-hashes -o {output}"
    )
    command = [
        uv_bin,
        "pip",
        "compile",
        source,
        "--universal",
        "--python",
        sys.executable,
        "--no-python-downloads",
        "--generate-hashes",
        "--no-emit-index-url",
        "--custom-compile-command",
        custom_command,
        "-o",
        output,
    ]
    completed = subprocess.run(command, cwd=portal_dir, check=False)
    if completed.returncode != 0:
        raise SupplyChainError(f"依赖锁生成失败：{output}")
    validate_hash_lock(portal_dir / output)


def main() -> int:
    try:
        if f"{sys.version_info.major}.{sys.version_info.minor}" != LOCK_TARGET_PYTHON:
            raise SupplyChainError(
                f"依赖锁必须使用 Python {LOCK_TARGET_PYTHON} 生成，"
                f"当前为 {sys.version_info.major}.{sys.version_info.minor}"
            )
        portal_dir = parse_args().portal_dir.resolve(strict=True)
        uv_bin = find_uv()
        compile_lock(uv_bin, portal_dir, "requirements.in", "requirements.lock")
        compile_lock(
            uv_bin,
            portal_dir,
            "requirements-test.in",
            "requirements-test.lock",
        )
        compile_lock(
            uv_bin,
            portal_dir,
            "requirements-build.in",
            "requirements-build.lock",
        )
        metadata_path = write_lock_metadata(portal_dir)
        print(f"依赖锁与元数据生成完成：{metadata_path}")
    except (OSError, SupplyChainError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

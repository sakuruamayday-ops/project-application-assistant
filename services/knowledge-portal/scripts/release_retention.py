#!/usr/bin/env python3
"""Safely retain only the generations referenced by current and previous.

The caller must already hold the deployment or index-refresh transaction lock.
Cleanup is limited to direct child directories of the immutable generation
root after both pointers have been resolved and validated.  Candidates are
moved to the operating-system trash instead of being permanently deleted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECOVERABLE_STAGING_PATTERN = re.compile(
    r"^\..+\.staging\.(?:concurrent-release|failed-download)\.[A-Za-z0-9.-]+$"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def directory_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def validated_pointer(pointer_root: Path, generation_root: Path, name: str) -> Path:
    pointer = pointer_root / name
    if not pointer.is_symlink():
        raise RuntimeError(f"{name}不是符号链接，拒绝执行历史release回收")
    target = pointer.resolve(strict=True)
    if target.parent != generation_root or not target.is_dir() or target.is_symlink():
        raise RuntimeError(f"{name}未指向固定release根目录的直接子目录：{target}")
    return target


def plan_release_retention(generation_root: Path, pointer_root: Path) -> dict[str, Any]:
    if generation_root.is_symlink() or pointer_root.is_symlink():
        raise RuntimeError("release根目录和指针根目录不得为符号链接")
    generation_root = generation_root.resolve(strict=True)
    pointer_root = pointer_root.resolve(strict=True)
    if generation_root == Path("/") or pointer_root == Path("/"):
        raise RuntimeError("release根目录不得为系统根目录")
    if not generation_root.is_dir():
        raise RuntimeError("release根目录必须是实体目录")
    current = validated_pointer(pointer_root, generation_root, "current")
    previous = validated_pointer(pointer_root, generation_root, "previous")
    if current == previous:
        raise RuntimeError("current与previous不能指向同一release")
    retained = {current, previous}
    candidates: list[dict[str, Any]] = []
    for child in sorted(generation_root.iterdir(), key=lambda item: item.name):
        if child in retained or child.name in {"current", "previous"}:
            continue
        if child.name.startswith(".gc-"):
            if child.is_dir() and not child.is_symlink():
                candidates.append(
                    {"path": str(child), "bytes": directory_bytes(child), "state": "interrupted_gc"}
                )
            continue
        if RECOVERABLE_STAGING_PATTERN.fullmatch(child.name):
            if child.is_dir() and not child.is_symlink():
                candidates.append(
                    {
                        "path": str(child),
                        "bytes": directory_bytes(child),
                        "state": "recoverable_staging_copy",
                    }
                )
            continue
        if child.name.startswith("."):
            continue
        if child.is_symlink():
            raise RuntimeError(f"release根目录包含未授权符号链接：{child}")
        if child.is_dir():
            candidates.append(
                {"path": str(child), "bytes": directory_bytes(child), "state": "unreferenced"}
            )
    return {
        "schema": "jiaotang-release-retention/v1",
        "checked_at": utc_now(),
        "generation_root": str(generation_root),
        "pointer_root": str(pointer_root),
        "current": str(current),
        "previous": str(previous),
        "retained": [str(current), str(previous)],
        "candidates": candidates,
        "candidate_count": len(candidates),
        "candidate_bytes": sum(int(item["bytes"]) for item in candidates),
        "applied": False,
    }


def prune_release_generations(
    generation_root: Path,
    pointer_root: Path,
    *,
    apply: bool,
    trash_root: Path | None = None,
) -> dict[str, Any]:
    report = plan_release_retention(generation_root, pointer_root)
    removed: list[dict[str, Any]] = []
    trashed: list[dict[str, Any]] = []
    concurrently_removed: list[dict[str, Any]] = []
    if apply:
        if trash_root is None:
            configured_trash = os.environ.get("JIAOTANG_RELEASE_TRASH_ROOT", "").strip()
            trash_root = (
                Path(configured_trash)
                if configured_trash
                else generation_root / ".Trash" / "files"
            )
        trash_root = trash_root.expanduser()
        if trash_root == Path("/") or trash_root.is_symlink():
            raise RuntimeError("回收站目录不得为系统根目录或符号链接")
        trash_root.mkdir(parents=True, exist_ok=True)
        trash_root = trash_root.resolve(strict=True)
        if generation_root.stat().st_dev != trash_root.stat().st_dev:
            raise RuntimeError(
                "发布槽与可恢复回收区不在同一文件系统，拒绝复制后删除"
            )
        for item in report["candidates"]:
            original = Path(str(item["path"]))
            destination = trash_root / (
                f"jiaotang-release-{original.name}-{os.getpid()}-{secrets.token_hex(4)}"
            )
            # Retention is an atomic same-filesystem rename.  Never fall back
            # to copy-then-delete, which can duplicate a large release before
            # a sandbox or permission error prevents the source removal.
            try:
                os.rename(original, destination)
            except FileNotFoundError:
                # Another retention worker may have completed the same
                # atomic rename after this worker produced its plan. Treat
                # an actually absent direct child as an idempotent success;
                # preserve every other rename error for operator review.
                if original.exists() or original.is_symlink():
                    raise
                concurrently_removed.append(item)
                continue
            moved = {**item, "trash_path": str(destination)}
            trashed.append(moved)
            removed.append(moved)
        report["applied"] = True
        report["delete_mode"] = "recoverable_system_trash"
        report["trash_root"] = str(trash_root)
    report["removed"] = removed
    report["trashed"] = trashed
    report["concurrently_removed"] = concurrently_removed
    report["concurrently_removed_count"] = len(concurrently_removed)
    report["removed_count"] = len(removed)
    report["removed_bytes"] = sum(int(item["bytes"]) for item in removed)
    report["completed_at"] = utc_now()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="只保留current与previous不可变release")
    parser.add_argument("--generation-root", required=True, type=Path)
    parser.add_argument("--pointer-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--trash-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = prune_release_generations(
        args.generation_root,
        args.pointer_root,
        apply=args.apply,
        trash_root=args.trash_root,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

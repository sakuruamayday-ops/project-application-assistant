#!/usr/bin/env python3
"""只读盘点正式发布指针、槽位、暂存区和工作树异常。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def directory_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def resolve_pointer(path: Path) -> str | None:
    try:
        return str(path.resolve(strict=True)) if path.is_symlink() else None
    except OSError:
        return None


def worktree_inventory(repository: Path) -> dict[str, object]:
    process = subprocess.run(
        ["git", "-C", str(repository), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode:
        return {"available": False, "error": process.stderr.strip()[:500]}
    worktrees: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in process.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.removeprefix("worktree ")}
        elif current is not None and line.startswith("branch "):
            current["branch"] = line.removeprefix("branch ")
        elif current is not None and line == "prunable":
            current["prunable"] = True
    if current:
        worktrees.append(current)
    dirty = 0
    for item in worktrees:
        path = Path(str(item["path"]))
        if path.is_dir():
            status = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
            )
            item["dirty"] = bool(status.stdout.strip())
            dirty += int(bool(item["dirty"]))
    return {
        "available": True,
        "total": len(worktrees),
        "dirty": dirty,
        "prunable": sum(1 for item in worktrees if item.get("prunable")),
        "worktrees": worktrees,
    }


def audit(
    repository: Path,
    runtime_root: Path,
    release_root: Path,
    skill_release_dir: Path,
) -> dict[str, object]:
    slots = sorted(
        (item for item in release_root.iterdir() if item.is_dir()),
        key=lambda item: item.name,
        reverse=True,
    ) if release_root.is_dir() else []
    current = resolve_pointer(runtime_root / "current")
    previous = resolve_pointer(runtime_root / "previous")
    referenced = {value for value in (current, previous) if value}
    unreferenced = [str(item) for item in slots if str(item.resolve()) not in referenced]
    return {
        "schema": "jiaotang-release-location-audit/v1",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "canonical_repository": str(repository),
        "runtime": {
            "root": str(runtime_root),
            "current": current,
            "previous": previous,
            "slot_count": len(slots),
            "unreferenced_slot_count": len(unreferenced),
            "unreferenced_slots": unreferenced,
            "slot_bytes": sum(directory_size(item) for item in slots),
        },
        "skill_releases": {
            "root": str(skill_release_dir),
            "staging_bytes": directory_size(skill_release_dir / ".staging"),
            "trash_bytes": directory_size(skill_release_dir / ".trash"),
            "failed_attempt_bytes": directory_size(skill_release_dir / ".failed-attempts"),
        },
        "worktrees": worktree_inventory(repository),
        "mutations_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读盘点焦糖发布位置和历史资源")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--runtime-root", type=Path, default=Path("/opt/jiaotang-kb-runtime"))
    parser.add_argument("--release-root", type=Path, default=Path("/opt/jiaotang-kb-release-slots"))
    parser.add_argument("--skill-release-dir", type=Path, default=Path(os.environ.get("JIAOTANG_SKILL_RELEASE_DIR", "/srv/jiaotang/skill-releases")))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(
        args.repository.expanduser().resolve(),
        args.runtime_root.expanduser().resolve(),
        args.release_root.expanduser().resolve(),
        args.skill_release_dir.expanduser().resolve(),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

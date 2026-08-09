from __future__ import annotations

import importlib.util
import errno
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_retention.py"
SPEC = importlib.util.spec_from_file_location("release_retention", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_layout(tmp_path: Path):
    generations = tmp_path / "releases"
    pointers = tmp_path / "runtime"
    generations.mkdir()
    pointers.mkdir()
    current = generations / "current-generation"
    previous = generations / "previous-generation"
    stale_a = generations / "stale-a"
    stale_b = generations / "stale-b"
    for path in (current, previous, stale_a, stale_b):
        path.mkdir()
        (path / "payload.bin").write_bytes(b"x" * 16)
    (pointers / "current").symlink_to(current)
    (pointers / "previous").symlink_to(previous)
    return generations, pointers, current, previous, stale_a, stale_b


def test_retention_dry_run_does_not_modify_generations(tmp_path: Path):
    generations, pointers, current, previous, stale_a, stale_b = make_layout(tmp_path)

    report = MODULE.prune_release_generations(generations, pointers, apply=False)

    assert report["candidate_count"] == 2
    assert report["removed_count"] == 0
    assert current.is_dir() and previous.is_dir()
    assert stale_a.is_dir() and stale_b.is_dir()


def test_retention_apply_keeps_exactly_current_and_previous(tmp_path: Path):
    generations, pointers, current, previous, stale_a, stale_b = make_layout(tmp_path)
    duplicate_staging = (
        generations
        / ".index-release-1234.staging.concurrent-release.20260808T010203Z.deadbeef"
    )
    duplicate_staging.mkdir()
    (duplicate_staging / "duplicate.bin").write_bytes(b"duplicate")

    trash = tmp_path / "trash"
    report = MODULE.prune_release_generations(
        generations, pointers, apply=True, trash_root=trash
    )

    assert report["removed_count"] == 3
    assert current.is_dir() and previous.is_dir()
    assert not stale_a.exists() and not stale_b.exists() and not duplicate_staging.exists()
    assert report["delete_mode"] == "recoverable_system_trash"
    assert report["trash_root"] == str(trash.resolve())
    assert len(list(trash.iterdir())) == 3
    assert sorted(path.name for path in generations.iterdir()) == [
        "current-generation",
        "previous-generation",
    ]


def test_retention_default_trash_stays_inside_generation_root(
    tmp_path: Path, monkeypatch
):
    generations, pointers, current, previous, stale_a, stale_b = make_layout(
        tmp_path
    )
    monkeypatch.delenv("JIAOTANG_RELEASE_TRASH_ROOT", raising=False)

    report = MODULE.prune_release_generations(generations, pointers, apply=True)

    trash = generations / ".Trash" / "files"
    assert report["trash_root"] == str(trash.resolve())
    assert report["removed_count"] == 2
    assert current.is_dir() and previous.is_dir()
    assert not stale_a.exists() and not stale_b.exists()
    assert len(list(trash.iterdir())) == 2


def test_retention_refuses_pointer_outside_generation_root(tmp_path: Path):
    generations, pointers, _, previous, _, _ = make_layout(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (pointers / "current").unlink()
    (pointers / "current").symlink_to(outside)

    with pytest.raises(RuntimeError, match="固定release根目录"):
        MODULE.prune_release_generations(generations, pointers, apply=True)

    assert previous.is_dir()


def test_retention_never_falls_back_to_copy_then_delete(
    tmp_path: Path, monkeypatch
):
    generations, pointers, current, previous, stale_a, stale_b = make_layout(
        tmp_path
    )
    trash = tmp_path / "trash"
    real_rename = MODULE.os.rename

    def reject_release_move(source, destination):
        if Path(source).parent == generations:
            raise OSError(errno.EXDEV, "cross-device move forbidden")
        return real_rename(source, destination)

    monkeypatch.setattr(MODULE.os, "rename", reject_release_move)

    with pytest.raises(OSError, match="cross-device move forbidden"):
        MODULE.prune_release_generations(
            generations, pointers, apply=True, trash_root=trash
        )

    assert current.is_dir() and previous.is_dir()
    assert stale_a.is_dir() and stale_b.is_dir()
    assert list(trash.iterdir()) == []


def test_retention_tolerates_candidate_already_moved_by_concurrent_worker(
    tmp_path: Path, monkeypatch
):
    generations, pointers, current, previous, stale_a, stale_b = make_layout(
        tmp_path
    )
    trash = tmp_path / "trash"
    real_rename = MODULE.os.rename
    raced = False

    def race_first_release_move(source, destination):
        nonlocal raced
        source_path = Path(source)
        if not raced and source_path.parent == generations:
            raced = True
            concurrent_destination = trash / "moved-by-concurrent-worker"
            real_rename(source_path, concurrent_destination)
            raise FileNotFoundError(errno.ENOENT, "already moved", source_path)
        return real_rename(source, destination)

    monkeypatch.setattr(MODULE.os, "rename", race_first_release_move)

    report = MODULE.prune_release_generations(
        generations, pointers, apply=True, trash_root=trash
    )

    assert report["concurrently_removed_count"] == 1
    assert report["removed_count"] == 1
    assert current.is_dir() and previous.is_dir()
    assert not stale_a.exists() and not stale_b.exists()
    assert sorted(path.name for path in generations.iterdir()) == [
        "current-generation",
        "previous-generation",
    ]

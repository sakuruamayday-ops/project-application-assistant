from __future__ import annotations

import importlib.util
import json
import sqlite3
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "publish_skill_release.py"
SPEC = importlib.util.spec_from_file_location("publish_skill_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_packages(
    root: Path,
    *,
    tag: str = "V1.2",
    semantic_version: str = "1.2.0",
) -> tuple[Path, Path]:
    generic = root / "generic.zip"
    workbuddy = root / "workbuddy.zip"
    suite = {
        "release": {"tag": tag, "version": semantic_version},
        "skills": [f"skill-{index}" for index in range(48)],
    }
    with zipfile.ZipFile(generic, "w") as archive:
        archive.writestr("bundle/skills/suite-manifest.json", json.dumps(suite))
    with zipfile.ZipFile(workbuddy, "w") as archive:
        archive.writestr(
            "jiaotang/.codebuddy-plugin/marketplace.json",
            json.dumps({"plugins": [{"version": semantic_version}]}),
        )
        archive.writestr(
            "jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json",
            json.dumps({"version": semantic_version}),
        )
        archive.writestr("jiaotang/plugins/plugin/skills/suite-manifest.json", json.dumps(suite))
        archive.writestr("jiaotang/install-jiaotang-workbuddy.command", "#!/bin/zsh\n")
        archive.writestr("jiaotang/install-jiaotang-workbuddy.cmd", "@echo off\r\n")
        archive.writestr("jiaotang/install-jiaotang-workbuddy.ps1", "exit 0\r\n")
    return generic, workbuddy


def make_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE skill_releases(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                release_notes TEXT NOT NULL,
                published_at TEXT NOT NULL
            )
            """
        )


def test_publish_is_validated_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "portal.db"
    release_dir = tmp_path / "releases"
    generic, workbuddy = make_packages(tmp_path)
    make_database(database)

    result = MODULE.publish(database, release_dir, generic, workbuddy, "1.2", "notes")
    assert result["status"] == "published"
    assert result["skill_count"] == 48
    assert (release_dir / "企业全生命周期助手-V1.2.zip").is_file()
    assert (release_dir / "企业全生命周期助手-V1.2-WorkBuddy.zip").is_file()

    repeated = MODULE.publish(database, release_dir, generic, workbuddy, "1.2", "notes")
    assert repeated["status"] == "already-published"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM skill_releases").fetchone()[0] == 1


def test_two_stage_release_requires_stage_before_promotion(tmp_path: Path) -> None:
    database = tmp_path / "portal.db"
    release_dir = tmp_path / "releases"
    generic, workbuddy = make_packages(tmp_path)
    make_database(database)

    try:
        MODULE.promote(database, release_dir, "1.2")
    except RuntimeError as error:
        assert "未处于正式发布中" in str(error)
    else:
        raise AssertionError("promotion must be blocked before staging")

    staged = MODULE.stage(
        database,
        release_dir,
        generic,
        workbuddy,
        "1.2",
        "notes",
        "abc123",
        "https://github.example/releases/V1.2",
    )
    assert staged["status"] == "staged"
    assert staged["release_state"] == "releasing"
    assert not (release_dir / "企业全生命周期助手-V1.2.zip").exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM skill_releases").fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM skill_release_stages WHERE version='1.2'"
        ).fetchone()[0] == "releasing"

    repeated = MODULE.stage(
        database,
        release_dir,
        generic,
        workbuddy,
        "1.2",
        "notes",
        "abc123",
        "https://github.example/releases/V1.2",
    )
    assert repeated["status"] == "already-staged"

    promoted = MODULE.promote(database, release_dir, "1.2")
    assert promoted["release_state"] == "published"
    assert (release_dir / "企业全生命周期助手-V1.2.zip").is_file()
    assert (release_dir / "企业全生命周期助手-V1.2-WorkBuddy.zip").is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status FROM skill_release_stages WHERE version='1.2'"
        ).fetchone()[0] == "published"


def test_publish_rejects_version_mismatch(tmp_path: Path) -> None:
    generic, workbuddy = make_packages(tmp_path)
    try:
        MODULE.validate_packages(generic, workbuddy, "1.3")
    except ValueError as error:
        assert "版本" in str(error)
    else:
        raise AssertionError("expected a version mismatch")


def test_validate_packages_accepts_patch_release(tmp_path: Path) -> None:
    generic, workbuddy = make_packages(
        tmp_path,
        tag="V1.3.1",
        semantic_version="1.3.1",
    )
    result = MODULE.validate_packages(generic, workbuddy, "1.3.1")
    assert result["version"] == "1.3.1"
    assert result["skill_count"] == 48


def test_windows_only_hotfix_accepts_four_part_version(tmp_path: Path) -> None:
    _, workbuddy = make_packages(
        tmp_path,
        tag="V1.3.1.1",
        semantic_version="1.3.1.1",
    )
    result = MODULE.validate_release_packages(
        {"windows": workbuddy},
        "1.3.1.1",
    )
    assert result["targets"] == ["windows"]
    assert result["skill_count"] == 48


def test_selective_stage_and_promote_windows_only(tmp_path: Path) -> None:
    database = tmp_path / "portal.db"
    release_dir = tmp_path / "releases"
    _, workbuddy = make_packages(
        tmp_path,
        tag="V1.3.1.1",
        semantic_version="1.3.1.1",
    )
    make_database(database)

    staged = MODULE.stage_selective(
        database,
        release_dir,
        {"windows": workbuddy},
        "1.3.1.1",
        "Windows hotfix",
        "abc123",
        "https://github.example/releases/V1.3.1.1",
    )
    assert staged["targets"] == ["windows"]
    assert staged["release_state"] == "releasing"

    promoted = MODULE.promote_selective(
        database,
        release_dir,
        "1.3.1.1",
    )
    assert promoted["release_state"] == "published"
    assert (
        release_dir
        / "企业全生命周期助手-V1.3.1.1-WorkBuddy-Windows.zip"
    ).is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT target FROM skill_release_artifacts"
        ).fetchall() == [("windows",)]

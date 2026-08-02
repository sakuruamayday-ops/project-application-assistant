from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "migrate_first_public_release.py"
SPEC = importlib.util.spec_from_file_location("migrate_first_public_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def build_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE users(id INTEGER PRIMARY KEY);
            CREATE TABLE skill_releases(
                id INTEGER PRIMARY KEY,version TEXT,file_name TEXT,file_path TEXT,
                sha256 TEXT,release_notes TEXT,published_at TEXT
            );
            INSERT INTO skill_releases VALUES(
                1,'1.4.9','old.zip','/releases/old.zip','old-sha','历史版本','2026-08-02'
            );
            """
        )


def test_migration_never_rewrites_history_when_v150_is_absent(tmp_path: Path):
    database = tmp_path / "knowledge.db"
    build_database(database)

    result = MODULE.migrate(database, tmp_path / "releases")

    assert result["status"] == "awaiting-release"
    assert result["history_rewritten"] is False
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT version,file_path,sha256 FROM skill_releases WHERE id=1"
        ).fetchone()
    assert row == ("1.4.9", "/releases/old.zip", "old-sha")


def test_migration_publishes_only_v150_announcement(tmp_path: Path):
    database = tmp_path / "knowledge.db"
    build_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO skill_releases VALUES(2,'1.5.0','new.zip',?,?,'首发','2026-08-02')",
            (str(tmp_path / "releases" / "new.zip"), "new-sha"),
        )

    result = MODULE.migrate(database, tmp_path / "releases")

    assert result["version"] == "1.5.0"
    assert result["history_rewritten"] is False
    with sqlite3.connect(database) as connection:
        releases = connection.execute(
            "SELECT id,version,file_path,sha256 FROM skill_releases ORDER BY id"
        ).fetchall()
        announcement = connection.execute(
            "SELECT release_id,status,title FROM release_announcements"
        ).fetchone()
    assert releases[0] == (1, "1.4.9", "/releases/old.zip", "old-sha")
    assert releases[1][1:] == (
        "1.5.0",
        str(tmp_path / "releases" / "new.zip"),
        "new-sha",
    )
    assert announcement == (
        2,
        "published",
        "欢迎使用企业全生命周期助手 V1.5.0",
    )

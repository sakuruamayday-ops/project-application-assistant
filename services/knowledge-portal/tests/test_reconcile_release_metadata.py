from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_release_metadata.py"
SPEC = importlib.util.spec_from_file_location("reconcile_release_metadata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_reconcile_repairs_published_stage_paths_without_moving_files(tmp_path: Path):
    database = tmp_path / "knowledge.db"
    release_directory = tmp_path / "releases"
    release_directory.mkdir()
    generic = release_directory / "企业全生命周期助手-V1.2.zip"
    workbuddy = release_directory / "企业全生命周期助手-V1.2-WorkBuddy.zip"
    generic.write_bytes(b"generic")
    workbuddy.write_bytes(b"workbuddy")
    staging = release_directory / ".staging" / "V1.2"
    staging.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        MODULE._ensure_stage_table(connection)
        connection.execute(
            """
            INSERT INTO skill_release_stages(
                version,status,generic_path,generic_sha256,workbuddy_path,workbuddy_sha256,
                release_notes,git_commit,github_url,staged_at,promoted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "1.2", "published", str(staging / generic.name), MODULE.sha256(generic),
                str(staging / workbuddy.name), MODULE.sha256(workbuddy), "notes", "abc",
                "https://example.invalid", "2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z",
            ),
        )
        connection.executemany(
            "INSERT INTO skill_release_stage_artifacts(version,target,file_path,sha256) VALUES (?,?,?,?)",
            [
                ("1.2", "generic", str(staging / generic.name), MODULE.sha256(generic)),
                ("1.2", "workbuddy", str(staging / workbuddy.name), MODULE.sha256(workbuddy)),
            ],
        )
        connection.commit()

    report = MODULE.audit(database, release_directory)
    assert report["repairable"] == 4
    assert report["unrepairable"] == 0
    backup = MODULE.apply_repairs(database, report)
    assert backup and Path(backup).is_file()
    assert generic.is_file() and workbuddy.is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT generic_path,workbuddy_path FROM skill_release_stages WHERE version='1.2'"
        ).fetchone() == (str(generic), str(workbuddy))
        assert connection.execute(
            "SELECT target,file_path FROM skill_release_stage_artifacts ORDER BY target"
        ).fetchall() == [("generic", str(generic)), ("workbuddy", str(workbuddy))]


def test_reconcile_can_scope_audit_to_current_release(tmp_path: Path):
    database = tmp_path / "knowledge.db"
    release_directory = tmp_path / "releases"
    release_directory.mkdir()
    current = release_directory / "企业全生命周期助手-V1.6.0.zip"
    current.write_bytes(b"current")
    with sqlite3.connect(database) as connection:
        MODULE._ensure_stage_table(connection)
        connection.executemany(
            "INSERT INTO skill_release_stage_artifacts(version,target,file_path,sha256) VALUES (?,?,?,?)",
            [
                ("1.4.9", "generic", "/removed/legacy.zip", "0" * 64),
                ("1.6.0", "generic", str(current), MODULE.sha256(current)),
            ],
        )
        connection.commit()

    full_report = MODULE.audit(database, release_directory)
    assert full_report["unrepairable"] == 1
    scoped_report = MODULE.audit(database, release_directory, {"1.6.0"})
    assert scoped_report["versions"] == ["1.6.0"]
    assert scoped_report["repairable"] == 0
    assert scoped_report["unrepairable"] == 0
    assert scoped_report["findings"] == []

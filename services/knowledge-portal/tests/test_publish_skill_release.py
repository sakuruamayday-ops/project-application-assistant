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


def make_packages(root: Path) -> tuple[Path, Path]:
    generic = root / "generic.zip"
    workbuddy = root / "workbuddy.zip"
    suite = {
        "release": {"tag": "V1.2", "version": "1.2.0"},
        "skills": [f"skill-{index}" for index in range(56)],
    }
    with zipfile.ZipFile(generic, "w") as archive:
        archive.writestr("bundle/skills/suite-manifest.json", json.dumps(suite))
    with zipfile.ZipFile(workbuddy, "w") as archive:
        archive.writestr(
            "jiaotang/.codebuddy-plugin/marketplace.json",
            json.dumps({"plugins": [{"version": "1.2.0"}]}),
        )
        archive.writestr(
            "jiaotang/plugins/plugin/.codebuddy-plugin/plugin.json",
            json.dumps({"version": "1.2.0"}),
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
    assert (release_dir / "企业全生命周期助手-V1.2.zip").is_file()
    assert (release_dir / "企业全生命周期助手-V1.2-WorkBuddy.zip").is_file()

    repeated = MODULE.publish(database, release_dir, generic, workbuddy, "1.2", "notes")
    assert repeated["status"] == "already-published"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM skill_releases").fetchone()[0] == 1


def test_publish_rejects_version_mismatch(tmp_path: Path) -> None:
    generic, workbuddy = make_packages(tmp_path)
    try:
        MODULE.validate_packages(generic, workbuddy, "1.3")
    except ValueError as error:
        assert "版本" in str(error)
    else:
        raise AssertionError("expected a version mismatch")


def test_publish_requires_both_successful_hosts_when_evidence_is_supplied(
    tmp_path: Path,
) -> None:
    database = tmp_path / "portal.db"
    release_dir = tmp_path / "releases"
    generic, workbuddy = make_packages(tmp_path)
    make_database(database)
    evidence = tmp_path / "host-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": "jiaotang-workbuddy-host-matrix/v1",
                "status": "pass",
                "release_tag": "V1.2",
                "hosts": {
                    "macos": {"status": "pass"},
                    "windows": {"status": "pass"},
                },
            }
        ),
        encoding="utf-8",
    )

    result = MODULE.publish(
        database,
        release_dir,
        generic,
        workbuddy,
        "1.2",
        "notes",
        evidence,
    )
    assert result["status"] == "published"
    assert Path(result["host_evidence_path"]).is_file()

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["hosts"]["windows"]["status"] = "pending"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    try:
        MODULE.validate_host_evidence(evidence, "1.2")
    except ValueError as error:
        assert "windows" in str(error)
    else:
        raise AssertionError("expected missing Windows evidence to fail")

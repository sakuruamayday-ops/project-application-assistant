from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load_script("release_retention")
MODULE = load_script("client_release_retention")


def make_layout(tmp_path: Path):
    release_root = tmp_path / "desktop-client-releases"
    macos_root = release_root / "v0.2" / "macos"
    windows_root = release_root / "v0.2" / "windows"
    macos_root.mkdir(parents=True)
    windows_root.mkdir(parents=True)
    database = tmp_path / "knowledge.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE client_releases(
            id INTEGER PRIMARY KEY,
            version TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            published_at TEXT
        );
        CREATE TABLE client_release_artifacts(
            id INTEGER PRIMARY KEY,
            release_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            architecture TEXT NOT NULL,
            file_kind TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL
        );
        """
    )
    connection.executemany(
        "INSERT INTO client_releases(id,version,status,published_at) VALUES (?,?,?,?)",
        (
            (7, "0.2.3", "retired", "2026-08-23T00:00:00Z"),
            (10, "0.2.7", "retired", "2026-08-24T00:00:00Z"),
            (11, "0.2.8", "published", "2026-08-25T00:00:00Z"),
        ),
    )
    files: dict[str, Path] = {}
    for release_id, version, payload in (
        (7, "0.2.3", b"old"),
        (10, "0.2.7", b"previous"),
        (11, "0.2.8", b"current"),
    ):
        name = f"Gongchuang-Enterprise-Assistant-{version}-mac-arm64.dmg"
        path = macos_root / name
        path.write_bytes(payload)
        files[version] = path
        connection.execute(
            """
            INSERT INTO client_release_artifacts(
                release_id,platform,architecture,file_kind,file_name,file_path,size_bytes
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (release_id, "macos", "arm64", "dmg", name, str(path), len(payload)),
        )
    old_windows = windows_root / "Gongchuang-Enterprise-Assistant-0.2.3-win-x64.exe"
    old_windows.write_bytes(b"old-windows")
    files["old_windows"] = old_windows
    (macos_root / "desktop-release-index.json").write_text(
        json.dumps({"clientVersion": "0.2.8"}), encoding="utf-8"
    )
    (macos_root / "desktop-release-index.sig").write_bytes(b"signature")
    (windows_root / "latest.yml").write_text("version: 0.2.8\n", encoding="utf-8")
    staging_root = release_root / ".staging"
    old_staging = staging_root / "v0.2.3-old-release"
    previous_staging = staging_root / "v0.2.7-previous-release"
    current_staging = staging_root / "v0.2.8-current-release"
    candidate_staging = staging_root / "v0.2.9-next-candidate"
    for directory in (
        old_staging,
        previous_staging,
        current_staging,
        candidate_staging,
    ):
        directory.mkdir(parents=True)
        (directory / "release.json").write_text("{}\n", encoding="utf-8")
    connection.commit()
    connection.close()
    staging = {
        "old": old_staging,
        "previous": previous_staging,
        "current": current_staging,
        "candidate": candidate_staging,
    }
    return database, release_root, files, staging


def test_dry_run_keeps_release_artifacts_and_reports_completed_staging(tmp_path: Path):
    database, release_root, files, staging = make_layout(tmp_path)

    report = MODULE.prune_client_release_artifacts(
        database, release_root, apply=False
    )

    assert report["current"] == "0.2.8"
    assert report["previous"] == "0.2.7"
    assert report["candidate_count"] == 5
    assert report["trashed_count"] == 0
    assert all(path.is_file() for path in files.values())
    assert all(path.is_dir() for path in staging.values())


def test_apply_keeps_current_and_previous_artifacts_but_cleans_known_staging(
    tmp_path: Path,
):
    database, release_root, files, staging = make_layout(tmp_path)
    trash = tmp_path / "trash"

    report = MODULE.prune_client_release_artifacts(
        database,
        release_root,
        apply=True,
        trash_root=trash,
    )

    assert report["trashed_count"] == 5
    assert report["delete_mode"] == "recoverable_system_trash"
    assert not files["0.2.3"].exists()
    assert not files["old_windows"].exists()
    assert files["0.2.7"].is_file()
    assert files["0.2.8"].is_file()
    assert not staging["old"].exists()
    assert not staging["previous"].exists()
    assert not staging["current"].exists()
    assert staging["candidate"].is_dir()
    assert (release_root / "v0.2/macos/desktop-release-index.json").is_file()
    assert (release_root / "v0.2/windows/latest.yml").is_file()
    assert report["cleanup_pending"]["authorization_required"] is True
    assert report["cleanup_pending"]["permanent_delete_applied"] is False


def test_refuses_manifest_version_drift(tmp_path: Path):
    database, release_root, _, _ = make_layout(tmp_path)
    (release_root / "v0.2/windows/latest.yml").write_text(
        "version: 0.2.7\n", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="Windows 更新清单"):
        MODULE.prune_client_release_artifacts(database, release_root, apply=True)


def test_refuses_unretired_orphan_asset(tmp_path: Path):
    database, release_root, _, _ = make_layout(tmp_path)
    orphan = (
        release_root
        / "v0.2/macos/Gongchuang-Enterprise-Assistant-0.2.9-mac-arm64.dmg"
    )
    orphan.write_bytes(b"candidate")

    with pytest.raises(RuntimeError, match="未退役版本"):
        MODULE.prune_client_release_artifacts(database, release_root, apply=True)

    assert orphan.is_file()


def test_refuses_retained_artifact_outside_release_root(tmp_path: Path):
    database, release_root, files, _ = make_layout(tmp_path)
    outside = tmp_path / "outside.dmg"
    outside.write_bytes(files["0.2.8"].read_bytes())
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE client_release_artifacts SET file_path=? WHERE release_id=11",
        (str(outside),),
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="不在正式发布根目录"):
        MODULE.prune_client_release_artifacts(database, release_root, apply=True)


def test_cleanup_backlog_ignores_other_server_trash(tmp_path: Path):
    trash = tmp_path / "trash"
    unrelated = trash / "jiaotang-release-old-app"
    related = trash / "desktop-client-v0.2.3-old"
    unrelated.mkdir(parents=True)
    related.mkdir()
    (unrelated / "many-files.bin").write_bytes(b"unrelated")
    (related / "installer.exe").write_bytes(b"client")

    report = MODULE.client_cleanup_backlog(trash)

    assert report["target_count"] == 1
    assert report["targets"][0]["path"] == str(related.resolve())

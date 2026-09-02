import importlib.util
import sqlite3
from pathlib import Path

import pytest

from test_skill_update_feed import make_desktop_projection


SCRIPT = Path(__file__).parents[1] / "scripts" / "publish_client_skill_update.py"
SPEC = importlib.util.spec_from_file_location("publish_client_skill_update", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_database(path: Path, version: str = "1.6.6") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE skill_releases(
                id INTEGER PRIMARY KEY,
                version TEXT NOT NULL UNIQUE
            )
            """
        )
        connection.execute(
            "INSERT INTO skill_releases(id,version) VALUES(1,?)",
            (version,),
        )


def test_client_update_requires_signed_transaction_and_published_generic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = "1.6.6"
    archive = tmp_path / "desktop.zip"
    make_desktop_projection(archive, version=version)
    database = tmp_path / "portal.db"
    make_database(database, version)
    transaction = {
        "version": version,
        "participants": {
            "client_update": {
                "release_version": version,
                "archive_sha256": MODULE.sha256(archive),
                "public_key_sha256": MODULE.CLIENT_SKILL_UPDATE_PUBLIC_KEY_SHA256,
                "required_result": "public-feed-readback-and-client-verification-pass",
            }
        },
    }
    monkeypatch.setattr(
        MODULE,
        "verify_transaction_files",
        lambda **_kwargs: {
            "manifest": transaction,
            "manifest_sha256": "a" * 64,
        },
    )
    placeholder = tmp_path / "placeholder"
    placeholder.write_text("test", encoding="utf-8")

    result = MODULE.publish_transaction_update(
        database=database,
        release_directory=tmp_path / "updates",
        archive=archive,
        version=version,
        release_notes="notes",
        transaction_manifest=placeholder,
        transaction_signature=placeholder,
        publisher_public_key=placeholder,
    )

    assert result["status"] == "published"
    assert result["validation"]["status"] == "verified"


def test_client_update_rejects_an_archive_not_bound_to_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "desktop.zip"
    make_desktop_projection(archive)
    database = tmp_path / "portal.db"
    make_database(database)
    monkeypatch.setattr(
        MODULE,
        "verify_transaction_files",
        lambda **_kwargs: {
            "manifest": {"version": "1.6.6", "participants": {}},
            "manifest_sha256": "a" * 64,
        },
    )
    placeholder = tmp_path / "placeholder"
    placeholder.write_text("test", encoding="utf-8")

    with pytest.raises(RuntimeError, match="未绑定"):
        MODULE.publish_transaction_update(
            database=database,
            release_directory=tmp_path / "updates",
            archive=archive,
            version="1.6.6",
            release_notes="notes",
            transaction_manifest=placeholder,
            transaction_signature=placeholder,
            publisher_public_key=placeholder,
        )

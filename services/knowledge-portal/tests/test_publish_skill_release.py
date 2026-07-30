from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sqlite3
import struct
import textwrap
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCRIPT = Path(__file__).parents[1] / "scripts" / "publish_skill_release.py"
SPEC = importlib.util.spec_from_file_location("publish_skill_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
TEST_RAW_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)


def ssh_string(value: bytes | str) -> bytes:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack(">I", len(payload)) + payload


TEST_PUBLIC_BLOB = (
    ssh_string(b"ssh-ed25519") + ssh_string(TEST_RAW_PUBLIC_KEY)
)
TEST_PUBLIC_TEXT = (
    "ssh-ed25519 "
    + base64.b64encode(TEST_PUBLIC_BLOB).decode("ascii")
    + " portal-release-test"
)
TEST_FINGERPRINT = "SHA256:" + base64.b64encode(
    hashlib.sha256(TEST_PUBLIC_BLOB).digest()
).decode("ascii").rstrip("=")
MODULE.TRUSTED_PUBLISHER_PUBLIC_KEY = TEST_PUBLIC_TEXT
MODULE.TRUSTED_PUBLISHER_FINGERPRINT = TEST_FINGERPRINT


def sign_manifest(payload: bytes) -> bytes:
    namespace = MODULE.WORKBUDDY_SIGNATURE_NAMESPACE
    digest = hashlib.sha512(payload).digest()
    signed_data = b"".join(
        (
            b"SSHSIG",
            ssh_string(namespace),
            ssh_string(b""),
            ssh_string("sha512"),
            ssh_string(digest),
        )
    )
    signature = TEST_PRIVATE_KEY.sign(signed_data)
    signature_blob = ssh_string(b"ssh-ed25519") + ssh_string(signature)
    sshsig = b"".join(
        (
            b"SSHSIG",
            struct.pack(">I", 1),
            ssh_string(TEST_PUBLIC_BLOB),
            ssh_string(namespace),
            ssh_string(b""),
            ssh_string("sha512"),
            ssh_string(signature_blob),
        )
    )
    encoded = base64.b64encode(sshsig).decode("ascii")
    body = "\n".join(textwrap.wrap(encoded, 70))
    return (
        "-----BEGIN SSH SIGNATURE-----\n"
        + body
        + "\n-----END SSH SIGNATURE-----\n"
    ).encode("ascii")


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
    plugin_files = {
        ".codebuddy-plugin/plugin.json": json.dumps(
            {
                "name": "jiaotang-workbuddy-skills",
                "version": semantic_version,
                "mcpServers": {
                    "jiaotang-kb": {
                        "command": "${CODEBUDDY_PLUGIN_ROOT}/bin/run-node",
                        "args": [
                            (
                                "${CODEBUDDY_PLUGIN_ROOT}/mcp/"
                                "jiaotang-agent.mjs"
                            ),
                            "plugin-serve",
                        ],
                    }
                },
            }
        ).encode("utf-8"),
        "bin/run-node": b"#!/bin/sh\n",
        "bin/run-node.cmd": b"@echo off\r\n",
        "mcp/jiaotang-agent.mjs": b"#!/usr/bin/env node\n",
        "skills/suite-manifest.json": json.dumps(suite).encode("utf-8"),
    }
    plugin_manifest = {
        "schema_version": 1,
        "artifact_type": "workbuddy-plugin",
        "plugin_name": "jiaotang-workbuddy-skills",
        "release_tag": tag,
        "skills": suite["skills"],
        "binding_key": ["session_id", "turn_id", "skill_name"],
        "files": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in plugin_files.items()
        },
        "integrity_excludes": [
            "plugin-release-manifest.json",
            "plugin-release-manifest.json.sig",
            "plugin-release-signature.json",
            "publisher-ed25519.pub",
        ],
    }
    plugin_manifest_bytes = (
        json.dumps(plugin_manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    signature_metadata = {
        "schema_version": 1,
        "algorithm": "OpenSSH-Ed25519",
        "signature_namespace": MODULE.WORKBUDDY_SIGNATURE_NAMESPACE,
        "signed_file": "plugin-release-manifest.json",
        "signature": "plugin-release-manifest.json.sig",
        "public_key": "publisher-ed25519.pub",
        "public_key_fingerprint": TEST_FINGERPRINT,
    }
    with zipfile.ZipFile(workbuddy, "w") as archive:
        archive.writestr(
            "jiaotang/.codebuddy-plugin/marketplace.json",
            json.dumps(
                {
                    "name": "jiaotang",
                    "description": "test",
                    "owner": {"name": "Jiaotang"},
                    "plugins": [
                        {
                            "name": "jiaotang-workbuddy-skills",
                            "description": "test",
                            "version": semantic_version,
                            "source": "./plugins/jiaotang-workbuddy-skills",
                        }
                    ],
                }
            ),
        )
        archive.writestr("jiaotang/INSTALL.md", "test")
        prefix = "jiaotang/plugins/jiaotang-workbuddy-skills/"
        for name, content in plugin_files.items():
            archive.writestr(prefix + name, content)
        archive.writestr(
            prefix + "plugin-release-manifest.json",
            plugin_manifest_bytes,
        )
        archive.writestr(
            prefix + "plugin-release-manifest.json.sig",
            sign_manifest(plugin_manifest_bytes),
        )
        archive.writestr(
            prefix + "plugin-release-signature.json",
            json.dumps(signature_metadata),
        )
        archive.writestr(prefix + "publisher-ed25519.pub", TEST_PUBLIC_TEXT)
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


def rewrite_zip(
    source: Path,
    output: Path,
    *,
    replacements: dict[str, bytes] | None = None,
    additions: dict[str, bytes] | None = None,
) -> None:
    replacements = replacements or {}
    additions = additions or {}
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, "w") as target:
        for info in original.infolist():
            target.writestr(
                info,
                replacements.get(info.filename, original.read(info.filename)),
            )
        for name, payload in additions.items():
            target.writestr(name, payload)


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


def test_workbuddy_hotfix_accepts_four_part_version(tmp_path: Path) -> None:
    _, workbuddy = make_packages(
        tmp_path,
        tag="V1.3.1.1",
        semantic_version="1.3.1.1",
    )
    result = MODULE.validate_release_packages(
        {"workbuddy": workbuddy},
        "1.3.1.1",
    )
    assert result["targets"] == ["workbuddy"]
    assert result["skill_count"] == 48
    assert (
        result["artifacts"]["workbuddy"]["integrity"]["status"]
        == "verified"
    )
    assert (
        result["artifacts"]["workbuddy"]["integrity"][
            "mcp_configuration_mode"
        ]
        == "signed_inline_plugin_manifest"
    )


def test_workbuddy_publish_rejects_tampered_signed_file(tmp_path: Path) -> None:
    _, workbuddy = make_packages(
        tmp_path,
        tag="V1.3.1.2",
        semantic_version="1.3.1.2",
    )
    tampered = tmp_path / "tampered.zip"
    rewrite_zip(
        workbuddy,
        tampered,
        replacements={
            "jiaotang/plugins/jiaotang-workbuddy-skills/"
            ".codebuddy-plugin/plugin.json": b'{"name":"attacker","version":"1.3.1.2"}',
        },
    )

    try:
        MODULE.validate_release_packages(
            {"workbuddy": tampered},
            "1.3.1.2",
        )
    except ValueError as error:
        assert "哈希不一致" in str(error)
    else:
        raise AssertionError("tampered signed file must be rejected")


def test_workbuddy_publish_rejects_outer_fixed_installer(tmp_path: Path) -> None:
    _, workbuddy = make_packages(
        tmp_path,
        tag="V1.3.1.2",
        semantic_version="1.3.1.2",
    )
    tampered = tmp_path / "outer-installer.zip"
    rewrite_zip(
        workbuddy,
        tampered,
        additions={"jiaotang/install-jiaotang-workbuddy.cmd": b"echo unsafe"},
    )

    try:
        MODULE.validate_release_packages(
            {"workbuddy": tampered},
            "1.3.1.2",
        )
    except ValueError as error:
        assert "未经允许的外层文件" in str(error)
    else:
        raise AssertionError("outer fixed installer must be rejected")


def test_selective_stage_and_promote_workbuddy_only(tmp_path: Path) -> None:
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
        {"workbuddy": workbuddy},
        "1.3.1.1",
        "WorkBuddy hotfix",
        "abc123",
        "https://github.example/releases/V1.3.1.1",
    )
    assert staged["targets"] == ["workbuddy"]
    assert staged["release_state"] == "releasing"

    refreshed = MODULE.stage_selective(
        database,
        release_dir,
        {"workbuddy": workbuddy},
        "1.3.1.1",
        "WorkBuddy hotfix refreshed",
        "def456",
        "https://github.example/releases/V1.3.1.1-refreshed",
    )
    assert refreshed["status"] == "already-staged"
    assert refreshed["git_commit"] == "def456"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            """
            SELECT release_notes,git_commit,github_url
            FROM skill_release_stages WHERE version='1.3.1.1'
            """
        ).fetchone() == (
            "WorkBuddy hotfix refreshed",
            "def456",
            "https://github.example/releases/V1.3.1.1-refreshed",
        )

    promoted = MODULE.promote_selective(
        database,
        release_dir,
        "1.3.1.1",
    )
    assert promoted["release_state"] == "published"
    assert (
        release_dir
        / "企业全生命周期助手-V1.3.1.1-WorkBuddy.zip"
    ).is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT target FROM skill_release_artifacts"
        ).fetchall() == [("workbuddy",)]


def test_existing_release_can_add_universal_workbuddy_without_replacing_generic(
    tmp_path: Path,
) -> None:
    database = tmp_path / "portal.db"
    release_dir = tmp_path / "releases"
    generic, workbuddy = make_packages(
        tmp_path,
        tag="V1.3.1.2",
        semantic_version="1.3.1.2",
    )
    make_database(database)
    generic_sha = MODULE.sha256(generic)
    generic_target = release_dir / "企业全生命周期助手-V1.3.1.2.zip"
    release_dir.mkdir()
    generic_target.write_bytes(generic.read_bytes())
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.3.1.2",
                generic_target.name,
                str(generic_target),
                generic_sha,
                "existing release",
                "2026-07-27T00:00:00+00:00",
            ),
        )
        release_id = cursor.lastrowid
        MODULE._ensure_stage_table(connection)
        connection.execute(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            (
                release_id,
                "generic",
                generic_target.name,
                str(generic_target),
                generic_sha,
            ),
        )
        connection.commit()

    staged = MODULE.stage_artifact_addition(
        database,
        release_dir,
        workbuddy,
        "workbuddy",
        "1.3.1.2",
        "universal WorkBuddy channel",
        "abc123",
        "https://github.example/releases/workbuddy-universal-v1.3.1.2-r1",
    )
    assert staged["status"] == "staged"
    assert generic_target.read_bytes() == generic.read_bytes()

    promoted = MODULE.promote_artifact_addition(
        database,
        release_dir,
        "1.3.1.2",
        "workbuddy",
    )
    assert promoted["status"] == "published"
    assert generic_target.read_bytes() == generic.read_bytes()
    assert (
        release_dir / "企业全生命周期助手-V1.3.1.2-WorkBuddy.zip"
    ).is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version,file_name,sha256 FROM skill_releases"
        ).fetchall() == [
            (
                "1.3.1.2",
                generic_target.name,
                generic_sha,
            )
        ]
        assert connection.execute(
            """
            SELECT target FROM skill_release_artifacts
            WHERE release_id=? ORDER BY target
            """,
            (release_id,),
        ).fetchall() == [("generic",), ("workbuddy",)]
        assert connection.execute(
            """
            SELECT status FROM skill_release_artifact_stages
            WHERE version='1.3.1.2' AND target='workbuddy'
            """
        ).fetchone()[0] == "published"


def test_artifact_addition_refuses_to_replace_existing_channel(
    tmp_path: Path,
) -> None:
    database = tmp_path / "portal.db"
    release_dir = tmp_path / "releases"
    _, workbuddy = make_packages(
        tmp_path,
        tag="V1.3.1.2",
        semantic_version="1.3.1.2",
    )
    make_database(database)
    release_dir.mkdir()
    existing = release_dir / "existing-workbuddy.zip"
    existing.write_bytes(b"different")
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            """
            INSERT INTO skill_releases(
                version,file_name,file_path,sha256,release_notes,published_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                "1.3.1.2",
                "existing.zip",
                str(existing),
                MODULE.sha256(existing),
                "existing release",
                "2026-07-27T00:00:00+00:00",
            ),
        )
        MODULE._ensure_stage_table(connection)
        connection.execute(
            """
            INSERT INTO skill_release_artifacts(
                release_id,target,file_name,file_path,sha256
            ) VALUES (?,?,?,?,?)
            """,
            (
                cursor.lastrowid,
                "workbuddy",
                existing.name,
                str(existing),
                MODULE.sha256(existing),
            ),
        )
        connection.commit()

    try:
        MODULE.stage_artifact_addition(
            database,
            release_dir,
            workbuddy,
            "workbuddy",
            "1.3.1.2",
            "replacement",
            "abc123",
            "https://github.example/releases/replacement",
        )
    except RuntimeError as error:
        assert "不同内容" in str(error)
    else:
        raise AssertionError("existing channel must not be replaced")

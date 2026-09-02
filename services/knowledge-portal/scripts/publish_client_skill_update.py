#!/usr/bin/env python3
"""Publish the desktop skill projection bound to a signed release transaction."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
SERVICE_DIRECTORY = SCRIPT_DIRECTORY.parent
for entry in (SCRIPT_DIRECTORY, SERVICE_DIRECTORY):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from app.skill_update_feed import (  # noqa: E402
    CLIENT_SKILL_UPDATE_PUBLIC_KEY_SHA256,
    publish_skill_update_feed,
    validate_skill_update_archive,
)
from publish_skill_release import (  # noqa: E402
    TRUSTED_PUBLISHER_FINGERPRINT,
    sha256,
)
from release_transaction import verify_transaction_files  # noqa: E402


def publish_transaction_update(
    *,
    database: Path,
    release_directory: Path,
    archive: Path,
    version: str,
    release_notes: str,
    transaction_manifest: Path,
    transaction_signature: Path,
    publisher_public_key: Path,
) -> dict[str, object]:
    verification = verify_transaction_files(
        manifest_path=transaction_manifest,
        signature_path=transaction_signature,
        public_key_path=publisher_public_key,
        expected_fingerprint=TRUSTED_PUBLISHER_FINGERPRINT,
    )
    manifest = verification["manifest"]
    if manifest.get("version") != version:
        raise RuntimeError("客户端技能更新版本与签名发布事务不一致")
    participants = manifest.get("participants")
    client_update = (
        participants.get("client_update")
        if isinstance(participants, dict)
        else None
    )
    archive_sha256 = sha256(archive)
    if (
        not isinstance(client_update, dict)
        or client_update.get("release_version") != version
        or client_update.get("archive_sha256") != archive_sha256
        or client_update.get("public_key_sha256")
        != CLIENT_SKILL_UPDATE_PUBLIC_KEY_SHA256
        or client_update.get("required_result")
        != "public-feed-readback-and-client-verification-pass"
    ):
        raise RuntimeError("客户端技能更新包未绑定到签名发布事务")

    with sqlite3.connect(database) as connection:
        published = connection.execute(
            "SELECT id FROM skill_releases WHERE version=?",
            (version,),
        ).fetchone()
    if published is None:
        raise RuntimeError("门户通用技能正式版尚未发布，禁止开放客户端更新")

    archive_validation = validate_skill_update_archive(archive, version)
    receipt = publish_skill_update_feed(
        release_directory=release_directory,
        archive=archive,
        version=version,
        release_notes=release_notes,
    )
    return {
        "status": "published",
        "version": receipt.version,
        "archive": str(receipt.archive_path),
        "archive_sha256": archive_sha256,
        "manifest": str(receipt.manifest_path),
        "transaction_sha256": verification["manifest_sha256"],
        "validation": archive_validation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="发布签名事务已绑定的桌面客户端技能更新包。"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-notes-file", type=Path, required=True)
    parser.add_argument("--transaction-manifest", type=Path, required=True)
    parser.add_argument("--transaction-signature", type=Path, required=True)
    parser.add_argument("--publisher-public-key", type=Path, required=True)
    arguments = parser.parse_args()
    release_notes = arguments.release_notes_file.read_text(encoding="utf-8").strip()
    if not release_notes:
        parser.error("更新日志不能为空")
    print(
        json.dumps(
            publish_transaction_update(
                database=arguments.database,
                release_directory=arguments.release_dir,
                archive=arguments.archive,
                version=arguments.version,
                release_notes=release_notes,
                transaction_manifest=arguments.transaction_manifest,
                transaction_signature=arguments.transaction_signature,
                publisher_public_key=arguments.publisher_public_key,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

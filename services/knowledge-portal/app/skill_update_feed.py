"""Publish the desktop client's independent skill-bundle update feed."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path


PRODUCT_ID = "cn.gongchuang.enterprise-assistant"
VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


@dataclass(frozen=True)
class SkillUpdateFeedReceipt:
    """Paths written for one current skill-bundle release."""

    archive_path: Path
    manifest_path: Path
    version: str


def _quarantine_incomplete(temporary: Path, destination: Path) -> None:
    if not temporary.exists():
        return
    quarantine = destination.parent / ".quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    failed = quarantine / (
        f"{temporary.name}.failed-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    os.replace(temporary, failed)


def _same_file_bytes(first: Path, second: Path) -> bool:
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open("rb") as left, second.open("rb") as right:
        while True:
            left_chunk = left.read(1024 * 1024)
            right_chunk = right.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{secrets.token_hex(8)}.tmp"
    )
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, destination)
    finally:
        _quarantine_incomplete(temporary, destination)


def _atomic_json(payload: dict[str, object], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{secrets.token_hex(8)}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        _quarantine_incomplete(temporary, destination)


def publish_skill_update_feed(
    *,
    release_directory: Path,
    archive: Path,
    version: str,
    release_notes: str,
) -> SkillUpdateFeedReceipt:
    """Atomically expose a validated desktop projection through the public v1 feed.

    The archive must use the desktop updater's root-level signed-index layout;
    the independently downloadable generic suite is a different artifact and
    must never be placed behind this feed. The caller validates the projection
    before invoking this function.
    A versioned archive is immutable: publishing different bytes under an
    existing version is rejected and requires a new release version.
    """

    normalized_version = version.strip().removeprefix("V").removeprefix("v")
    if VERSION_PATTERN.fullmatch(normalized_version) is None:
        raise ValueError("技能包更新版本必须使用三段语义化版本")
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("技能包更新源必须是普通 ZIP 文件")
    if archive.suffix.casefold() != ".zip":
        raise ValueError("技能包更新源必须是 ZIP 文件")

    release_directory.mkdir(parents=True, exist_ok=True)
    archive_name = f"Gongchuang-Enterprise-Assistant-Skills-V{normalized_version}.zip"
    destination = release_directory / archive_name
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError("技能包更新目标被非普通文件占用")
        if not _same_file_bytes(destination, archive):
            raise ValueError("同一技能包版本已存在不同内容")
    else:
        _atomic_copy(archive, destination)

    manifest_path = release_directory / "latest.json"
    _atomic_json(
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "skillBundleVersion": normalized_version,
            "sourceReleaseTag": f"V{normalized_version}",
            "archiveUrl": f"./{archive_name}",
            "releaseNotes": release_notes.strip(),
        },
        manifest_path,
    )
    return SkillUpdateFeedReceipt(
        archive_path=destination,
        manifest_path=manifest_path,
        version=normalized_version,
    )

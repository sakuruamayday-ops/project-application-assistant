#!/usr/bin/env python3
"""Publish one signed universal Skills ZIP and its desktop update feed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
SERVICE_DIRECTORY = SCRIPT_DIRECTORY.parent
for entry in (SCRIPT_DIRECTORY, SERVICE_DIRECTORY):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from app.skill_update_feed import publish_skill_update_feed  # noqa: E402
from publish_skill_release import publish_selective  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="发布已签名的通用 Skills ZIP，并同步桌面客户端技能更新 feed。"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--skill-update-release-dir", type=Path, required=True)
    parser.add_argument("--generic-package", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-notes-file", type=Path, required=True)
    arguments = parser.parse_args()

    release_notes = arguments.release_notes_file.read_text(encoding="utf-8").strip()
    if not release_notes:
        parser.error("更新日志不能为空")
    result = publish_selective(
        arguments.database,
        arguments.release_dir,
        {"generic": arguments.generic_package},
        arguments.version,
        release_notes,
    )
    artifact = result["artifacts"]["generic"]
    release_id = result.get("release_id")
    if not release_id:
        raise RuntimeError("通用技能包未形成有效发布记录")
    feed = publish_skill_update_feed(
        release_directory=arguments.skill_update_release_dir,
        archive=Path(str(artifact["path"])),
        version=arguments.version,
        release_notes=release_notes,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "release_id": release_id,
                "version": feed.version,
                "targets": ["generic"],
                "skill_count": result["skill_count"],
                "skill_update_manifest": str(feed.manifest_path),
                "skill_update_archive": str(feed.archive_path),
                "workbuddy_specific_package": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

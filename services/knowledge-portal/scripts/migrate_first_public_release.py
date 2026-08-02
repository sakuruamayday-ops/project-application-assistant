#!/usr/bin/env python3
"""为首个对外版本 V1.5.0 建立公告；绝不改写历史发布。"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


VERSION = "1.5.0"
ANNOUNCEMENT_TITLE = "欢迎使用企业全生命周期助手 V1.5.0"
ANNOUNCEMENT_BODY = """## 首个对外正式版本

V1.5.0 一次安装 49 项 Skills、最小行为 Hook 和远程知识 MCP。安装会清理活动搜索路径中的焦糖旧版与重复副本，同时保留搜索路径外的可恢复快照。

## 安装后可以做什么

- 专精特新 2026 前期预评估与后期体检。
- 高企预评估、申请书撰写与成长性复算。
- 项目匹配、单项目可行性、企业分析 A/B/C 版本。
- 标准撰写、专利全流程、金税四期分析与财务核验。

回复“查看常用指令”可查看按 49 项 Skills 核对的完整示例。
"""
QUICK_PHRASES = [
    "查看常用指令",
    "帮我做2026年专精特新前期预评估",
    "帮我体检这份专精特新申请材料",
    "帮我出具企业全景分析报告",
    "帮我出具金税四期分析报告",
]


def migrate(database_path: Path, release_directory: Path) -> dict[str, object]:
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS release_announcements (
                release_id INTEGER PRIMARY KEY REFERENCES skill_releases(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                quick_phrases TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'draft',
                updated_at TEXT NOT NULL,
                published_at TEXT
            );
            CREATE TABLE IF NOT EXISTS user_release_acknowledgements (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                release_id INTEGER NOT NULL REFERENCES skill_releases(id) ON DELETE CASCADE,
                acknowledged_at TEXT NOT NULL,
                PRIMARY KEY(user_id,release_id)
            );
            """
        )
        release = connection.execute(
            "SELECT * FROM skill_releases WHERE version=? ORDER BY id DESC LIMIT 1",
            (VERSION,),
        ).fetchone()
        if release is None:
            connection.commit()
            return {
                "version": VERSION,
                "status": "awaiting-release",
                "history_rewritten": False,
            }
        existing = connection.execute(
            "SELECT title,body,quick_phrases,status FROM release_announcements WHERE release_id=?",
            (int(release["id"]),),
        ).fetchone()
        expected_phrases = json.dumps(QUICK_PHRASES, ensure_ascii=False)
        if existing is not None and tuple(existing) == (
            ANNOUNCEMENT_TITLE,
            ANNOUNCEMENT_BODY,
            expected_phrases,
            "published",
        ):
            return {
                "release_id": int(release["id"]),
                "version": VERSION,
                "package": str(release["file_path"]),
                "sha256": str(release["sha256"]),
                "announcement_status": "published",
                "database_backup": "not-required",
                "history_rewritten": False,
            }
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = database_path.with_name(
            f"{database_path.name}.before-v1.5.0-announcement-{timestamp}"
        )
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO release_announcements(
                release_id,title,body,quick_phrases,status,updated_at,published_at
            ) VALUES (?,?,?,?, 'published', ?, ?)
            ON CONFLICT(release_id) DO UPDATE SET
                title=excluded.title,
                body=excluded.body,
                quick_phrases=excluded.quick_phrases,
                status='published',
                updated_at=excluded.updated_at,
                published_at=COALESCE(release_announcements.published_at,excluded.published_at)
            """,
            (
                int(release["id"]),
                ANNOUNCEMENT_TITLE,
                ANNOUNCEMENT_BODY,
                expected_phrases,
                now,
                now,
            ),
        )
        connection.commit()
        return {
            "release_id": int(release["id"]),
            "version": VERSION,
            "package": str(release["file_path"]),
            "sha256": str(release["sha256"]),
            "announcement_status": "published",
            "database_backup": str(backup_path),
            "history_rewritten": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="发布V1.5.0首个对外版本公告")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(migrate(arguments.database, arguments.release_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

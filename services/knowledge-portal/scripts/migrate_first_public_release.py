#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path


VERSION = "1.0"
ANNOUNCEMENT_TITLE = "欢迎使用企业全生命周期助手 V1.0"
ANNOUNCEMENT_BODY = """## 这是一套什么工具

企业全生命周期助手把团队知识库、专业 Skills、企业与政策分析、专利与财税能力连接到你正在使用的 Agent 中，团队成员无需共享本地文件。

## 首次使用只需四步

1. 下载 V1.0 技能包并拖入你正在使用的 Agent。
2. 在网站生成个人 API 与 MCP 接入配置，复制到 Agent 的安全凭据或连接器配置中。
3. 在对话框输入“请检查企业全生命周期助手是否安装完整，并启动首次配置向导”。
4. 进入网站“API 与用户”，按需点击企查查扫码注册，再把企查查首页生成的 MCP 配置复制给对应 Agent；专利业务人员注册 BigQuery，并连接全球专利数据库。

## 你可以用它做什么

- 分析企业可申报项目、材料缺口和未来规划。
- 核验现行政策、申报条件、政策版本和替代关系。
- 完成专精特新、小巨人、专利、财税和申报材料检查。
- 调用团队云端知识库，并在结果中保留资料来源。
"""
QUICK_PHRASES = [
    "帮我出具这家企业全景分析报告",
    "帮我出具这家企业金税四期分析报告",
    "帮我体检下这份申报材料",
    "根据现有资料和小巨人的要求帮我规划下这家企业的10个专利方向",
    "帮我排查下这么做的法律风险",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rewrite_package(source: Path, target: Path) -> None:
    temporary = target.with_suffix(".tmp.zip")
    with zipfile.ZipFile(source) as input_archive, zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED
    ) as output_archive:
        manifest_updated = False
        for info in input_archive.infolist():
            payload = input_archive.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(payload.decode("utf-8"))
                manifest["version"] = VERSION
                payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                manifest_updated = True
            output_archive.writestr(info, payload)
        if not manifest_updated:
            raise RuntimeError("发布包缺少根目录 manifest.json")
    temporary.replace(target)


def migrate(database_path: Path, release_directory: Path) -> dict[str, object]:
    release_directory.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        existing = connection.execute(
            "SELECT * FROM skill_releases WHERE version=? ORDER BY id DESC LIMIT 1", (VERSION,)
        ).fetchone()
        if existing is not None:
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
                    updated_at=excluded.updated_at
                """,
                (
                    existing["id"], ANNOUNCEMENT_TITLE, ANNOUNCEMENT_BODY,
                    json.dumps(QUICK_PHRASES, ensure_ascii=False), now, now,
                ),
            )
            connection.commit()
            announcement = connection.execute(
                "SELECT status FROM release_announcements WHERE release_id=?", (existing["id"],)
            ).fetchone()
            return {
                "release_id": int(existing["id"]),
                "version": VERSION,
                "package": str(existing["file_path"]),
                "sha256": str(existing["sha256"]),
                "database_backup": "not-required",
                "announcement_status": str(announcement[0]) if announcement else "missing",
            }
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = database_path.with_name(f"{database_path.name}.before-v1-{timestamp}")
    shutil.copy2(database_path, backup_path)
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
            "SELECT * FROM skill_releases ORDER BY published_at DESC,id DESC LIMIT 1"
        ).fetchone()
        if release is None:
            raise RuntimeError("数据库中没有可迁移的 Skills 发布记录")
        source_path = Path(str(release["file_path"]))
        if not source_path.is_file():
            raise RuntimeError(f"Skills 发布包不存在：{source_path}")
        target_path = release_directory / "企业全生命周期助手-V1.0.zip"
        rewrite_package(source_path, target_path)
        release_notes = str(release["release_notes"] or "")
        release_notes = release_notes.replace("2.2.0", "V1.0").replace("v2.2.0", "V1.0")
        connection.execute(
            """
            UPDATE skill_releases SET version=?,file_name=?,file_path=?,sha256=?,release_notes=?
            WHERE id=?
            """,
            (VERSION, target_path.name, str(target_path), sha256(target_path), release_notes, release["id"]),
        )
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO release_announcements(release_id,title,body,quick_phrases,status,updated_at)
            VALUES (?,?,?,?, 'draft', ?)
            ON CONFLICT(release_id) DO NOTHING
            """,
            (
                release["id"], ANNOUNCEMENT_TITLE, ANNOUNCEMENT_BODY,
                json.dumps(QUICK_PHRASES, ensure_ascii=False), now,
            ),
        )
        connection.commit()
        return {
            "release_id": int(release["id"]),
            "version": VERSION,
            "package": str(target_path),
            "sha256": sha256(target_path),
            "database_backup": str(backup_path),
            "announcement_status": "draft",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="将首个正式团队 Skills 发布记录迁移为 V1.0")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(migrate(arguments.database, arguments.release_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

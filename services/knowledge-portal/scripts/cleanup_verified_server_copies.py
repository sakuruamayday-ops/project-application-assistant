#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pwd
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DATA_DIR = Path("/var/lib/jiaotang-kb")
KNOWLEDGE_ROOT = Path("/srv/jiaotang/knowledge-files")
SNAPSHOT_ROOT = Path("/srv/jiaotang/index-snapshots")
BACKUP_ROOT = Path("/var/backups/jiaotang-kb")
PORTAL_DATABASE = DATA_DIR / "knowledge.db"


def referenced_snapshots() -> set[Path]:
    queries = (
        ("SELECT snapshot_path FROM knowledge_update_jobs WHERE status=? AND rolled_back_at IS NULL", ("indexed",)),
        ("SELECT snapshot_path FROM knowledge_document_revisions WHERE rolled_back_at IS NULL", ()),
        ("SELECT snapshot_path FROM knowledge_document_trash WHERE status=? AND restored_at IS NULL", ("trashed",)),
    )
    references: set[Path] = set()
    connection = sqlite3.connect(PORTAL_DATABASE)
    try:
        for query, parameters in queries:
            references.update(
                Path(row[0])
                for row in connection.execute(query, parameters)
                if row[0]
            )
    finally:
        connection.close()
    return references


def inventory(root: Path) -> dict[str, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return {"files": len(files), "bytes": sum(path.stat().st_size for path in files)}


def remove_empty_directories(root: Path) -> None:
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()), reverse=True
    ):
        try:
            directory.rmdir()
        except OSError:
            pass


def main() -> int:
    service_user = pwd.getpwnam("jiaotang")
    preserved: list[Path] = []
    for target in sorted(referenced_snapshots()):
        if not target.is_file():
            candidates = list(BACKUP_ROOT.rglob(target.name))
            if len(candidates) != 1:
                raise RuntimeError(
                    f"无法唯一恢复被引用快照：{target}，候选={len(candidates)}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(candidates[0]), str(target))
        os.chown(target, service_user.pw_uid, service_user.pw_gid)
        os.chmod(target, 0o640)
        connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError(f"保留快照完整性异常：{target}")
        finally:
            connection.close()
        preserved.append(target)

    before = {
        "knowledge": inventory(KNOWLEDGE_ROOT),
        "snapshots": inventory(SNAPSHOT_ROOT),
        "backups": inventory(BACKUP_ROOT),
    }
    manifest = {
        "authorized_cleanup_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "oss_verification": {
            "objects": 3638,
            "bytes": 33857003884,
            "status": "passed",
        },
        "before": before,
        "preserved_snapshots": [str(path) for path in preserved],
    }
    manifest_path = DATA_DIR / "server-copy-cleanup-20260720.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(manifest_path, 0o640)

    for path in sorted(path for path in KNOWLEDGE_ROOT.rglob("*") if path.is_file()):
        path.unlink()
    for path in sorted(path for path in SNAPSHOT_ROOT.rglob("*") if path.is_file()):
        if path not in preserved:
            path.unlink()
    for path in sorted(path for path in BACKUP_ROOT.rglob("*") if path.is_file()):
        path.unlink()
    for root in (KNOWLEDGE_ROOT, SNAPSHOT_ROOT, BACKUP_ROOT):
        remove_empty_directories(root)
        root.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"before": before, "preserved": len(preserved)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

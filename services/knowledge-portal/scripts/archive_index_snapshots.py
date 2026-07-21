#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="将超出热保留窗口的索引快照移入归档区")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--portal-database", type=Path)
    parser.add_argument("--keep-latest", type=int, default=12)
    args = parser.parse_args()
    args.archive_dir.mkdir(parents=True, exist_ok=True)
    referenced: set[Path] = set()
    if args.portal_database and args.portal_database.is_file():
        connection = sqlite3.connect(args.portal_database)
        try:
            for query in (
                "SELECT snapshot_path FROM knowledge_update_jobs WHERE status='indexed' AND rolled_back_at IS NULL",
                "SELECT snapshot_path FROM knowledge_document_revisions WHERE rolled_back_at IS NULL",
                "SELECT snapshot_path FROM knowledge_document_trash WHERE status='trashed' AND restored_at IS NULL",
            ):
                referenced.update(
                    Path(row[0]) for row in connection.execute(query) if row[0]
                )
        finally:
            connection.close()
    candidates = sorted(
        (path for path in args.snapshot_dir.glob("*.sqlite3") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    archived = []
    for path in candidates[max(args.keep_latest, 1) :]:
        if path in referenced:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        target = args.archive_dir / modified.strftime("%Y/%m") / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f"{target.stem}-{int(path.stat().st_mtime)}{target.suffix}")
        shutil.move(str(path), target)
        archived.append(str(target))
    payload = {
        "status": "正常",
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "hot_snapshots": min(len(candidates), max(args.keep_latest, 1)),
        "archived_snapshots": len(archived),
        "policy": "最近12份保留在热回滚区，其余按年月移入服务器归档区，不永久删除",
    }
    args.status_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.status_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, args.status_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

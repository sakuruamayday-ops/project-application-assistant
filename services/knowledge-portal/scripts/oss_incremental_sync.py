#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import oss2


EXCLUDED_NAMES = {".DS_Store"}
EXCLUDED_SUFFIXES = {".tmp", ".part", ".lock", ".wal", ".shm"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def eligible_file(path: Path) -> bool:
    return (
        path.is_file()
        and path.name not in EXCLUDED_NAMES
        and not path.name.startswith("._")
        and path.suffix.lower() not in EXCLUDED_SUFFIXES
    )


def open_state(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS synced_files (
            source_group TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            object_key TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            etag TEXT,
            synced_at TEXT NOT NULL,
            PRIMARY KEY(source_group, relative_path)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            uploaded_files INTEGER NOT NULL DEFAULT 0,
            skipped_files INTEGER NOT NULL DEFAULT 0,
            uploaded_bytes INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        )
        """
    )
    connection.commit()
    return connection


def consistent_source(path: Path, staging_dir: Path) -> Path:
    if path.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        return path
    target = staging_dir / path.name
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"SQLite 快照完整性检查失败：{path.name}: {integrity}")
    return target


def upload_file(bucket: oss2.Bucket, source: Path, object_key: str, digest: str) -> str:
    headers = {
        "x-oss-meta-sha256": digest,
        "x-oss-meta-source-size": str(source.stat().st_size),
    }
    if source.stat().st_size >= 64 * 1024 * 1024:
        resumable_root = Path(
            os.environ.get("JIAOTANG_OSS_RESUMABLE_DIR", "/var/lib/jiaotang-kb/oss-resumable")
        )
        resumable_root.mkdir(parents=True, exist_ok=True)
        result = oss2.resumable_upload(
            bucket,
            object_key,
            str(source),
            store=oss2.ResumableStore(root=str(resumable_root)),
            multipart_threshold=64 * 1024 * 1024,
            part_size=16 * 1024 * 1024,
            headers=headers,
            num_threads=4,
        )
    else:
        result = bucket.put_object_from_file(object_key, str(source), headers=headers)
    return str(getattr(result, "etag", "") or "")


def copy_existing_object(
    bucket: oss2.Bucket,
    source_key: str,
    target_key: str,
) -> str | None:
    try:
        result = bucket.copy_object(bucket.bucket_name, source_key, target_key)
    except oss2.exceptions.OssError:
        return None
    return str(getattr(result, "etag", "") or "")


def sync_group(
    connection: sqlite3.Connection,
    bucket: oss2.Bucket,
    source_group: str,
    root: Path,
    object_prefix: str,
    staging_dir: Path,
    snapshot_sqlite: bool = True,
) -> tuple[int, int, int]:
    uploaded_files = 0
    skipped_files = 0
    uploaded_bytes = 0
    seen_relatives: set[str] = set()
    for path in sorted(item for item in root.rglob("*") if eligible_file(item)):
        relative = path.relative_to(root).as_posix()
        seen_relatives.add(relative)
        stat = path.stat()
        previous = connection.execute(
            "SELECT * FROM synced_files WHERE source_group = ? AND relative_path = ?",
            (source_group, relative),
        ).fetchone()
        if previous and previous["size"] == stat.st_size and previous["mtime_ns"] == stat.st_mtime_ns:
            skipped_files += 1
            continue
        source = consistent_source(path, staging_dir) if snapshot_sqlite else path
        digest = sha256_file(source)
        object_key = f"{object_prefix.rstrip('/')}/{relative}"
        if previous and previous["sha256"] == digest and previous["object_key"] == object_key:
            connection.execute(
                "UPDATE synced_files SET size = ?, mtime_ns = ? WHERE source_group = ? AND relative_path = ?",
                (stat.st_size, stat.st_mtime_ns, source_group, relative),
            )
            skipped_files += 1
            continue
        reusable = connection.execute(
            """
            SELECT object_key FROM synced_files
            WHERE sha256 = ? AND size = ? AND object_key <> ?
            ORDER BY synced_at DESC LIMIT 1
            """,
            (digest, source.stat().st_size, object_key),
        ).fetchone()
        transferred_bytes = source.stat().st_size
        etag = None
        if reusable:
            etag = copy_existing_object(bucket, reusable["object_key"], object_key)
            if etag is not None:
                transferred_bytes = 0
        if etag is None:
            etag = upload_file(bucket, source, object_key, digest)
        connection.execute(
            """
            INSERT INTO synced_files(
                source_group,relative_path,object_key,size,mtime_ns,sha256,etag,synced_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(source_group,relative_path) DO UPDATE SET
                object_key=excluded.object_key,size=excluded.size,mtime_ns=excluded.mtime_ns,
                sha256=excluded.sha256,etag=excluded.etag,synced_at=excluded.synced_at
            """,
            (
                source_group,
                relative,
                object_key,
                stat.st_size,
                stat.st_mtime_ns,
                digest,
                etag,
                isoformat(utc_now()),
            ),
        )
        connection.commit()
        uploaded_files += 1
        uploaded_bytes += transferred_bytes
    stale_rows = connection.execute(
        "SELECT relative_path FROM synced_files WHERE source_group = ?",
        (source_group,),
    ).fetchall()
    for row in stale_rows:
        if row["relative_path"] not in seen_relatives:
            connection.execute(
                "DELETE FROM synced_files WHERE source_group = ? AND relative_path = ?",
                (source_group, row["relative_path"]),
            )
    connection.commit()
    return uploaded_files, skipped_files, uploaded_bytes


def write_status(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


def main() -> int:
    raise SystemExit(
        "旧式相对路径OSS同步已永久停用；请使用"
        "sync_archived_knowledge_to_production.sh执行SHA-256内容寻址发布"
    )

    # 以下参数与实现仅保留用于读取历史状态和测试底层同步函数，不再作为生产入口。
    parser = argparse.ArgumentParser(description="增量同步生产知识库和索引到阿里云 OSS")
    parser.add_argument("--knowledge-dir", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--state-database", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--snapshot-index", action="store_true")
    args = parser.parse_args()

    endpoint = os.environ["JIAOTANG_OSS_ENDPOINT"].rstrip("/")
    bucket_name = os.environ["JIAOTANG_OSS_BUCKET"]
    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    auth = oss2.Auth(os.environ["JIAOTANG_OSS_ACCESS_KEY_ID"], os.environ["JIAOTANG_OSS_ACCESS_KEY_SECRET"])
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    started = utc_now()
    with closing(open_state(args.state_database)) as connection:
        cursor = connection.execute(
            "INSERT INTO sync_runs(started_at,status) VALUES(?, 'running')",
            (isoformat(started),),
        )
        run_id = int(cursor.lastrowid)
        connection.commit()
        try:
            with tempfile.TemporaryDirectory(prefix="jiaotang-oss-sync-") as temporary:
                staging = Path(temporary)
                knowledge_stats = sync_group(
                    connection,
                    bucket,
                    "knowledge",
                    args.knowledge_dir,
                    f"{prefix}/knowledge/current",
                    staging,
                )
                index_stats = sync_group(
                    connection,
                    bucket,
                    "index",
                    args.index_dir,
                    f"{prefix}/index/current",
                    staging,
                )
                group_stats = [knowledge_stats, index_stats]
                if args.snapshot_dir and args.snapshot_dir.is_dir():
                    group_stats.append(
                        sync_group(
                            connection,
                            bucket,
                            "rollback-snapshots",
                            args.snapshot_dir,
                            f"{prefix}/index/rollback-snapshots",
                            staging,
                            snapshot_sqlite=False,
                        )
                    )
                if args.backup_dir and args.backup_dir.is_dir():
                    group_stats.append(
                        sync_group(
                            connection,
                            bucket,
                            "server-backups",
                            args.backup_dir,
                            f"{prefix}/server-backups",
                            staging,
                            snapshot_sqlite=False,
                        )
                    )
                uploaded = sum(item[0] for item in group_stats)
                skipped = sum(item[1] for item in group_stats)
                uploaded_bytes = sum(item[2] for item in group_stats)
                snapshot_prefix = None
                if args.snapshot_index:
                    snapshot_stamp = started.strftime("%Y/%m/%d/%Y%m%dT%H%M%SZ")
                    snapshot_prefix = f"{prefix}/index/snapshots/{snapshot_stamp}"
                    for path in sorted(item for item in args.index_dir.rglob("*") if eligible_file(item)):
                        relative = path.relative_to(args.index_dir).as_posix()
                        source = consistent_source(path, staging)
                        digest = sha256_file(source)
                        upload_file(bucket, source, f"{snapshot_prefix}/{relative}", digest)
                completed = utc_now()
                connection.execute(
                    """
                    UPDATE sync_runs SET completed_at=?,status='completed',uploaded_files=?,
                    skipped_files=?,uploaded_bytes=? WHERE id=?
                    """,
                    (isoformat(completed), uploaded, skipped, uploaded_bytes, run_id),
                )
                connection.commit()
                write_status(
                    args.status_file,
                    {
                        "status": "正常",
                        "started_at": isoformat(started),
                        "completed_at": isoformat(completed),
                        "bucket": bucket_name,
                        "uploaded_files": uploaded,
                        "skipped_files": skipped,
                        "uploaded_bytes": uploaded_bytes,
                        "index_snapshot": snapshot_prefix,
                    },
                )
        except Exception as exc:
            connection.execute(
                "UPDATE sync_runs SET completed_at=?,status='failed',error_message=? WHERE id=?",
                (isoformat(utc_now()), str(exc)[:1000], run_id),
            )
            connection.commit()
            write_status(
                args.status_file,
                {
                    "status": "异常",
                    "started_at": isoformat(started),
                    "completed_at": isoformat(utc_now()),
                    "error": str(exc)[:500],
                },
            )
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

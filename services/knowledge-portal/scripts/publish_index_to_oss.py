from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import oss2


PRODUCTION_FILES = (
    "README.md",
    "manifest.jsonl",
    "knowledge_inventory.sqlite3",
    "knowledge_content.sqlite3",
    "policy_versions.sqlite3",
    "summary.json",
    "extraction_summary.json",
    "policy_version_summary.json",
    "extraction_report.csv",
    "upload_allowlist.csv",
    "upload_allowlist_summary.json",
    "OCR资料抽检报告_2026-07-21.md",
    "OCR资料抽检报告_2026-07-21.json",
)
FULL_INDEX_NAME = "knowledge_content.sqlite3"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sqlite(path: Path) -> None:
    if path.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        return
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        connection.close()
    if result != "ok":
        raise RuntimeError(f"SQLite完整性检查失败：{path.name}: {result}")


def checkpoint_sqlite(path: Path) -> None:
    if path.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        return
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        connection.close()


def full_index_due(
    policy: str,
    remote: object | None,
    *,
    max_age_days: int,
    now: datetime,
) -> bool:
    if policy == "always" or remote is None:
        return True
    if policy == "skip":
        return False
    last_modified = getattr(remote, "last_modified", None)
    if not last_modified:
        return True
    remote_time = datetime.fromtimestamp(float(last_modified), timezone.utc)
    return now - remote_time >= timedelta(days=max(max_age_days, 1))


def main() -> None:
    parser = argparse.ArgumentParser(description="增量发布生产索引文件到OSS")
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--snapshot-current", action="store_true")
    parser.add_argument(
        "--index-policy",
        choices=("skip", "weekly", "always"),
        default="weekly",
        help="完整全文索引发布策略；默认每7天上传一次，日常由服务器差异块同步接管",
    )
    parser.add_argument("--full-index-max-age-days", type=int, default=7)
    parser.add_argument(
        "--prevalidated",
        action="store_true",
        help="调用方已在同一流水线完成SQLite完整性校验时跳过重复校验",
    )
    args = parser.parse_args()
    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    auth = oss2.Auth(
        os.environ["JIAOTANG_OSS_ACCESS_KEY_ID"],
        os.environ["JIAOTANG_OSS_ACCESS_KEY_SECRET"],
    )
    bucket = oss2.Bucket(
        auth,
        os.environ["JIAOTANG_OSS_ENDPOINT"].rstrip("/"),
        os.environ["JIAOTANG_OSS_BUCKET"],
    )
    uploaded = skipped = deferred = 0
    now = datetime.now(timezone.utc)
    snapshot_stamp = now.strftime("%Y/%m/%d/%Y%m%dT%H%M%SZ")
    for name in PRODUCTION_FILES:
        path = args.index_dir / name
        if not path.is_file():
            continue
        object_key = f"{prefix}/index/current/{name}"
        remote = None
        try:
            remote = bucket.head_object(object_key)
        except oss2.exceptions.NoSuchKey:
            pass
        if name == FULL_INDEX_NAME and not full_index_due(
            args.index_policy,
            remote,
            max_age_days=args.full_index_max_age_days,
            now=now,
        ):
            deferred += 1
            continue
        checkpoint_sqlite(path)
        if not args.prevalidated:
            verify_sqlite(path)
        digest = sha256_file(path)
        if remote is not None:
            remote_digest = str(remote.headers.get("x-oss-meta-sha256", ""))
            if remote_digest == digest and int(remote.content_length) == path.stat().st_size:
                skipped += 1
                continue
            if args.snapshot_current and name == "knowledge_content.sqlite3":
                bucket.copy_object(
                    bucket.bucket_name,
                    object_key,
                    f"{prefix}/index/snapshots/{snapshot_stamp}/{name}",
                )
        headers = {"x-oss-meta-sha256": digest, "x-oss-meta-source-size": str(path.stat().st_size)}
        if path.stat().st_size >= 64 * 1024 * 1024:
            checkpoint_store = oss2.ResumableStore(
                root=os.environ.get("JIAOTANG_OSS_CHECKPOINT_DIR", "/tmp/jiaotang-oss-checkpoints"),
                dir=digest,
            )
            oss2.resumable_upload(
                bucket,
                object_key,
                str(path),
                store=checkpoint_store,
                multipart_threshold=64 * 1024 * 1024,
                part_size=16 * 1024 * 1024,
                headers=headers,
                num_threads=4,
            )
        else:
            bucket.put_object_from_file(object_key, str(path), headers=headers)
        if sha256_file(path) != digest:
            raise RuntimeError(f"发布期间索引发生变化，请在写入停止后重试：{name}")
        remote = bucket.head_object(object_key)
        if (
            str(remote.headers.get("x-oss-meta-sha256", "")) != digest
            or int(remote.content_length) != path.stat().st_size
        ):
            raise RuntimeError(f"OSS发布后校验失败：{name}")
        uploaded += 1
    print(
        f"生产索引发布完成：上传{uploaded}，内容相同跳过{skipped}，"
        f"完整索引按策略延后{deferred}"
    )


if __name__ == "__main__":
    main()

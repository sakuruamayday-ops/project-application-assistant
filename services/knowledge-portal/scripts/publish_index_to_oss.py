from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
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


def main() -> None:
    parser = argparse.ArgumentParser(description="增量发布生产索引文件到OSS")
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--snapshot-current", action="store_true")
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
    uploaded = skipped = 0
    snapshot_stamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%Y%m%dT%H%M%SZ")
    for name in PRODUCTION_FILES:
        path = args.index_dir / name
        if not path.is_file():
            continue
        verify_sqlite(path)
        digest = sha256_file(path)
        object_key = f"{prefix}/index/current/{name}"
        try:
            remote = bucket.head_object(object_key)
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
        except oss2.exceptions.NoSuchKey:
            pass
        headers = {"x-oss-meta-sha256": digest, "x-oss-meta-source-size": str(path.stat().st_size)}
        if path.stat().st_size >= 64 * 1024 * 1024:
            oss2.resumable_upload(
                bucket,
                object_key,
                str(path),
                multipart_threshold=64 * 1024 * 1024,
                part_size=16 * 1024 * 1024,
                headers=headers,
                num_threads=4,
            )
        else:
            bucket.put_object_from_file(object_key, str(path), headers=headers)
        uploaded += 1
    print(f"生产索引发布完成：上传{uploaded}，跳过{skipped}")


if __name__ == "__main__":
    main()

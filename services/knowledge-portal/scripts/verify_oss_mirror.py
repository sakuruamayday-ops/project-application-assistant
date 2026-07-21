#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import oss2


def parse_group(value: str) -> tuple[str, Path]:
    name, separator, root = value.partition("=")
    if not separator or not name or not root:
        raise argparse.ArgumentTypeError("分组格式须为 name=/absolute/path")
    return name, Path(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="逐对象核验 OSS 镜像与本地同步状态")
    parser.add_argument("--state-database", type=Path, required=True)
    parser.add_argument("--group", action="append", type=parse_group, required=True)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    roots = dict(args.group)
    with closing(sqlite3.connect(args.state_database)) as connection:
        connection.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in roots)
        rows = connection.execute(
            f"SELECT * FROM synced_files WHERE source_group IN ({placeholders}) ORDER BY source_group, relative_path",
            tuple(roots),
        ).fetchall()
    if not rows:
        raise SystemExit("同步状态中没有待核验对象")
    auth = oss2.Auth(
        os.environ["JIAOTANG_OSS_ACCESS_KEY_ID"],
        os.environ["JIAOTANG_OSS_ACCESS_KEY_SECRET"],
    )
    bucket = oss2.Bucket(
        auth,
        os.environ["JIAOTANG_OSS_ENDPOINT"].rstrip("/"),
        os.environ["JIAOTANG_OSS_BUCKET"],
    )

    def verify(row: sqlite3.Row) -> str | None:
        local_path = roots[str(row["source_group"])] / str(row["relative_path"])
        if not local_path.is_file():
            return f"本地缺失：{local_path}"
        stat = local_path.stat()
        if stat.st_size != int(row["size"]) or stat.st_mtime_ns != int(row["mtime_ns"]):
            return f"本地已变化：{local_path}"
        try:
            remote = bucket.head_object(str(row["object_key"]))
        except Exception as error:
            return f"OSS 读取失败：{row['object_key']}：{error}"
        if int(remote.content_length) != int(row["size"]):
            return f"OSS 大小不一致：{row['object_key']}"
        remote_sha256 = str(remote.headers.get("x-oss-meta-sha256", ""))
        if remote_sha256 != str(row["sha256"]):
            return f"OSS 哈希不一致：{row['object_key']}"
        return None

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 24))) as executor:
        errors = [error for error in executor.map(verify, rows) if error]
    if errors:
        for error in errors[:30]:
            print(error)
        raise SystemExit(f"核验失败：{len(errors)} 个对象异常")
    counts: dict[str, int] = {}
    total_bytes = 0
    for row in rows:
        group = str(row["source_group"])
        counts[group] = counts.get(group, 0) + 1
        total_bytes += int(row["size"])
    print(f"OSS 镜像核验通过：{len(rows)} 个对象，{total_bytes} 字节，分组={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

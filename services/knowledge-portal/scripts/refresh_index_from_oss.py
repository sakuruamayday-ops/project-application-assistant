#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import os
import pwd
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import oss2


REQUIRED_STRUCTURED_TABLES = {
    "list_coverage_matrix": 384,
    "list_entity_reconciliation": 1,
    "national_small_giant_master": 1,
    "three_first_project_awards": 1,
    "three_first_status_timeline": 1,
    "enterprise_product_graph_nodes": 1,
    "enterprise_product_graph_edges": 1,
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def structured_tables_valid(connection: sqlite3.Connection) -> bool:
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if not set(REQUIRED_STRUCTURED_TABLES) <= existing:
        return False
    return all(
        connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] >= minimum
        for table, minimum in REQUIRED_STRUCTURED_TABLES.items()
    )


def valid_index(path: Path, *, quick_check: bool = True) -> bool:
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if quick_check and connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                return False
            return structured_tables_valid(connection)
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def write_status(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


def main() -> int:
    index_dir = Path(os.environ.get("JIAOTANG_INDEX_DIR", "/srv/jiaotang/knowledge-index"))
    local_index = index_dir / "knowledge_content.sqlite3"
    status_path = Path(
        os.environ.get(
            "JIAOTANG_OSS_INDEX_CACHE_STATUS",
            "/var/lib/jiaotang-kb/oss-index-cache-status.json",
        )
    )
    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    object_key = f"{prefix}/index/current/knowledge_content.sqlite3"
    service_user = os.environ.get("JIAOTANG_SERVICE_USER", "jiaotang")
    service_account = pwd.getpwnam(service_user)
    auth = oss2.Auth(
        os.environ["JIAOTANG_OSS_ACCESS_KEY_ID"],
        os.environ["JIAOTANG_OSS_ACCESS_KEY_SECRET"],
    )
    bucket = oss2.Bucket(
        auth,
        os.environ["JIAOTANG_OSS_ENDPOINT"].rstrip("/"),
        os.environ["JIAOTANG_OSS_BUCKET"],
    )
    try:
        remote = bucket.head_object(object_key)
        remote_sha256 = str(remote.headers.get("x-oss-meta-sha256", ""))
        previous = {}
        if status_path.is_file():
            try:
                previous = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
        local_size_matches = (
            local_index.is_file() and local_index.stat().st_size == remote.content_length
        )
        remote_identity_matches = previous.get("remote_etag") == remote.etag
        if local_size_matches and not remote_identity_matches and remote_sha256:
            remote_identity_matches = hmac.compare_digest(
                sha256_file(local_index), remote_sha256
            )
        unchanged = local_size_matches and remote_identity_matches
        if unchanged and valid_index(local_index, quick_check=False):
            cache_updated_at = datetime.fromtimestamp(
                local_index.stat().st_mtime, timezone.utc
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            write_status(
                status_path,
                {
                    "status": "正常",
                    "mode": "OSS 权威源 + 服务器只读查询缓存",
                    "checked_at": utc_timestamp(),
                    "cache_updated_at": cache_updated_at,
                    "source": "OSS",
                    "object_key": object_key,
                    "remote_etag": remote.etag,
                    "cache_updated": False,
                },
            )
            return 0
        index_dir.mkdir(parents=True, exist_ok=True)
        temporary = local_index.with_suffix(".oss-download.tmp")
        bucket.get_object_to_file(object_key, str(temporary))
        if remote_sha256 and sha256_file(temporary) != remote_sha256:
            raise RuntimeError("OSS 索引 SHA-256 校验失败")
        if not valid_index(temporary):
            raise RuntimeError("OSS 索引完整性或结构化专表校验失败")
        os.chmod(temporary, 0o640)
        os.chown(temporary, service_account.pw_uid, service_account.pw_gid)
        os.replace(temporary, local_index)
        cache_updated_at = utc_timestamp()
        write_status(
            status_path,
            {
                "status": "正常",
                "mode": "OSS 权威源 + 服务器只读查询缓存",
                "checked_at": cache_updated_at,
                "cache_updated_at": cache_updated_at,
                "source": "OSS",
                "object_key": object_key,
                "remote_etag": remote.etag,
                "cache_updated": True,
            },
        )
        return 0
    except Exception as error:
        if local_index.is_file():
            write_status(
                status_path,
                {
                    "status": "降级",
                    "mode": "最近一次本地只读缓存",
                    "checked_at": utc_timestamp(),
                    "cache_updated_at": datetime.fromtimestamp(
                        local_index.stat().st_mtime, timezone.utc
                    ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "source": "OSS 暂不可用",
                    "error": str(error)[:500],
                },
            )
            return 0
        raise


if __name__ == "__main__":
    raise SystemExit(main())

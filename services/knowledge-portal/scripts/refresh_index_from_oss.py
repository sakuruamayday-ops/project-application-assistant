#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import functools
import hashlib
import hmac
import json
import os
import pwd
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import oss2

try:
    import fcntl
except ImportError:  # pragma: no cover - production refresh runs on Linux
    fcntl = None  # type: ignore[assignment]

try:
    from scripts.oss_auth import build_bucket
    from scripts.publish_index_to_oss import (
        MANIFEST_SCHEMA,
        POINTER_SCHEMA,
        PRODUCTION_FILES,
        canonical_json,
        sha256_bytes,
        sha256_crc64_file,
        sha256_file,
        signing_key_id,
    )
    from scripts.release_progress import TransferProgress, emit_progress
    from scripts.release_retention import prune_release_generations
except ImportError:  # direct script execution
    from oss_auth import build_bucket
    from publish_index_to_oss import (
        MANIFEST_SCHEMA,
        POINTER_SCHEMA,
        PRODUCTION_FILES,
        canonical_json,
        sha256_bytes,
        sha256_crc64_file,
        sha256_file,
        signing_key_id,
    )
    from release_progress import TransferProgress, emit_progress
    from release_retention import prune_release_generations


REQUIRED_STRUCTURED_TABLES = {
    "list_coverage_matrix": 384,
    "list_entity_reconciliation": 1,
    "national_small_giant_master": 1,
    "national_small_giant_batch_coverage": 7,
    "national_small_giant_platform_year_claims": 1,
    "enterprise_recognition_events": 1,
    "enterprise_lifecycle_source_audits": 1,
    "enterprise_regional_coverage_audits": 3,
    "three_first_project_awards": 1,
    "three_first_status_timeline": 1,
    "three_first_guidance_directory_entries": 1,
    "three_first_guidance_directory_diffs": 1,
    "three_first_award_directory_links": 1,
    "enterprise_product_graph_nodes": 1,
    "enterprise_product_graph_edges": 1,
}
RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")


class IndexRefreshBusy(RuntimeError):
    """A second refresh attempted to enter the shared index transaction."""


def index_refresh_lock_path() -> Path:
    configured = os.environ.get("JIAOTANG_OSS_INDEX_REFRESH_LOCK", "").strip()
    if configured:
        return Path(configured)
    status_path = Path(
        os.environ.get(
            "JIAOTANG_OSS_INDEX_CACHE_STATUS",
            "/var/lib/jiaotang-kb/oss-index-cache-status.json",
        )
    )
    return status_path.with_name("index-refresh.lock")


def acquire_index_refresh_lock(path: Path, *, wait: bool):
    if fcntl is None:
        raise RuntimeError("当前平台不支持索引刷新进程互斥锁")
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+", encoding="utf-8")
    operation = fcntl.LOCK_EX
    if not wait:
        operation |= fcntl.LOCK_NB
    try:
        fcntl.flock(stream.fileno(), operation)
    except BlockingIOError as error:
        stream.close()
        raise IndexRefreshBusy("已有索引刷新事务持有互斥锁") from error
    stream.seek(0)
    stream.truncate()
    stream.write(
        json.dumps(
            {"pid": os.getpid(), "acquired_at": utc_timestamp()},
            ensure_ascii=False,
        )
        + "\n"
    )
    stream.flush()
    os.fsync(stream.fileno())
    return stream


def release_index_refresh_lock(stream) -> None:
    if fcntl is not None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    stream.close()


def serialized_index_refresh(function):
    @functools.wraps(function)
    def wrapped() -> int:
        verify_only = "--verify-only" in sys.argv[1:]
        try:
            lock = acquire_index_refresh_lock(
                index_refresh_lock_path(),
                wait=not verify_only,
            )
        except IndexRefreshBusy:
            emit_progress(
                "server-index-refresh",
                "skipped",
                item="concurrent-refresh-active",
            )
            return 0
        try:
            return function()
        finally:
            release_index_refresh_lock(lock)

    return wrapped


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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
        connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        >= minimum
        for table, minimum in REQUIRED_STRUCTURED_TABLES.items()
    )


def valid_index(path: Path, *, quick_check: bool = True) -> bool:
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if (
                quick_check
                and connection.execute("PRAGMA quick_check").fetchone()[0] != "ok"
            ):
                return False
            return structured_tables_valid(connection)
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def write_status(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def signing_secrets() -> list[bytes]:
    values = [
        os.environ.get("JIAOTANG_OSS_RELEASE_SIGNING_SECRET", ""),
        *os.environ.get(
            "JIAOTANG_OSS_RELEASE_VERIFY_SECRETS",
            "",
        ).split(","),
    ]
    secrets = [value.strip().encode() for value in values if value.strip()]
    if not secrets or any(len(secret) < 32 for secret in secrets):
        raise RuntimeError(
            "索引release当前及历史验签密钥均至少需要32字节，"
            "缓存刷新不得信任未签名release"
        )
    return secrets


def secret_for_key(secrets: list[bytes], key_id: str) -> bytes:
    for secret in secrets:
        if hmac.compare_digest(signing_key_id(secret), key_id):
            return secret
    raise RuntimeError(f"未配置release验签密钥：{key_id}")


def load_json(payload: bytes, label: str) -> dict[str, object]:
    try:
        result = json.loads(payload)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{label}不是有效JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"{label}必须是JSON对象")
    return result


def verify_pointer(payload: bytes, secrets: list[bytes]) -> dict[str, object]:
    pointer = load_json(payload, "current指针")
    if pointer.get("schema") != POINTER_SCHEMA:
        raise RuntimeError("current指针schema不受支持")
    signature = str(pointer.pop("pointer_hmac_sha256", ""))
    secret = secret_for_key(secrets, str(pointer.get("signing_key_id") or ""))
    expected = hmac.new(
        secret,
        canonical_json(pointer),
        hashlib.sha256,
    ).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise RuntimeError("current指针HMAC校验失败")
    pointer["pointer_hmac_sha256"] = signature
    release_id = str(pointer.get("release_id") or "")
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise RuntimeError("current指针release_id非法")
    return pointer


def verify_release(
    manifest_body: bytes,
    signature_body: bytes,
    pointer: dict[str, object],
    secrets: list[bytes],
) -> dict[str, object]:
    expected_manifest_sha = str(pointer.get("release_manifest_sha256") or "")
    if not hmac.compare_digest(sha256_bytes(manifest_body), expected_manifest_sha):
        raise RuntimeError("release.json与current指针摘要不一致")
    signature = load_json(signature_body, "release.sig")
    if signature.get("algorithm") != "hmac-sha256":
        raise RuntimeError("release签名算法不受支持")
    secret = secret_for_key(secrets, str(signature.get("key_id") or ""))
    if signature.get("key_id") != pointer.get("signing_key_id"):
        raise RuntimeError("release签名密钥与current指针不一致")
    if not hmac.compare_digest(
        str(signature.get("document_sha256") or ""),
        expected_manifest_sha,
    ):
        raise RuntimeError("release.sig文档摘要不一致")
    expected_hmac = hmac.new(secret, manifest_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(
        str(signature.get("signature") or ""),
        expected_hmac,
    ):
        raise RuntimeError("release.json HMAC验签失败")
    release = load_json(manifest_body, "release.json")
    if release.get("schema") != MANIFEST_SCHEMA:
        raise RuntimeError("release.json schema不受支持")
    if release.get("release_id") != pointer.get("release_id"):
        raise RuntimeError("release.json与current指针release_id不一致")
    whitelist = release.get("file_whitelist")
    if whitelist != list(PRODUCTION_FILES):
        raise RuntimeError("release文件白名单与运行时契约不一致")
    files = release.get("files")
    if not isinstance(files, list):
        raise RuntimeError("release.json缺少files")
    names = [str(row.get("name") or "") for row in files if isinstance(row, dict)]
    if names != list(PRODUCTION_FILES) or len(names) != len(set(names)):
        raise RuntimeError("release文件集合不完整、有额外项或顺序异常")
    for row in files:
        if (
            not isinstance(row, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256") or ""))
            or int(row.get("size") or -1) < 0
            or not str(row.get("crc64") or "").isdigit()
        ):
            raise RuntimeError("release文件元数据非法")
    return release


def remote_bytes(bucket: object, key: str) -> bytes:
    return bucket.get_object(key).read()


def download_release(
    bucket: object,
    prefix: str,
    release: dict[str, object],
    target: Path,
) -> None:
    release_id = str(release["release_id"])
    target.mkdir(parents=True, exist_ok=False)
    try:
        for row in release["files"]:
            assert isinstance(row, dict)
            name = str(row["name"])
            path = target / name
            key = f"{prefix}/index/releases/{release_id}/{name}"
            expected_size = int(row["size"])
            reporter = TransferProgress("oss-download", name, expected_size)
            try:
                bucket.get_object_to_file(
                    key,
                    str(path),
                    progress_callback=reporter,
                )
            except Exception:
                reporter.finish(status="failed")
                raise
            reporter.finish()
            if path.stat().st_size != int(row["size"]):
                raise RuntimeError(f"下载大小不一致：{name}")
            digest, crc64, _ = sha256_crc64_file(
                path,
                stage="download-verify",
            )
            if not hmac.compare_digest(digest, str(row["sha256"])):
                raise RuntimeError(f"下载SHA-256不一致：{name}")
            if crc64 != int(str(row["crc64"])):
                raise RuntimeError(f"下载CRC64不一致：{name}")
        emit_progress(
            "sqlite-validation",
            "started",
            item="knowledge_content.sqlite3",
        )
        if not valid_index(target / "knowledge_content.sqlite3"):
            raise RuntimeError("下载索引完整性或结构化专表校验失败")
        emit_progress(
            "sqlite-validation",
            "completed",
            item="knowledge_content.sqlite3",
        )
        (target / "release.json").write_bytes(canonical_json(release))
    except Exception:
        if target.exists():
            preserve_generated_staging(target, "failed-download")
        raise


def release_id_from_link(link: Path) -> str | None:
    if not link.is_symlink():
        return None
    target = Path(os.readlink(link))
    if (
        target.is_absolute()
        or len(target.parts) != 2
        or target.parts[0] != "releases"
        or not RELEASE_ID_PATTERN.fullmatch(target.parts[1])
    ):
        return None
    return target.parts[1]


def replace_symlink(link: Path, target: str) -> None:
    temporary = link.with_name(
        f".{link.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    temporary.symlink_to(target)
    os.replace(temporary, link)


def preserve_generated_staging(path: Path, label: str) -> Path:
    """Move only the staging directory created by this invocation to a recoverable name."""

    destination = path.with_name(
        f"{path.name}.{label}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
        f".{secrets.token_hex(4)}"
    )
    os.replace(path, destination)
    return destination


def require_unused_staging(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError(
            f"发现既有暂存路径且本轮未获授权处置：{path}"
        )


def install_downloaded_release(
    staging: Path,
    release_dir: Path,
    index_dir: Path,
    release_id: str,
) -> Path | None:
    try:
        os.rename(staging, release_dir)
        return None
    except OSError as error:
        if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
            raise
        preserved = preserve_generated_staging(staging, "concurrent-release")
        if not local_generation_valid(index_dir, release_id):
            raise RuntimeError("并发刷新产生同名但无效release") from error
        emit_progress(
            "index-install",
            "deduplicated",
            item=f"{release_id}:errno-{error.errno}",
        )
        return preserved


def ensure_root_aliases(index_dir: Path) -> None:
    for name in PRODUCTION_FILES:
        alias = index_dir / name
        expected = f"current/{name}"
        if alias.is_symlink() and os.readlink(alias) == expected:
            continue
        if alias.exists() and not alias.is_symlink():
            raise RuntimeError(f"根索引文件尚未迁移到release目录：{alias}")
        replace_symlink(alias, expected)


def local_release_metadata(
    index_dir: Path,
    release_id: str,
) -> dict[str, object] | None:
    release_dir = index_dir / "releases" / release_id
    if not release_dir.is_dir():
        return None
    manifest_path = release_dir / "release.json"
    if not manifest_path.is_file():
        return None
    try:
        release = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(release, dict):
        return None
    if (
        release.get("schema") != MANIFEST_SCHEMA
        or release.get("release_id") != release_id
        or release.get("file_whitelist") != list(PRODUCTION_FILES)
    ):
        return None
    files = release.get("files")
    if not isinstance(files, list):
        return None
    names = [
        str(row.get("name") or "")
        for row in files
        if isinstance(row, dict)
    ]
    if names != list(PRODUCTION_FILES) or len(names) != len(files):
        return None
    for row in files:
        if not isinstance(row, dict):
            return None
        name = str(row.get("name") or "")
        path = release_dir / name
        try:
            size = int(row.get("size"))
            int(str(row.get("crc64")))
        except (TypeError, ValueError):
            return None
        if (
            size < 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256") or ""))
            or not path.is_file()
            or path.stat().st_size != size
        ):
            return None
    return release


def local_generation_metadata_valid(index_dir: Path, release_id: str) -> bool:
    """Cheap health-path validation; deep hashes and SQLite checks stay in refresh."""

    return local_release_metadata(index_dir, release_id) is not None


def local_generation_valid(index_dir: Path, release_id: str) -> bool:
    release = local_release_metadata(index_dir, release_id)
    if release is None:
        return False
    release_dir = index_dir / "releases" / release_id
    files = release["files"]
    assert isinstance(files, list)
    for row in files:
        assert isinstance(row, dict)
        path = release_dir / str(row["name"])
        if sha256_file(path) != row.get("sha256"):
            return False
    return valid_index(release_dir / "knowledge_content.sqlite3")


def root_files_match_release(index_dir: Path, release_id: str) -> bool:
    release_dir = index_dir / "releases" / release_id
    try:
        release = json.loads(
            (release_dir / "release.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    rows = release.get("files")
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        name = str(row.get("name") or "")
        root_file = index_dir / name
        if (
            name not in PRODUCTION_FILES
            or root_file.is_symlink()
            or not root_file.is_file()
            or root_file.stat().st_size != int(row.get("size") or -1)
            or sha256_file(root_file) != str(row.get("sha256") or "")
        ):
            return False
    return len(rows) == len(PRODUCTION_FILES)


def runtime_binding_mode(index_dir: Path, release_id: str) -> str | None:
    if all(
        (index_dir / name).is_symlink()
        and os.readlink(index_dir / name) == f"current/{name}"
        for name in PRODUCTION_FILES
    ):
        return "atomic-release-links"
    if root_files_match_release(index_dir, release_id):
        return "legacy-root-readonly"
    return None


def activate_release(
    index_dir: Path,
    release_id: str,
    *,
    prevalidated: bool = False,
) -> tuple[str | None, str | None]:
    releases_dir = index_dir / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    validation = (
        local_generation_metadata_valid if prevalidated else local_generation_valid
    )
    if not validation(index_dir, release_id):
        raise RuntimeError(f"待激活release本地校验失败：{release_id}")
    current_link = index_dir / "current"
    previous_link = index_dir / "previous"
    old_current = release_id_from_link(current_link)
    old_previous = release_id_from_link(previous_link)
    regular_root_files = any(
        (index_dir / name).is_file() and not (index_dir / name).is_symlink()
        for name in PRODUCTION_FILES
    )
    if regular_root_files:
        if old_current not in {None, release_id}:
            raise RuntimeError(
                "既有根索引仍处于只读兼容模式；本轮未获授权迁移或处置，"
                "拒绝切换到不同release"
            )
        if not root_files_match_release(index_dir, release_id):
            raise RuntimeError(
                "既有根索引与目标release不一致；本轮未获授权迁移或处置"
            )
        replace_symlink(current_link, f"releases/{release_id}")
        return old_current, old_previous
    if old_current and old_current != release_id:
        replace_symlink(previous_link, f"releases/{old_current}")
    replace_symlink(current_link, f"releases/{release_id}")
    ensure_root_aliases(index_dir)
    if not validation(index_dir, release_id):
        if old_current and local_generation_valid(index_dir, old_current):
            replace_symlink(current_link, f"releases/{old_current}")
            if old_previous and local_generation_valid(index_dir, old_previous):
                replace_symlink(previous_link, f"releases/{old_previous}")
        raise RuntimeError("release切换后复检失败，已尝试恢复原current")
    return old_current, release_id_from_link(previous_link)


def rollback_release(index_dir: Path) -> tuple[str, str]:
    current_link = index_dir / "current"
    previous_link = index_dir / "previous"
    current = release_id_from_link(current_link)
    previous = release_id_from_link(previous_link)
    if not current or not previous:
        raise RuntimeError("current/previous身份不完整，无法自动回滚")
    if not local_generation_valid(index_dir, previous):
        raise RuntimeError(f"previous release校验失败，拒绝回滚：{previous}")
    replace_symlink(current_link, f"releases/{previous}")
    replace_symlink(previous_link, f"releases/{current}")
    ensure_root_aliases(index_dir)
    if not local_generation_valid(index_dir, previous):
        replace_symlink(current_link, f"releases/{current}")
        replace_symlink(previous_link, f"releases/{previous}")
        raise RuntimeError("回滚后复检失败，已恢复回滚前current")
    return current, previous


def apply_ownership(path: Path, user: str) -> None:
    try:
        account = pwd.getpwnam(user)
    except KeyError:
        if os.geteuid() == 0:
            raise
        return
    for item in [path, *path.rglob("*")]:
        if not item.is_symlink():
            os.chown(item, 0, account.pw_gid)
            os.chmod(item, 0o550 if item.is_dir() else 0o440)


def status_payload(
    index_dir: Path,
    *,
    status: str,
    source: str,
    error: str | None = None,
    cache_updated: bool = False,
    pointer_sha256: str | None = None,
) -> dict[str, object]:
    current = release_id_from_link(index_dir / "current")
    previous = release_id_from_link(index_dir / "previous")
    current_metadata = (
        local_release_metadata(index_dir, current) if current else None
    )
    current_files = (
        current_metadata.get("files") if current_metadata else None
    )
    index_sha256 = None
    if isinstance(current_files, list):
        index_sha256 = next(
            (
                str(row.get("sha256") or "")
                for row in current_files
                if isinstance(row, dict)
                and row.get("name") == "knowledge_content.sqlite3"
            ),
            None,
        )
    payload: dict[str, object] = {
        "status": status,
        "mode": "OSS不可变release + 本地原子current/previous",
        "checked_at": utc_timestamp(),
        "cache_updated_at": utc_timestamp(),
        "source": source,
        "current_release_id": current,
        "previous_release_id": previous,
        "index_sha256": index_sha256,
        "pointer_sha256": pointer_sha256,
        "generation_consistent": bool(
            current
            and local_generation_metadata_valid(index_dir, current)
            and runtime_binding_mode(index_dir, current)
        ),
        "runtime_mode": (
            runtime_binding_mode(index_dir, current) if current else None
        ),
        "cache_updated": cache_updated,
    }
    if error:
        payload["error"] = error[:500]
    return payload


def cleanup_index_generations(index_dir: Path) -> dict[str, object]:
    try:
        report = prune_release_generations(
            index_dir / "releases",
            index_dir,
            apply=True,
        )
        emit_progress(
            "index-release-retention",
            "completed",
            item=f"removed={report['removed_count']}",
        )
        return report
    except Exception as error:
        # A healthy, signed current index remains usable even if historical
        # garbage collection needs manual recovery.
        emit_progress(
            "index-release-retention",
            "failed",
            item=error.__class__.__name__,
        )
        return {
            "schema": "jiaotang-release-retention/v1",
            "applied": False,
            "error": str(error)[:500],
        }


@serialized_index_refresh
def main() -> int:
    parser = argparse.ArgumentParser(
        description="从OSS签名current指针刷新本地不可变索引release"
    )
    parser.add_argument("--allow-stale", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "只验签OSS current指针、release元数据和对象集；"
            "当远程release变化时才继续下载并切换"
        ),
    )
    args = parser.parse_args()
    index_dir = Path(
        os.environ.get("JIAOTANG_INDEX_DIR", "/srv/jiaotang/knowledge-index")
    )
    status_path = Path(
        os.environ.get(
            "JIAOTANG_OSS_INDEX_CACHE_STATUS",
            "/var/lib/jiaotang-kb/oss-index-cache-status.json",
        )
    )
    index_dir.mkdir(parents=True, exist_ok=True)
    if args.rollback:
        old, restored = rollback_release(index_dir)
        write_status(
            status_path,
            status_payload(
                index_dir,
                status="正常",
                source="previous自动回滚",
                cache_updated=True,
            )
            | {"rolled_back_release_id": old, "restored_release_id": restored},
        )
        return 0

    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    pointer_key = f"{prefix}/index/current.json"
    try:
        emit_progress("server-index-refresh", "started", item="signed-current")
        secrets = signing_secrets()
        bucket = build_bucket()
        emit_progress("pointer-verification", "started", item=pointer_key)
        pointer_body = remote_bytes(bucket, pointer_key)
        pointer = verify_pointer(pointer_body, secrets)
        manifest_key = str(pointer.get("release_manifest_key") or "")
        signature_key = str(pointer.get("release_signature_key") or "")
        expected_prefix = f"{prefix}/index/releases/{pointer['release_id']}/"
        if (
            manifest_key != expected_prefix + "release.json"
            or signature_key != expected_prefix + "release.sig"
        ):
            raise RuntimeError("current指针指向release目录之外")
        manifest_body = remote_bytes(bucket, manifest_key)
        signature_body = remote_bytes(bucket, signature_key)
        release = verify_release(
            manifest_body,
            signature_body,
            pointer,
            secrets,
        )
        emit_progress(
            "pointer-verification",
            "completed",
            item=str(pointer["release_id"]),
        )
        release_id = str(release["release_id"])
        expected_keys = {
            *(
                f"{expected_prefix}{name}"
                for name in PRODUCTION_FILES
            ),
            expected_prefix + "release.json",
            expected_prefix + "release.sig",
        }
        actual_keys = {
            item.key
            for item in oss2.ObjectIterator(
                bucket,
                prefix=expected_prefix,
            )
        }
        if actual_keys != expected_keys:
            raise RuntimeError(
                "current release远端对象集合与白名单不一致："
                f"缺失={sorted(expected_keys - actual_keys)[:10]}，"
                f"额外={sorted(actual_keys - expected_keys)[:10]}"
            )
        release_dir = index_dir / "releases" / release_id
        local_current = release_id_from_link(index_dir / "current")
        if (
            args.verify_only
            and local_current == release_id
            and local_generation_metadata_valid(index_dir, release_id)
            and runtime_binding_mode(index_dir, release_id)
        ):
            existing_status: dict[str, object] = {}
            try:
                existing_status = load_json(
                    status_path.read_bytes(),
                    "本地OSS校验状态",
                )
            except (OSError, RuntimeError):
                existing_status = {}
            payload = status_payload(
                index_dir,
                status="正常",
                source="OSS签名release轻量巡检",
                cache_updated=False,
                pointer_sha256=sha256_bytes(pointer_body),
            ) | {
                "object_key": pointer_key,
                "release_manifest_key": manifest_key,
                "verification_mode": "metadata-only",
            }
            payload["cache_updated_at"] = existing_status.get(
                "cache_updated_at"
            ) or payload["checked_at"]
            payload["retention_cleanup"] = cleanup_index_generations(index_dir)
            write_status(status_path, payload)
            emit_progress(
                "server-index-refresh",
                "completed",
                item=f"{release_id}:metadata-only",
            )
            return 0
        if not local_generation_valid(index_dir, release_id):
            staging = index_dir / "releases" / f".{release_id}.{os.getpid()}.staging"
            require_unused_staging(staging)
            download_release(bucket, prefix, release, staging)
            apply_ownership(
                staging,
                os.environ.get("JIAOTANG_SERVICE_USER", "jiaotang"),
            )
            install_downloaded_release(
                staging,
                release_dir,
                index_dir,
                release_id,
            )
        old_current = release_id_from_link(index_dir / "current")
        emit_progress("index-activation", "started", item=release_id)
        activate_release(index_dir, release_id, prevalidated=True)
        refreshed_status = (
            status_payload(
                index_dir,
                status="正常",
                source="OSS签名release",
                cache_updated=old_current != release_id,
                pointer_sha256=sha256_bytes(pointer_body),
            )
            | {
                "object_key": pointer_key,
                "release_manifest_key": manifest_key,
            }
        )
        refreshed_status["retention_cleanup"] = cleanup_index_generations(index_dir)
        write_status(status_path, refreshed_status)
        emit_progress("index-activation", "completed", item=release_id)
        emit_progress("server-index-refresh", "completed", item=release_id)
        return 0
    except Exception as error:
        emit_progress(
            "server-index-refresh",
            "failed",
            item=error.__class__.__name__,
        )
        write_status(
            status_path,
            status_payload(
                index_dir,
                status="降级" if args.allow_stale else "异常",
                source="最近一次本地只读release",
                error=str(error),
            ),
        )
        if args.allow_stale:
            current = release_id_from_link(index_dir / "current")
            if current and local_generation_valid(index_dir, current):
                return 0
        raise


if __name__ == "__main__":
    raise SystemExit(main())

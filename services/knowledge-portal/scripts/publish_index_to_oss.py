from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import oss2

try:
    from scripts.oss_auth import build_bucket
    from scripts.verify_acceptance_receipt import (
        DEFAULT_PROFILE,
        verify_receipt_against_release,
    )
except ImportError:  # direct script execution
    from oss_auth import build_bucket
    from verify_acceptance_receipt import (
        DEFAULT_PROFILE,
        verify_receipt_against_release,
    )


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
)
FULL_INDEX_NAME = "knowledge_content.sqlite3"
RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
MANIFEST_SCHEMA = "jiaotang-index-release/v1"
POINTER_SCHEMA = "jiaotang-index-pointer/v1"
TRANSITION_SCHEMA = "jiaotang-index-transition/v1"


def canonical_json(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def crc64_file(path: Path) -> int:
    digest = oss2.utils.Crc64()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return int(digest.crc)


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
    """Retained for callers that estimate cadence; atomic releases always include it."""

    if policy == "always" or remote is None:
        return True
    if policy == "skip":
        return False
    last_modified = getattr(remote, "last_modified", None)
    if not last_modified:
        return True
    remote_time = datetime.fromtimestamp(float(last_modified), timezone.utc)
    return now - remote_time >= timedelta(days=max(max_age_days, 1))


def release_id_for(index_dir: Path, *, checkpoint: bool = True) -> str:
    digest = hashlib.sha256()
    for name in PRODUCTION_FILES:
        path = index_dir / name
        if not path.is_file():
            raise RuntimeError(f"生成release_id时缺少文件：{name}")
        if checkpoint:
            checkpoint_sqlite(path)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return "index-" + digest.hexdigest()[:40]


def signing_secret() -> bytes:
    secret = os.environ.get("JIAOTANG_OSS_RELEASE_SIGNING_SECRET", "").encode()
    if len(secret) < 32:
        raise RuntimeError(
            "JIAOTANG_OSS_RELEASE_SIGNING_SECRET至少需要32字节，"
            "索引发布不得使用未签名清单"
        )
    return secret


def signing_key_id(secret: bytes) -> str:
    return "hmac-" + hashlib.sha256(secret).hexdigest()[:16]


def verification_secrets(current_secret: bytes) -> list[bytes]:
    historical = [
        value.strip().encode()
        for value in os.environ.get(
            "JIAOTANG_OSS_RELEASE_VERIFY_SECRETS",
            "",
        ).split(",")
        if value.strip()
    ]
    if any(len(secret) < 32 for secret in historical):
        raise RuntimeError("历史release验签密钥至少需要32字节")
    return [current_secret, *historical]


def verify_pointer_signature(
    pointer: dict[str, object],
    secrets: list[bytes],
) -> None:
    unsigned = dict(pointer)
    signature = str(unsigned.pop("pointer_hmac_sha256", ""))
    key_id = str(unsigned.get("signing_key_id") or "")
    for secret in secrets:
        if (
            hmac.compare_digest(signing_key_id(secret), key_id)
            and signature
            and hmac.compare_digest(
                signature,
                hmac.new(
                    secret,
                    canonical_json(unsigned),
                    hashlib.sha256,
                ).hexdigest(),
            )
        ):
            return
    raise RuntimeError("既有current指针HMAC校验失败")


def signed_document(
    payload: dict[str, object],
    secret: bytes,
) -> tuple[bytes, bytes]:
    body = canonical_json(payload)
    signature = canonical_json(
        {
            "algorithm": "hmac-sha256",
            "key_id": signing_key_id(secret),
            "document_sha256": sha256_bytes(body),
            "signature": hmac.new(secret, body, hashlib.sha256).hexdigest(),
        }
    )
    return body, signature


def verify_existing_signed_document(
    body: bytes,
    signature_body: bytes,
    secrets: list[bytes],
) -> None:
    try:
        signature = json.loads(signature_body)
    except json.JSONDecodeError as error:
        raise RuntimeError("既有release.sig不是有效JSON") from error
    if signature.get("algorithm") != "hmac-sha256":
        raise RuntimeError("既有不可变release签名算法不受支持")
    candidates = [
        secret
        for secret in secrets
        if hmac.compare_digest(
            str(signature.get("key_id") or ""),
            signing_key_id(secret),
        )
    ]
    if (
        signature.get("document_sha256") != sha256_bytes(body)
        or not any(
            hmac.compare_digest(
                str(signature.get("signature") or ""),
                hmac.new(secret, body, hashlib.sha256).hexdigest(),
            )
            for secret in candidates
        )
    ):
        raise RuntimeError("既有不可变release签名校验失败")


def metadata_value(remote: object, name: str) -> str:
    headers = getattr(remote, "headers", {}) or {}
    return str(headers.get(name, headers.get(name.lower(), "")))


def head_optional(bucket: object, object_key: str) -> object | None:
    try:
        return bucket.head_object(object_key)
    except oss2.exceptions.NoSuchKey:
        return None


def remote_bytes(bucket: object, object_key: str) -> bytes:
    result = bucket.get_object(object_key)
    return result.read()


def verify_remote_object(
    bucket: object,
    object_key: str,
    *,
    digest: str,
    size: int,
    crc64: int | None = None,
) -> object:
    remote = bucket.head_object(object_key)
    if int(remote.content_length) != size:
        raise RuntimeError(f"OSS对象大小不一致：{object_key}")
    if metadata_value(remote, "x-oss-meta-sha256") != digest:
        raise RuntimeError(f"OSS对象SHA-256元数据不一致：{object_key}")
    remote_crc = int(
        getattr(remote, "hash_crc64_ecma", 0)
        or metadata_value(remote, "x-oss-hash-crc64ecma")
        or 0
    )
    metadata_crc = int(metadata_value(remote, "x-oss-meta-crc64") or 0)
    if crc64 is not None and metadata_crc != crc64:
        raise RuntimeError(f"OSS对象CRC64元数据不一致：{object_key}")
    if crc64 is not None and remote_crc and remote_crc != crc64:
        raise RuntimeError(f"OSS对象CRC64不一致：{object_key}")
    return remote


def put_immutable_file(
    bucket: object,
    object_key: str,
    source: Path,
    *,
    digest: str,
    size: int,
    crc64: int,
) -> str:
    existing = head_optional(bucket, object_key)
    if existing is not None:
        verify_remote_object(
            bucket,
            object_key,
            digest=digest,
            size=size,
            crc64=crc64,
        )
        verify_download_sample(bucket, object_key, source)
        return "existing"
    headers = {
        "x-oss-forbid-overwrite": "true",
        "x-oss-meta-sha256": digest,
        "x-oss-meta-source-size": str(size),
        "x-oss-meta-crc64": str(crc64),
    }
    if size >= 64 * 1024 * 1024:
        checkpoint_store = oss2.ResumableStore(
            root=os.environ.get(
                "JIAOTANG_OSS_CHECKPOINT_DIR",
                "/tmp/jiaotang-oss-checkpoints",
            ),
            dir=digest,
        )
        oss2.resumable_upload(
            bucket,
            object_key,
            str(source),
            store=checkpoint_store,
            multipart_threshold=64 * 1024 * 1024,
            part_size=16 * 1024 * 1024,
            headers=headers,
            num_threads=4,
        )
    else:
        bucket.put_object_from_file(object_key, str(source), headers=headers)
    if sha256_file(source) != digest or source.stat().st_size != size:
        raise RuntimeError(f"发布期间文件发生变化：{source.name}")
    verify_remote_object(
        bucket,
        object_key,
        digest=digest,
        size=size,
        crc64=crc64,
    )
    verify_download_sample(bucket, object_key, source)
    return "uploaded"


def put_immutable_bytes(
    bucket: object,
    object_key: str,
    payload: bytes,
) -> str:
    digest = sha256_bytes(payload)
    existing = head_optional(bucket, object_key)
    if existing is not None:
        verify_remote_object(
            bucket,
            object_key,
            digest=digest,
            size=len(payload),
        )
        if remote_bytes(bucket, object_key) != payload:
            raise RuntimeError(f"OSS不可变对象内容冲突：{object_key}")
        return "existing"
    bucket.put_object(
        object_key,
        payload,
        headers={
            "x-oss-forbid-overwrite": "true",
            "x-oss-meta-sha256": digest,
            "x-oss-meta-source-size": str(len(payload)),
        },
    )
    verify_remote_object(
        bucket,
        object_key,
        digest=digest,
        size=len(payload),
    )
    if remote_bytes(bucket, object_key) != payload:
        raise RuntimeError(f"OSS发布后下载抽验失败：{object_key}")
    return "uploaded"


def verify_download_sample(
    bucket: object,
    object_key: str,
    source: Path,
    *,
    sample_size: int = 1024 * 1024,
) -> None:
    size = source.stat().st_size
    if size <= sample_size * 2:
        if remote_bytes(bucket, object_key) != source.read_bytes():
            raise RuntimeError(f"OSS下载全量抽验失败：{object_key}")
        return
    with source.open("rb") as stream:
        expected_first = stream.read(sample_size)
        stream.seek(size - sample_size)
        expected_last = stream.read(sample_size)
    first = bucket.get_object(object_key, byte_range=(0, sample_size - 1)).read()
    last = bucket.get_object(
        object_key,
        byte_range=(size - sample_size, size - 1),
    ).read()
    if first != expected_first or last != expected_last:
        raise RuntimeError(f"OSS下载首尾抽验失败：{object_key}")


def verify_release_object_whitelist(
    bucket: object,
    release_prefix: str,
) -> None:
    expected = {
        *(f"{release_prefix}/{name}" for name in PRODUCTION_FILES),
        f"{release_prefix}/release.json",
        f"{release_prefix}/release.sig",
    }
    actual = {
        item.key
        for item in oss2.ObjectIterator(
            bucket,
            prefix=release_prefix + "/",
        )
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RuntimeError(
            "release对象白名单不一致："
            f"缺失={missing[:10]}，额外={extra[:10]}"
        )


def parse_pointer(payload: bytes) -> dict[str, object]:
    try:
        pointer = json.loads(payload)
    except json.JSONDecodeError as error:
        raise RuntimeError("OSS current指针不是有效JSON") from error
    if pointer.get("schema") != POINTER_SCHEMA:
        raise RuntimeError("OSS current指针schema不受支持")
    return pointer


def pointer_state(bucket: object, key: str) -> tuple[dict[str, object] | None, str | None]:
    remote = head_optional(bucket, key)
    if remote is None:
        return None, None
    payload = remote_bytes(bucket, key)
    return parse_pointer(payload), str(remote.etag)


def switch_pointer_cas(
    bucket: object,
    key: str,
    pointer: dict[str, object],
    *,
    expected_release_id: str | None,
    allow_initial: bool,
) -> str:
    current, _ = pointer_state(bucket, key)
    target_release = str(pointer["release_id"])
    if current and current.get("release_id") == target_release:
        if current != pointer:
            raise RuntimeError("current已指向同名release但内容不一致")
        return "unchanged"
    actual_release = str(current.get("release_id") or "") if current else ""
    if current is None:
        if not allow_initial:
            raise RuntimeError("current指针不存在；首次发布必须显式使用--allow-initial-current")
        headers = {"x-oss-forbid-overwrite": "true"}
    else:
        if not expected_release_id:
            raise RuntimeError("覆盖current前必须提供--expected-current-release-id")
        if actual_release != expected_release_id:
            raise RuntimeError(
                f"current CAS冲突：预期{expected_release_id}，实际{actual_release}"
            )
        body = canonical_json(pointer)
        transition = {
            "schema": TRANSITION_SCHEMA,
            "expected_release_id": expected_release_id,
            "target_release_id": target_release,
            "target_pointer_sha256": sha256_bytes(body),
        }
        transition_body = canonical_json(transition)
        transition_key = (
            f"{key.rsplit('/', 1)[0]}/transitions/"
            f"{expected_release_id}.json"
        )
        transition_headers = {
            "x-oss-forbid-overwrite": "true",
            "x-oss-meta-sha256": sha256_bytes(transition_body),
            "x-oss-meta-source-size": str(len(transition_body)),
            "x-oss-meta-expected-release-id": expected_release_id,
            "x-oss-meta-target-release-id": target_release,
        }
        try:
            bucket.put_object(
                transition_key,
                transition_body,
                headers=transition_headers,
            )
        except Exception as error:
            existing_transition = head_optional(bucket, transition_key)
            if existing_transition is None:
                raise
            if remote_bytes(bucket, transition_key) != transition_body:
                raise RuntimeError(
                    "current转换声明冲突：同一前驱release已绑定其他目标"
                ) from error

        confirmed_current, _ = pointer_state(bucket, key)
        if confirmed_current == pointer:
            return "unchanged"
        confirmed_release = (
            str(confirmed_current.get("release_id") or "")
            if confirmed_current
            else ""
        )
        if confirmed_release != expected_release_id:
            raise RuntimeError(
                "current CAS冲突：转换声明写入后指针已变化，"
                f"预期{expected_release_id}，实际{confirmed_release}"
            )
        headers = {}
    body = canonical_json(pointer)
    headers.update(
        {
            "x-oss-meta-sha256": sha256_bytes(body),
            "x-oss-meta-release-id": target_release,
        }
    )
    bucket.put_object(key, body, headers=headers)
    confirmed, _ = pointer_state(bucket, key)
    if confirmed != pointer:
        raise RuntimeError("current指针CAS切换后复核失败")
    return "switched"


@contextmanager
def local_publish_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"其他索引发布任务正在运行：{path}") from error
        stream.seek(0)
        stream.truncate()
        stream.write(f"pid={os.getpid()}\n")
        stream.flush()
        yield


def capacity_guard(
    bucket: object,
    *,
    budget: int | None,
    reserve: int,
) -> None:
    if budget is None:
        return
    stat = bucket.get_bucket_stat()
    current = int(stat.storage_size_in_bytes)
    if current + max(reserve, 0) > budget:
        raise RuntimeError(
            f"OSS容量熔断：当前{current} + 预留{reserve} > 预算{budget}"
        )


def build_release(
    index_dir: Path,
    *,
    release_id: str,
    previous_release_id: str | None,
    prevalidated: bool,
) -> tuple[dict[str, object], list[tuple[Path, dict[str, object]]]]:
    missing = [name for name in PRODUCTION_FILES if not (index_dir / name).is_file()]
    if missing:
        raise RuntimeError("生产索引发布集合不完整：" + ", ".join(missing))
    files: list[tuple[Path, dict[str, object]]] = []
    for name in PRODUCTION_FILES:
        path = index_dir / name
        if not prevalidated:
            checkpoint_sqlite(path)
        verify_sqlite(path)
        size = path.stat().st_size
        digest = sha256_file(path)
        files.append(
            (
                path,
                {
                    "name": name,
                    "size": size,
                    "sha256": digest,
                    "crc64": str(crc64_file(path)),
                },
            )
        )
    manifest: dict[str, object] = {
        "schema": MANIFEST_SCHEMA,
        "release_id": release_id,
        "created_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "previous_release_id": previous_release_id,
        "files": [metadata for _, metadata in files],
        "file_whitelist": list(PRODUCTION_FILES),
    }
    return manifest, files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="以不可变release发布生产索引，并通过CAS原子切换current指针"
    )
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--acceptance-receipt", type=Path)
    parser.add_argument("--acceptance-profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--release-id")
    parser.add_argument("--expected-current-release-id")
    parser.add_argument("--allow-initial-current", action="store_true")
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--capacity-budget-bytes", type=int)
    parser.add_argument("--reserve-bytes", type=int, default=0)
    parser.add_argument("--prevalidated", action="store_true")
    parser.add_argument(
        "--index-policy",
        choices=("skip", "weekly", "always"),
        default="always",
        help="兼容旧调用；原子release只允许always",
    )
    parser.add_argument("--full-index-max-age-days", type=int, default=7)
    parser.add_argument("--snapshot-current", action="store_true")
    args = parser.parse_args()
    if args.index_policy != "always":
        raise SystemExit("不可变索引release必须包含完整索引；--index-policy只能为always")
    if args.snapshot_current:
        raise SystemExit(
            "本轮未启用存量快照处置；不可变release发布不接受--snapshot-current"
        )

    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    pointer_key = f"{prefix}/index/current.json"
    bucket = build_bucket()
    current, _ = pointer_state(bucket, pointer_key)
    secret = signing_secret()
    if current:
        verify_pointer_signature(current, verification_secrets(secret))
    actual_previous = str(current.get("release_id") or "") if current else None
    if (
        args.expected_current_release_id
        and actual_previous != args.expected_current_release_id
    ):
        raise SystemExit(
            "发布前current已变化："
            f"预期{args.expected_current_release_id}，实际{actual_previous or '不存在'}"
        )
    now = datetime.now(timezone.utc)
    lock_path = args.lock_file or Path(
        os.environ.get(
            "JIAOTANG_INDEX_PUBLISH_LOCK",
            str(Path(tempfile.gettempdir()) / "jiaotang-index-publish.lock"),
        )
    )
    with local_publish_lock(lock_path):
        receipt_path = (
            args.acceptance_receipt or args.index_dir / "acceptance-harness.json"
        ).expanduser().resolve()
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Acceptance Harness回执不可用：{receipt_path}") from error
        if not isinstance(receipt, dict):
            raise RuntimeError("Acceptance Harness回执必须是JSON对象")
        receipt_body, receipt_signature_body = signed_document(receipt, secret)
        receipt_digest = sha256_bytes(receipt_body)
        base_release_id = release_id_for(
            args.index_dir,
            checkpoint=not args.prevalidated,
        )
        release_id = "index-" + hashlib.sha256(
            (base_release_id + "\0" + receipt_digest).encode("ascii")
        ).hexdigest()[:40]
        if args.release_id and args.release_id != release_id:
            raise RuntimeError(
                "显式release_id与索引及签名回执计算结果不一致："
                f"预期{release_id}，收到{args.release_id}"
            )
        if not RELEASE_ID_PATTERN.fullmatch(release_id):
            raise SystemExit("release_id格式非法")
        manifest_previous = (
            str(current.get("previous_release_id") or "") or None
            if current and current.get("release_id") == release_id
            else actual_previous
        )
        manifest, files = build_release(
            args.index_dir,
            release_id=release_id,
            previous_release_id=manifest_previous,
            prevalidated=args.prevalidated,
        )
        receipt_validation = verify_receipt_against_release(
            receipt,
            args.acceptance_profile.expanduser().resolve(),
            manifest,
            "knowledge_base",
        )
        if receipt_validation["status"] != "pass":
            raise RuntimeError(
                "Acceptance Harness回执与待签名索引不一致："
                + "; ".join(str(item) for item in receipt_validation["errors"])
            )
        receipt_prefix = f"{prefix}/index/acceptance-receipts/{receipt_digest}"
        release_prefix = f"{prefix}/index/releases/{release_id}"
        existing_manifest = head_optional(
            bucket,
            f"{release_prefix}/release.json",
        )
        if existing_manifest is not None:
            manifest_body = remote_bytes(
                bucket,
                f"{release_prefix}/release.json",
            )
            signature_body = remote_bytes(
                bucket,
                f"{release_prefix}/release.sig",
            )
            verify_existing_signed_document(
                manifest_body,
                signature_body,
                verification_secrets(secret),
            )
            try:
                immutable_manifest = json.loads(manifest_body)
            except json.JSONDecodeError as error:
                raise RuntimeError("既有release.json不是有效JSON") from error
            if (
                immutable_manifest.get("schema") != MANIFEST_SCHEMA
                or immutable_manifest.get("release_id") != release_id
                or immutable_manifest.get("previous_release_id")
                != manifest_previous
                or immutable_manifest.get("file_whitelist")
                != list(PRODUCTION_FILES)
                or immutable_manifest.get("files") != manifest.get("files")
            ):
                raise RuntimeError("同名release已存在但与本次冻结集合不一致")
            manifest = immutable_manifest
        else:
            manifest_body, signature_body = signed_document(manifest, secret)
        required_capacity = max(args.reserve_bytes, 0)
        for _, metadata in files:
            if head_optional(
                bucket,
                f"{release_prefix}/{metadata['name']}",
            ) is None:
                required_capacity += int(metadata["size"])
        for name, payload in (
            ("release.json", manifest_body),
            ("release.sig", signature_body),
            ("acceptance-receipt.json", receipt_body),
            ("acceptance-receipt.sig", receipt_signature_body),
        ):
            object_prefix = (
                receipt_prefix
                if name.startswith("acceptance-receipt.")
                else release_prefix
            )
            if head_optional(bucket, f"{object_prefix}/{name}") is None:
                required_capacity += len(payload)
        capacity_guard(
            bucket,
            budget=args.capacity_budget_bytes,
            reserve=required_capacity,
        )
        uploaded = existing = 0
        for path, metadata in files:
            status = put_immutable_file(
                bucket,
                f"{release_prefix}/{metadata['name']}",
                path,
                digest=str(metadata["sha256"]),
                size=int(metadata["size"]),
                crc64=int(str(metadata["crc64"])),
            )
            uploaded += int(status == "uploaded")
            existing += int(status == "existing")
        for name, payload in (
            ("release.json", manifest_body),
            ("release.sig", signature_body),
            ("acceptance-receipt.json", receipt_body),
            ("acceptance-receipt.sig", receipt_signature_body),
        ):
            object_prefix = (
                receipt_prefix
                if name.startswith("acceptance-receipt.")
                else release_prefix
            )
            status = put_immutable_bytes(
                bucket,
                f"{object_prefix}/{name}",
                payload,
            )
            uploaded += int(status == "uploaded")
            existing += int(status == "existing")
        verify_release_object_whitelist(bucket, release_prefix)

        manifest_digest = sha256_bytes(manifest_body)
        if current and current.get("release_id") == release_id:
            pointer_unsigned = current
        else:
            pointer_unsigned = {
                "schema": POINTER_SCHEMA,
                "release_id": release_id,
                "release_manifest_key": f"{release_prefix}/release.json",
                "release_signature_key": f"{release_prefix}/release.sig",
                "release_manifest_sha256": manifest_digest,
                "acceptance_receipt_key": (
                    f"{receipt_prefix}/acceptance-receipt.json"
                ),
                "acceptance_receipt_signature_key": (
                    f"{receipt_prefix}/acceptance-receipt.sig"
                ),
                "acceptance_receipt_sha256": receipt_digest,
                "previous_release_id": manifest_previous,
                "signing_key_id": signing_key_id(secret),
                "switched_at": now.replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
            pointer_unsigned["pointer_hmac_sha256"] = hmac.new(
                secret,
                canonical_json(pointer_unsigned),
                hashlib.sha256,
            ).hexdigest()
        switch_status = switch_pointer_cas(
            bucket,
            pointer_key,
            pointer_unsigned,
            expected_release_id=args.expected_current_release_id,
            allow_initial=args.allow_initial_current,
        )
        capacity_guard(
            bucket,
            budget=args.capacity_budget_bytes,
            reserve=max(args.reserve_bytes, 0),
        )
    print(
        json.dumps(
            {
                "status": "completed",
                "release_id": release_id,
                "previous_release_id": manifest_previous,
                "release_manifest_sha256": manifest_digest,
                "acceptance_receipt_sha256": receipt_digest,
                "objects_uploaded": uploaded,
                "objects_existing": existing,
                "pointer": switch_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

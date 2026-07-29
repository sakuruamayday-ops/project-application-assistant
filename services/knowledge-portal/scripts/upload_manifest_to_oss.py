from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import oss2


THREAD_LOCAL = threading.local()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按生产 manifest 将指定目录增量上传到 OSS")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--allowlist",
        type=Path,
        help="仅上传object_storage_allowed=true的清单项",
    )
    parser.add_argument("--relative-prefix", action="append", default=[])
    parser.add_argument(
        "--object-layout",
        choices=("sha256",),
        default="sha256",
        help="固定按SHA-256内容寻址保存，同一内容全局只上传一份",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--verify-after-upload",
        action="store_true",
        help="上传结束后重新计算本地SHA-256并逐对象核验OSS元数据与大小",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="不执行上传，仅对所选冻结集合进行二次校验",
    )
    parser.add_argument(
        "--require-no-orphans",
        action="store_true",
        help="内容寻址模式下要求OSS objects前缀不存在冻结清单之外的当前对象",
    )
    return parser.parse_args()


def load_allowed_paths(path: Path | None) -> set[tuple[str, str]] | None:
    if path is None:
        return None
    with path.open(encoding="utf-8-sig", newline="") as source:
        return {
            (str(row["relative_path"]), str(row.get("sha256") or ""))
            for row in csv.DictReader(source)
            if str(row.get("object_storage_allowed", "")).lower() == "true"
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bucket() -> oss2.Bucket:
    cached = getattr(THREAD_LOCAL, "bucket", None)
    if cached is not None:
        return cached
    auth = oss2.Auth(
        os.environ["JIAOTANG_OSS_ACCESS_KEY_ID"],
        os.environ["JIAOTANG_OSS_ACCESS_KEY_SECRET"],
    )
    cached = oss2.Bucket(
        auth,
        os.environ["JIAOTANG_OSS_ENDPOINT"].rstrip("/"),
        os.environ["JIAOTANG_OSS_BUCKET"],
    )
    THREAD_LOCAL.bucket = cached
    return cached


def object_key_for(row: dict[str, object], layout: str) -> str:
    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    digest = str(row.get("sha256") or "")
    if layout != "sha256":
        raise ValueError("旧相对路径上传已永久停用，只允许sha256内容寻址布局")
    if not digest:
        raise ValueError(f"内容寻址上传缺少SHA-256：{row.get('relative_path')}")
    return f"{prefix}/knowledge/objects/{digest[:2]}/{digest}"


def upload_once(row: dict[str, object], layout: str) -> tuple[str, int]:
    source = Path(str(row["source_path"]))
    relative = str(row["relative_path"])
    digest = str(row.get("sha256") or "") or sha256_file(source)
    object_key = object_key_for(row, layout)
    current_bucket = bucket()
    try:
        metadata = current_bucket.head_object(object_key)
        remote_digest = str(metadata.headers.get("x-oss-meta-sha256", ""))
        if remote_digest == digest and int(metadata.content_length) == source.stat().st_size:
            return "skipped", 0
    except oss2.exceptions.NoSuchKey:
        pass
    headers = {
        "x-oss-meta-sha256": digest,
        "x-oss-meta-source-size": str(source.stat().st_size),
    }
    if source.stat().st_size >= 64 * 1024 * 1024:
        oss2.resumable_upload(
            current_bucket,
            object_key,
            str(source),
            multipart_threshold=64 * 1024 * 1024,
            part_size=16 * 1024 * 1024,
            headers=headers,
            num_threads=2,
        )
    else:
        current_bucket.put_object_from_file(object_key, str(source), headers=headers)
    return "uploaded", source.stat().st_size


def upload(row: dict[str, object], layout: str) -> tuple[str, int]:
    error: Exception | None = None
    for attempt in range(1, 5):
        try:
            return upload_once(row, layout)
        except Exception as caught:
            error = caught
            if attempt < 4:
                time.sleep(2 ** (attempt - 1))
    assert error is not None
    raise error


def head_object_with_network_retry(
    object_key: str,
    *,
    attempts: int | None = None,
) -> object:
    retry_attempts = max(
        1,
        attempts
        if attempts is not None
        else int(os.environ.get("JIAOTANG_OSS_VERIFY_RETRIES", "5")),
    )
    error: oss2.exceptions.RequestError | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            return bucket().head_object(object_key)
        except oss2.exceptions.NoSuchKey:
            raise
        except oss2.exceptions.RequestError as caught:
            error = caught
            THREAD_LOCAL.bucket = None
            if attempt < retry_attempts:
                time.sleep(min(2 ** (attempt - 1), 8))
    assert error is not None
    raise error


def verify_row(row: dict[str, object], layout: str) -> str | None:
    source = Path(str(row["source_path"]))
    expected_digest = str(row.get("sha256") or "")
    if not source.is_file():
        return f"本地缺失：{source}"
    actual_digest = sha256_file(source)
    if actual_digest != expected_digest:
        return f"冻结后本地内容变化：{source}"
    expected_size = source.stat().st_size
    try:
        remote = head_object_with_network_retry(object_key_for(row, layout))
    except Exception as error:
        return f"OSS读取失败：{object_key_for(row, layout)}：{type(error).__name__}:{error}"
    if int(remote.content_length) != expected_size:
        return f"OSS大小不一致：{object_key_for(row, layout)}"
    if str(remote.headers.get("x-oss-meta-sha256", "")) != expected_digest:
        return f"OSS哈希不一致：{object_key_for(row, layout)}"
    return None


def main() -> None:
    args = parse_args()
    prefixes = tuple(args.relative_prefix)
    allowed_paths = load_allowed_paths(args.allowlist)
    rows = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [
        row
        for row in rows
        if (not prefixes or str(row.get("relative_path", "")).startswith(prefixes))
        and row.get("upload_action") in {"upload", "reference_duplicate"}
        and (
            allowed_paths is None
            or (str(row.get("relative_path", "")), str(row.get("sha256") or ""))
            in allowed_paths
        )
    ]
    if args.object_layout == "sha256":
        unique: dict[str, dict[str, object]] = {}
        for row in selected:
            digest = str(row.get("sha256") or "")
            if not digest:
                raise SystemExit(f"内容寻址上传清单存在无SHA-256文件：{row.get('relative_path')}")
            unique.setdefault(digest, row)
        selected = list(unique.values())
    if not args.verify_only:
        uploaded = skipped = failed = uploaded_bytes = 0
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 16))) as executor:
            futures = {executor.submit(upload, row, args.object_layout): row for row in selected}
            for position, future in enumerate(as_completed(futures), start=1):
                try:
                    status, transferred = future.result()
                    uploaded += int(status == "uploaded")
                    skipped += int(status == "skipped")
                    uploaded_bytes += transferred
                except Exception as error:
                    failed += 1
                    row = futures[future]
                    print(f"failed={row.get('relative_path')} error={type(error).__name__}:{error}", flush=True)
                if position % 250 == 0 or position == len(selected):
                    print(
                        f"processed={position}/{len(selected)} uploaded={uploaded} skipped={skipped} failed={failed}",
                        flush=True,
                    )
        summary = {
            "selected": len(selected),
            "uploaded": uploaded,
            "skipped": skipped,
            "failed": failed,
            "uploaded_bytes": uploaded_bytes,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if failed:
            raise SystemExit(1)
    if args.verify_after_upload or args.verify_only:
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 16))) as executor:
            errors = [error for error in executor.map(
                lambda row: verify_row(row, args.object_layout),
                selected,
            ) if error]
        expected_keys = {object_key_for(row, args.object_layout) for row in selected}
        orphan_keys: set[str] = set()
        if args.require_no_orphans:
            if args.object_layout != "sha256":
                raise SystemExit("--require-no-orphans仅支持sha256内容寻址模式")
            prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
            remote_keys = {
                item.key
                for item in oss2.ObjectIterator(
                    bucket(),
                    prefix=f"{prefix}/knowledge/objects/",
                )
            }
            orphan_keys = remote_keys - expected_keys
        if errors or orphan_keys:
            for error in errors[:30]:
                print(error)
            for key in sorted(orphan_keys)[:30]:
                print(f"OSS孤立对象：{key}")
            raise SystemExit(
                f"二次校验失败：异常{len(errors)}，孤立{len(orphan_keys)}"
            )
        print(
            f"二次校验通过：对象{len(selected)}，失败0，缺失0，孤立0"
        )


if __name__ == "__main__":
    main()

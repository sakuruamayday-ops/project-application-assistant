from __future__ import annotations

import argparse
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
    parser.add_argument("--relative-prefix", action="append", required=True)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


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


def upload_once(row: dict[str, object]) -> tuple[str, int]:
    source = Path(str(row["source_path"]))
    relative = str(row["relative_path"])
    digest = str(row.get("sha256") or "") or sha256_file(source)
    object_key = f"{os.environ.get('JIAOTANG_OSS_PREFIX', 'production').strip('/')}/knowledge/{relative}"
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


def upload(row: dict[str, object]) -> tuple[str, int]:
    error: Exception | None = None
    for attempt in range(1, 5):
        try:
            return upload_once(row)
        except Exception as caught:
            error = caught
            if attempt < 4:
                time.sleep(2 ** (attempt - 1))
    assert error is not None
    raise error


def main() -> None:
    args = parse_args()
    prefixes = tuple(args.relative_prefix)
    rows = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [
        row
        for row in rows
        if str(row.get("relative_path", "")).startswith(prefixes)
        and row.get("upload_action") in {"upload", "reference_duplicate"}
    ]
    uploaded = skipped = failed = uploaded_bytes = 0
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 16))) as executor:
        futures = {executor.submit(upload, row): row for row in selected}
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


if __name__ == "__main__":
    main()

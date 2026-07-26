from __future__ import annotations

import argparse
import json
import os

import oss2


FORBIDDEN_PREFIXES = (
    "production/index/snapshots/",
    "production/index/rollback-snapshots/",
    "production/server-backups/",
    "production/knowledge/current/",
    "production/knowledge/10_政策与目录/",
    "production/knowledge/50_名单与对标/",
    "production/knowledge/90_方法与复盘/",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="复核OSS当前/非当前版本容量和发布后异常占用")
    parser.add_argument("--max-keys", type=int, default=1000)
    parser.add_argument("--max-total-bytes", type=int)
    parser.add_argument(
        "--reserve-bytes",
        type=int,
        default=0,
        help="发布前为即将产生的新增或非当前版本预留容量",
    )
    args = parser.parse_args()
    auth = oss2.Auth(
        os.environ["JIAOTANG_OSS_ACCESS_KEY_ID"],
        os.environ["JIAOTANG_OSS_ACCESS_KEY_SECRET"],
    )
    bucket = oss2.Bucket(
        auth,
        os.environ["JIAOTANG_OSS_ENDPOINT"].rstrip("/"),
        os.environ["JIAOTANG_OSS_BUCKET"],
    )

    current_bytes = noncurrent_bytes = 0
    current_count = noncurrent_count = 0
    forbidden: dict[str, dict[str, int]] = {
        prefix: {"versions": 0, "bytes": 0} for prefix in FORBIDDEN_PREFIXES
    }
    key_marker = versionid_marker = ""
    while True:
        result = bucket.list_object_versions(
            key_marker=key_marker,
            versionid_marker=versionid_marker,
            max_keys=max(1, min(args.max_keys, 1000)),
        )
        for item in result.versions:
            size = int(item.size)
            if item.is_latest:
                current_count += 1
                current_bytes += size
            else:
                noncurrent_count += 1
                noncurrent_bytes += size
            for prefix in FORBIDDEN_PREFIXES:
                if item.key.startswith(prefix):
                    forbidden[prefix]["versions"] += 1
                    forbidden[prefix]["bytes"] += size
        if not result.is_truncated:
            break
        key_marker = result.next_key_marker
        versionid_marker = result.next_versionid_marker

    multipart_uploads = 0
    key_marker = upload_id_marker = ""
    while True:
        result = bucket.list_multipart_uploads(
            key_marker=key_marker,
            upload_id_marker=upload_id_marker,
            max_uploads=1000,
        )
        multipart_uploads += len(result.upload_list)
        if not result.is_truncated:
            break
        key_marker = result.next_key_marker
        upload_id_marker = result.next_upload_id_marker

    stat = bucket.get_bucket_stat()
    report = {
        "bucket": bucket.bucket_name,
        "bucket_stat": {
            "storage_size_in_bytes": int(stat.storage_size_in_bytes),
            "object_count": int(stat.object_count),
            "multipart_upload_count": int(stat.multi_part_upload_count),
            "multipart_part_count": int(stat.multipart_part_count or 0),
            "delete_marker_count": int(stat.delete_marker_count or 0),
        },
        "version_inventory": {
            "current_count": current_count,
            "current_bytes": current_bytes,
            "noncurrent_count": noncurrent_count,
            "noncurrent_bytes": noncurrent_bytes,
            "total_bytes": current_bytes + noncurrent_bytes,
        },
        "forbidden_prefixes": forbidden,
        "listed_multipart_uploads": multipart_uploads,
        "capacity_gate": {
            "max_total_bytes": args.max_total_bytes,
            "reserve_bytes": args.reserve_bytes,
            "projected_total_bytes": (
                current_bytes + noncurrent_bytes + args.reserve_bytes
            ),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    occupied_forbidden = {
        prefix: values for prefix, values in forbidden.items() if values["versions"]
    }
    if multipart_uploads or occupied_forbidden:
        raise SystemExit(
            "容量复核失败：存在未完成分片、快照、server-backups或旧相对路径对象"
        )
    if (
        args.max_total_bytes is not None
        and current_bytes + noncurrent_bytes + args.reserve_bytes
        > args.max_total_bytes
    ):
        raise SystemExit("容量熔断：现有版本加发布预留量将超过OSS容量预算")


if __name__ == "__main__":
    main()

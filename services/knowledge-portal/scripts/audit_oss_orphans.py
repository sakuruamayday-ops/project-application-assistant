from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import oss2


UNMAPPED_ORPHAN_LABEL = "仅OSS可见，现有本地审计资料未映射"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="列出未被当前OSS白名单引用的知识对象，并反查历史路径与清理依据"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument(
        "--manifest-history-dir",
        type=Path,
        required=True,
        help="读取该目录下manifest*.jsonl，用于反查旧内容版本",
    )
    parser.add_argument(
        "--cleanup-audit-root",
        type=Path,
        help="递归读取delete_candidates.jsonl和regenerated_empty_*.jsonl",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--require-no-orphans",
        action="store_true",
        help="写完完整明细后，若仍有孤立对象则退出失败",
    )
    parser.add_argument(
        "--require-no-unmapped-orphans",
        action="store_true",
        help="允许保留可由历史manifest追溯的旧对象，但来源未映射的孤立对象仍退出失败",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def load_expected_shas(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return {
            str(row.get("sha256") or "")
            for row in csv.DictReader(source)
            if str(row.get("object_storage_allowed", "")).lower() == "true"
            and row.get("sha256")
        }


def oss_bucket() -> oss2.Bucket:
    auth = oss2.Auth(
        os.environ["JIAOTANG_OSS_ACCESS_KEY_ID"],
        os.environ["JIAOTANG_OSS_ACCESS_KEY_SECRET"],
    )
    return oss2.Bucket(
        auth,
        os.environ["JIAOTANG_OSS_ENDPOINT"].rstrip("/"),
        os.environ["JIAOTANG_OSS_BUCKET"],
    )


def list_objects_page_with_network_retry(
    prefix: str,
    marker: str,
    *,
    attempts: int | None = None,
) -> object:
    max_attempts = attempts or int(
        os.environ.get("JIAOTANG_OSS_AUDIT_RETRIES", "5")
    )
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return oss_bucket().list_objects(
                prefix=prefix,
                marker=marker,
                max_keys=1000,
            )
        except oss2.exceptions.RequestError as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise
            time.sleep(min(2 ** (attempt - 1), 8))
    assert last_error is not None
    raise last_error


def list_remote_objects(prefix: str) -> list[dict[str, object]]:
    marker = ""
    remote_objects: list[dict[str, object]] = []
    while True:
        result = list_objects_page_with_network_retry(prefix, marker)
        for item in result.object_list:
            remote_objects.append(
                {
                    "object_key": item.key,
                    "sha256": item.key.rsplit("/", 1)[-1],
                    "size_bytes": int(item.size),
                    "last_modified_epoch": int(item.last_modified),
                }
            )
        if not result.is_truncated:
            break
        marker = str(result.next_marker or "")
        if not marker:
            raise RuntimeError("OSS对象清单仍有下一页，但未返回next_marker")
    return remote_objects


def load_history(
    manifest_history_dir: Path,
) -> tuple[
    dict[str, dict[str, set[str]]],
    list[Path],
]:
    history: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {
            "paths": set(),
            "extensions": set(),
            "categories": set(),
            "manifest_files": set(),
        }
    )
    manifest_files = sorted(manifest_history_dir.glob("manifest*.jsonl"))
    for manifest_file in manifest_files:
        for row in read_jsonl(manifest_file):
            digest = str(row.get("sha256") or "")
            if not digest:
                continue
            relative_path = str(row.get("relative_path") or "")
            entry = history[digest]
            if relative_path:
                entry["paths"].add(relative_path)
            extension = str(
                row.get("extension")
                or PurePosixPath(relative_path).suffix
                or ""
            ).lower()
            if extension:
                entry["extensions"].add(extension)
            category = str(
                row.get("top_category")
                or (relative_path.split("/", 1)[0] if relative_path else "")
            )
            if category:
                entry["categories"].add(category)
            entry["manifest_files"].add(manifest_file.name)
    return history, manifest_files


def load_cleanup_audits(
    root: Path | None,
) -> dict[str, list[dict[str, object]]]:
    deleted: dict[str, list[dict[str, object]]] = defaultdict(list)
    if root is None or not root.is_dir():
        return deleted
    audit_files = sorted(root.rglob("delete_candidates.jsonl"))
    audit_files.extend(sorted(root.rglob("regenerated_empty_*.jsonl")))
    for audit_file in audit_files:
        for row in read_jsonl(audit_file):
            digest = str(row.get("sha256") or "")
            if not digest:
                continue
            record = dict(row)
            record["_source_file"] = str(audit_file)
            deleted[digest].append(record)
    return deleted


def classify(
    cleanup_rows: list[dict[str, object]],
    replacements: list[str],
    known_paths: list[str],
) -> str:
    if cleanup_rows and replacements:
        return "本轮已清理，且同路径已有新版"
    if cleanup_rows:
        return "已移入废纸篓的内容"
    if replacements:
        return "当前文件的旧内容版本"
    if known_paths:
        return "历史清单路径已退出当前版本"
    return UNMAPPED_ORPHAN_LABEL


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    expected_shas = load_expected_shas(args.allowlist)
    current_rows = read_jsonl(args.manifest)
    current_by_path = {
        str(row["relative_path"]): row
        for row in current_rows
    }
    history, manifest_files = load_history(args.manifest_history_dir)
    deleted = load_cleanup_audits(args.cleanup_audit_root)

    prefix = os.environ.get("JIAOTANG_OSS_PREFIX", "production").strip("/")
    object_prefix = f"{prefix}/knowledge/objects/"
    remote_objects = list_remote_objects(object_prefix)
    orphan_objects = [
        row for row in remote_objects
        if row["sha256"] not in expected_shas
    ]

    records: list[dict[str, object]] = []
    for orphan in sorted(orphan_objects, key=lambda row: row["object_key"]):
        digest = str(orphan["sha256"])
        historical = history.get(
            digest,
            {
                "paths": set(),
                "extensions": set(),
                "categories": set(),
                "manifest_files": set(),
            },
        )
        cleanup_rows = deleted.get(digest, [])
        cleanup_paths = {
            str(row.get("relative_path") or "")
            for row in cleanup_rows
            if row.get("relative_path")
        }
        known_paths = sorted(historical["paths"] | cleanup_paths)
        replacements = []
        for relative_path in known_paths:
            current = current_by_path.get(relative_path)
            if current and str(current.get("sha256") or "") != digest:
                replacements.append(
                    f"{relative_path} -> {current.get('sha256')}"
                )
        reasons = {
            str(
                row.get("reason")
                or (
                    "regenerated_empty"
                    if "regenerated_empty_" in str(row["_source_file"])
                    else ""
                )
            )
            for row in cleanup_rows
        }
        reasons.discard("")
        extensions = set(historical["extensions"])
        extensions.update(
            PurePosixPath(path).suffix.lower()
            for path in known_paths
            if PurePosixPath(path).suffix
        )
        categories = set(historical["categories"])
        categories.update(
            path.split("/", 1)[0]
            for path in known_paths
            if path
        )
        evidence_files = set(historical["manifest_files"])
        evidence_files.update(
            str(row["_source_file"]) for row in cleanup_rows
        )
        records.append(
            {
                "序号": len(records) + 1,
                "对象键": orphan["object_key"],
                "SHA256": digest,
                "大小_字节": orphan["size_bytes"],
                "大小_MiB": f"{int(orphan['size_bytes']) / 1024 / 1024:.3f}",
                "OSS最后修改时间": datetime.fromtimestamp(
                    int(orphan["last_modified_epoch"]),
                    timezone.utc,
                ).astimezone().isoformat(timespec="seconds"),
                "判定": classify(cleanup_rows, replacements, known_paths),
                "历史或清理路径数量": len(known_paths),
                "历史或清理相对路径": " | ".join(known_paths),
                "当前同路径新版": " | ".join(replacements),
                "清理原因": " | ".join(sorted(reasons)),
                "扩展名": " | ".join(sorted(extensions)),
                "一级目录": " | ".join(sorted(categories)),
                "证据文件": " | ".join(sorted(evidence_files)),
            }
        )

    csv_path = args.output_dir / "oss_orphans_detailed.csv"
    jsonl_path = args.output_dir / "oss_orphans_detailed.jsonl"
    summary_path = args.output_dir / "oss_orphans_summary.md"
    fieldnames = list(records[0]) if records else [
        "序号",
        "对象键",
        "SHA256",
        "大小_字节",
        "大小_MiB",
        "OSS最后修改时间",
        "判定",
        "历史或清理路径数量",
        "历史或清理相对路径",
        "当前同路径新版",
        "清理原因",
        "扩展名",
        "一级目录",
        "证据文件",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    with jsonl_path.open("w", encoding="utf-8") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")

    class_counts = Counter(str(row["判定"]) for row in records)
    class_bytes: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    reason_bytes: Counter[str] = Counter()
    for row in records:
        size = int(row["大小_字节"])
        class_bytes[str(row["判定"])] += size
        for reason in filter(None, str(row["清理原因"]).split(" | ")):
            reason_counts[reason] += 1
            reason_bytes[reason] += size
    total_bytes = sum(int(row["大小_字节"]) for row in records)
    unmapped_records = [
        row for row in records
        if str(row["判定"]) == UNMAPPED_ORPHAN_LABEL
    ]
    lines = [
        "# OSS 孤立知识对象审计",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 当前白名单唯一对象：{len(expected_shas):,}",
        f"- OSS 知识对象：{len(remote_objects):,}",
        f"- 孤立对象：{len(records):,}",
        f"- 来源未映射孤立对象：{len(unmapped_records):,}",
        f"- 孤立对象容量：{total_bytes:,} 字节，{total_bytes / 1_000_000_000:.3f} GB",
        f"- 历史 manifest 样本：{len(manifest_files)} 份",
        "",
        "## 按判定分类",
        "",
        "| 判定 | 对象数 | 容量 GB |",
        "|---|---:|---:|",
    ]
    for label, count in class_counts.most_common():
        lines.append(
            f"| {label} | {count:,} | {class_bytes[label] / 1_000_000_000:.3f} |"
        )
    lines.extend(
        [
            "",
            "## 按清理原因",
            "",
            "| 原因 | 对象数 | 容量 GB |",
            "|---|---:|---:|",
        ]
    )
    for reason, count in reason_counts.most_common():
        lines.append(
            f"| {reason} | {count:,} | {reason_bytes[reason] / 1_000_000_000:.3f} |"
        )
    lines.extend(
        [
            "",
            "## 明细文件",
            "",
            f"- CSV：`{csv_path}`",
            f"- JSONL：`{jsonl_path}`",
            "",
            "说明：一个内容哈希可能对应多个历史路径。未执行任何删除。",
        ]
    )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "expected_unique_objects": len(expected_shas),
                "remote_objects": len(remote_objects),
                "orphan_objects": len(records),
                "unmapped_orphan_objects": len(unmapped_records),
                "orphan_bytes": total_bytes,
                "csv": str(csv_path),
                "jsonl": str(jsonl_path),
                "summary": str(summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.require_no_orphans and records:
        raise SystemExit(
            f"发现{len(records)}个孤立对象；完整待确认名单：{csv_path}"
        )
    if args.require_no_unmapped_orphans and unmapped_records:
        raise SystemExit(
            f"发现{len(unmapped_records)}个来源未映射孤立对象；"
            f"完整待确认名单：{csv_path}"
        )
    if args.require_no_unmapped_orphans and records:
        print(
            f"历史可追溯对象保留：{len(records)}，来源未映射：0；"
            "未执行任何删除。"
        )


if __name__ == "__main__":
    main()

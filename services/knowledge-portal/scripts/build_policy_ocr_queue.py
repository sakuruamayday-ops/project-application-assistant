#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path


CURRENT_YEAR_PATTERN = re.compile(r"202[56]年|202[56]-")
HISTORICAL_YEAR_PATTERN = re.compile(r"20(?:0\d|1\d|2[0-4])年|20(?:0\d|1\d|2[0-4])-")


def priority(relative_path: str) -> tuple[str, str]:
    name = Path(relative_path).name
    if "申报通知" in relative_path and CURRENT_YEAR_PATTERN.search(relative_path):
        return "P0", "2025—2026年申报通知"
    if any(keyword in name for keyword in ("管理办法", "实施办法", "评价办法", "认定办法")):
        return "P0", "管理办法或认定规则"
    if "公示公告" in relative_path:
        return "P1", "公示、认定或复核名单"
    if any(keyword in relative_path for keyword in ("目录", "指南", "指引")):
        return "P2", "产业、产品、领域目录或办事指南"
    if HISTORICAL_YEAR_PATTERN.search(relative_path):
        return "P3", "历史年度资料，OCR后必须核验效力"
    return "P2", "其他政策与规则资料"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.report.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = [
            row
            for row in csv.DictReader(handle)
            if row["status"] == "ocr_required"
            and row["relative_path"].startswith("10_政策与目录/")
        ]

    selected: dict[str, dict[str, str]] = {}
    aliases: dict[str, list[str]] = {}
    for row in source_rows:
        digest = row["sha256"]
        aliases.setdefault(digest, []).append(row["relative_path"])
        current = selected.get(digest)
        if current is None or priority(row["relative_path"])[0] < priority(current["relative_path"])[0]:
            selected[digest] = row

    queue = []
    for digest, row in selected.items():
        level, reason = priority(row["relative_path"])
        queue.append(
            {
                "优先级": level,
                "优先原因": reason,
                "源文件": str(args.knowledge_root / row["relative_path"]),
                "相对路径": row["relative_path"],
                "SHA256": digest,
                "别名路径数": len(aliases[digest]),
                "别名路径": " | ".join(aliases[digest]),
            }
        )
    queue.sort(key=lambda item: (item["优先级"], item["相对路径"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(queue[0]))
        writer.writeheader()
        writer.writerows(queue)
    print(f"queue={len(queue)} source_paths={len(source_rows)} aliases={len(source_rows)-len(queue)}")


if __name__ == "__main__":
    main()

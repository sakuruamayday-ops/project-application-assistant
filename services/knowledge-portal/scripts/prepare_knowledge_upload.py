from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SYSTEM_DIRS = {
    "$RECYCLE.BIN",
    ".fseventsd",
    ".Spotlight-V100",
    ".TemporaryItems",
    ".Trashes",
    "System Volume Information",
}
SYSTEM_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
OUTPUT_DIR_NAME = "_云端迁移索引"

ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz"}
MEDIA_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".mov", ".avi", ".wav"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
DIRECT_TEXT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".xlsm",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".jsonl",
    ".html",
    ".xml",
    ".yaml",
    ".yml",
}
CONVERT_EXTENSIONS = {".doc", ".xls", ".ppt", ".wps", ".docm"}

PUBLIC_TERMS = (
    "政策",
    "通知",
    "指南",
    "办法",
    "细则",
    "公示",
    "名单",
    "目录",
    "标准",
    "工作指引",
)
CONFIDENTIAL_TERMS = (
    "身份证",
    "护照",
    "手机号",
    "通讯录",
    "银行流水",
    "银行卡",
    "工资",
    "社保",
    "劳动合同",
    "审计报告",
    "纳税",
    "发票",
    "销售合同",
    "采购合同",
    "客户名单",
    "股东",
    "财务",
)
CASE_TERMS = (
    "申报书",
    "申请书",
    "终稿",
    "装订材料",
    "上报稿",
    "提交稿",
    "佐证",
    "附件材料",
    "验收材料",
)
RULE_TERMS = ("申报指南", "申报通知", "管理办法", "实施细则", "评价标准", "认定办法")
TRAINING_TERMS = ("培训", "答辩", "模板", "范例", "谈单", "介绍ppt", "课件")

PROJECT_CATEGORY_MAP = {
    "1.谈单资料": "60_模板培训",
    "各类答辩ppt": "60_模板培训",
    "专利": "70_知识产权",
    "专精特新和小巨人公示名单与认定名单": "50_名单与对标",
    "政策数据库": "10_政策与通知",
}
PACKAGE_LAYER_ROLES = {
    "00_系统与索引": "00_系统元数据",
    "10_政策与目录": "10_政策与通知",
    "20_申报指南与规则": "20_项目规则与指南",
    "30_空白模板": "30_空白模板",
    "40_内部培训与方法": "40_内部培训与方法",
    "50_名单与对标": "50_名单与对标",
    "60_脱敏案例": "60_脱敏案例",
    "60_申报案例与建设方案": "60_申报案例与建设方案",
    "70_知识产权方法": "70_知识产权方法",
    "90_受限资料": "90_受限资料",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成知识库上云清单和本地元数据索引")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_KNOWLEDGE_ROOT", Path.cwd() / "knowledge")))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-hash", action="store_true")
    return parser.parse_args()


def is_system_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if not relative.parts:
        return False
    if relative.parts[0] == OUTPUT_DIR_NAME:
        return True
    if any(part in SYSTEM_DIRS for part in relative.parts):
        return True
    return path.name in SYSTEM_FILES or path.name.startswith("._")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def classify_role(relative_path: str, top_category: str) -> str:
    if top_category in PACKAGE_LAYER_ROLES:
        return PACKAGE_LAYER_ROLES[top_category]
    text = relative_path.lower()
    if any(term.lower() in text for term in RULE_TERMS):
        return "20_项目规则与指南"
    if any(term.lower() in text for term in CASE_TERMS):
        return "30_申报案例"
    if any(term.lower() in text for term in TRAINING_TERMS):
        return "60_模板培训"
    if "名单" in text or "公示" in text:
        return "50_名单与对标"
    if "专利" in text or "软著" in text or "商标" in text:
        return "70_知识产权"
    if any(term.lower() in text for term in PUBLIC_TERMS):
        return "10_政策与通知"
    if top_category in PROJECT_CATEGORY_MAP:
        return PROJECT_CATEGORY_MAP[top_category]
    return "40_项目与客户资料"


def classify_sensitivity(relative_path: str, role: str) -> str:
    if role == "90_受限资料":
        return "restricted"
    if role == "00_系统元数据":
        return "internal_metadata"
    text = relative_path.lower()
    if any(term.lower() in text for term in CONFIDENTIAL_TERMS):
        return "confidential"
    if role in {"10_政策与通知", "20_项目规则与指南", "50_名单与对标"}:
        return "public_reference"
    return "internal"


def classify_index_mode(extension: str) -> str:
    if extension in ARCHIVE_EXTENSIONS or extension in MEDIA_EXTENSIONS:
        return "archive_only"
    if extension in IMAGE_EXTENSIONS:
        return "ocr_required"
    if extension in DIRECT_TEXT_EXTENSIONS:
        return "extract_text"
    if extension in CONVERT_EXTENSIONS:
        return "convert_required"
    return "manual_review"


def upload_priority(role: str, sensitivity: str, index_mode: str) -> int:
    if index_mode == "archive_only":
        return 6
    if index_mode in {"ocr_required", "convert_required", "manual_review"}:
        return 5
    if sensitivity == "confidential":
        return 4
    return {
        "10_政策与通知": 1,
        "20_项目规则与指南": 1,
        "50_名单与对标": 2,
        "30_申报案例": 3,
        "60_模板培训": 3,
        "60_申报案例与建设方案": 3,
        "70_知识产权": 3,
        "40_项目与客户资料": 4,
    }.get(role, 5)


def duplicate_preference(record: dict[str, object]) -> tuple[int, int, str]:
    name = str(record["name"]).lower()
    penalty = 0
    if any(term in name for term in ("副本", "copy", "复件", "备份")):
        penalty += 5
    if re.search(r"\([1-9]\)|（[1-9]）|_[1-9](?=\.)", name):
        penalty += 2
    return penalty, len(str(record["relative_path"])), str(record["relative_path"])


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_database(path: Path, records: list[dict[str, object]]) -> None:
    with tempfile.TemporaryDirectory(prefix="jiaotang-kb-index-") as directory:
        temporary_path = Path(directory) / path.name
        connection = sqlite3.connect(temporary_path)
        try:
            connection.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                source_path TEXT NOT NULL UNIQUE,
                relative_path TEXT NOT NULL,
                cloud_path TEXT NOT NULL,
                name TEXT NOT NULL,
                extension TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                modified_at TEXT NOT NULL,
                sha256 TEXT,
                top_category TEXT NOT NULL,
                document_role TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                index_mode TEXT NOT NULL,
                upload_priority INTEGER NOT NULL,
                upload_action TEXT NOT NULL,
                canonical_path TEXT
            );
            CREATE INDEX documents_priority_idx ON documents(upload_priority, document_role);
            CREATE INDEX documents_hash_idx ON documents(sha256);
            CREATE INDEX documents_category_idx ON documents(top_category);
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                name,
                relative_path,
                cloud_path,
                top_category,
                document_role,
                content='documents',
                content_rowid='id',
                tokenize='unicode61'
            );
            """
        )
            columns = [
            "source_path",
            "relative_path",
            "cloud_path",
            "name",
            "extension",
            "size_bytes",
            "modified_at",
            "sha256",
            "top_category",
            "document_role",
            "sensitivity",
            "index_mode",
            "upload_priority",
            "upload_action",
            "canonical_path",
        ]
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f"INSERT INTO documents ({','.join(columns)}) VALUES ({placeholders})",
                ([record[column] for column in columns] for record in records),
            )
            connection.execute(
                "INSERT INTO documents_fts(rowid,name,relative_path,cloud_path,top_category,document_role) "
                "SELECT id,name,relative_path,cloud_path,top_category,document_role FROM documents"
            )
            connection.commit()
        finally:
            connection.close()
        shutil.copy2(temporary_path, path)


def main() -> None:
    args = parse_args()
    root = args.root.expanduser().resolve()
    output = (args.output or root / OUTPUT_DIR_NAME).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    hash_cache: dict[tuple[str, int, str], str] = {}
    previous_manifest = output / "manifest.jsonl"
    if previous_manifest.exists():
        for line in previous_manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                item = json.loads(line)
                if item.get("sha256"):
                    hash_cache[
                        (item["relative_path"], int(item["size_bytes"]), item["modified_at"])
                    ] = item["sha256"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue

    records: list[dict[str, object]] = []
    skipped_system = 0
    unreadable: list[str] = []
    for current_root, directories, files in os.walk(root):
        current = Path(current_root)
        directories[:] = [
            directory
            for directory in directories
            if directory not in SYSTEM_DIRS and directory != OUTPUT_DIR_NAME
        ]
        for filename in files:
            path = current / filename
            if is_system_path(path, root):
                skipped_system += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                unreadable.append(str(path.relative_to(root)))
                continue
            relative = path.relative_to(root).as_posix()
            top_category = relative.split("/", 1)[0] if "/" in relative else "根目录"
            extension = path.suffix.lower()
            role = classify_role(relative, top_category)
            sensitivity = classify_sensitivity(relative, role)
            index_mode = classify_index_mode(extension)
            priority = upload_priority(role, sensitivity, index_mode)
            records.append(
                {
                    "source_path": str(path),
                    "relative_path": relative,
                    "cloud_path": f"{role}/{relative}",
                    "name": filename,
                    "extension": extension or "[无扩展名]",
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "sha256": "",
                    "top_category": top_category,
                    "document_role": role,
                    "sensitivity": sensitivity,
                    "index_mode": index_mode,
                    "upload_priority": priority,
                    "upload_action": (
                        "restricted_excluded"
                        if role == "90_受限资料"
                        else "metadata_only"
                        if role == "00_系统元数据"
                        else "upload"
                    ),
                    "canonical_path": relative,
                }
            )

    if not args.no_hash:
        for record in records:
            cache_key = (
                str(record["relative_path"]),
                int(record["size_bytes"]),
                str(record["modified_at"]),
            )
            if cache_key in hash_cache:
                record["sha256"] = hash_cache[cache_key]
                continue
            try:
                record["sha256"] = sha256_file(Path(str(record["source_path"])))
            except OSError:
                unreadable.append(str(record["relative_path"]))

    hash_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        digest = str(record["sha256"])
        if digest:
            hash_groups[digest].append(record)

    duplicate_rows: list[dict[str, object]] = []
    duplicate_sets = 0
    duplicate_bytes = 0
    for digest, group in hash_groups.items():
        if len(group) < 2:
            continue
        duplicate_sets += 1
        canonical = min(group, key=duplicate_preference)
        for record in group:
            record["canonical_path"] = canonical["relative_path"]
            if record is canonical:
                continue
            record["upload_action"] = "reference_duplicate"
            duplicate_bytes += int(record["size_bytes"])
            duplicate_rows.append(
                {
                    "sha256": digest,
                    "size_bytes": record["size_bytes"],
                    "canonical_path": canonical["relative_path"],
                    "duplicate_path": record["relative_path"],
                }
            )

    records.sort(
        key=lambda item: (
            int(item["upload_priority"]),
            str(item["document_role"]),
            str(item["top_category"]),
            str(item["relative_path"]),
        )
    )

    manifest_fields = [
        "upload_priority",
        "upload_action",
        "document_role",
        "sensitivity",
        "index_mode",
        "top_category",
        "name",
        "extension",
        "size_bytes",
        "modified_at",
        "sha256",
        "relative_path",
        "cloud_path",
        "canonical_path",
        "source_path",
    ]
    write_csv(output / "manifest.csv", records, manifest_fields)
    with (output / "manifest.jsonl").open("w", encoding="utf-8") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")
    write_csv(
        output / "duplicates.csv",
        duplicate_rows,
        ["sha256", "size_bytes", "canonical_path", "duplicate_path"],
    )
    build_database(output / "knowledge_inventory.sqlite3", records)

    batch_counts = Counter((int(item["upload_priority"]), str(item["document_role"])) for item in records)
    batch_sizes = Counter()
    for item in records:
        if item["upload_action"] == "upload":
            batch_sizes[(int(item["upload_priority"]), str(item["document_role"]))] += int(item["size_bytes"])
    batch_rows = [
        {
            "upload_priority": priority,
            "document_role": role,
            "file_count": count,
            "upload_bytes_after_dedup": batch_sizes[(priority, role)],
        }
        for (priority, role), count in sorted(batch_counts.items())
    ]
    write_csv(
        output / "upload_batches.csv",
        batch_rows,
        ["upload_priority", "document_role", "file_count", "upload_bytes_after_dedup"],
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "files": len(records),
        "bytes": sum(int(item["size_bytes"]) for item in records),
        "bytes_after_dedup": sum(
            int(item["size_bytes"]) for item in records if item["upload_action"] == "upload"
        ),
        "system_files_skipped": skipped_system,
        "unreadable_files": len(set(unreadable)),
        "duplicate_sets": duplicate_sets,
        "duplicate_files": len(duplicate_rows),
        "duplicate_bytes": duplicate_bytes,
        "roles": dict(Counter(str(item["document_role"]) for item in records)),
        "sensitivity": dict(Counter(str(item["sensitivity"]) for item in records)),
        "index_modes": dict(Counter(str(item["index_mode"]) for item in records)),
        "priorities": dict(Counter(str(item["upload_priority"]) for item in records)),
        "unreadable_paths": sorted(set(unreadable)),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "README.md").write_text(
        """# 知识库上云迁移索引

本目录由 `prepare_knowledge_upload.py` 生成。原文件不移动、不重命名、不删除。

## 上传顺序

1. 政策、通知、项目规则与申报指南
2. 公示名单与同行对标资料
3. 申报案例、模板培训和知识产权资料
4. 项目与客户资料及保密资料
5. 需要 OCR、格式转换或人工确认的文件
6. 压缩包和音视频等只归档、不直接进入全文检索的文件

## 文件说明

- `manifest.csv`：可人工查看和筛选的完整清单。
- `manifest.jsonl`：供上传脚本和知识服务读取。
- `upload_batches.csv`：按优先级汇总的上传批次。
- `duplicates.csv`：完全相同文件的规范副本与别名关系。
- `knowledge_inventory.sqlite3`：支持文件名、路径和分类全文检索的本地索引。
- `summary.json`：盘点统计与异常记录。

运行 `build_knowledge_content_index.py` 后还会生成：

- `documents.jsonl`：云端知识服务的全文导入源。
- `knowledge_content.sqlite3`：本地全文检索索引。
- `extraction_report.csv`：逐文件提取状态及 OCR、转换、修复队列。
- `extraction_summary.json`：全文覆盖率汇总。
- `policy_versions.csv`：政策版本状态、前后版本和最新版本关联。
- `policy_versions.sqlite3`：可检索的政策版本关系库。
- `documents_with_versions.jsonl`：包含版本关系的云端导入源。
- `policy_version_groups.jsonl`：版本组和明确替代关系。
- `shichen_import_executed.csv`：石晨硬盘精选导入、重复引用和排除原因。
- `shichen_disk_cloud_review.md`：石晨硬盘的上云价值和敏感边界评审。

规范化云端入口位于 `../_云端知识库`，按政策、指南、模板、内部方法、名单、脱敏案例和受限资料分层。旧目录保持原位，不移动、不删除。

政策版本记录同时包含原文证据类型、原文摘录、证据来源、明确替代的政策名称、被替代来源、替代依据和状态来源。只有 `explicit_original_text` 可视为原文明示；`chronology_inference` 仅为时间顺序候选。

`reference_duplicate` 只表示云端可复用同一对象，不会删除本地重复文件。云端必须保留原始路径、哈希、敏感级别、更新时间和规范副本关系。
""",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

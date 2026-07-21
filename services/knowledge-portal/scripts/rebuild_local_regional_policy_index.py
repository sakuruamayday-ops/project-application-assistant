from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_knowledge_content_index import DEFAULT_CACHE_PATH, cache_status_reusable, extract


DEFAULT_SOURCE_ROOT = Path(
    "/Volumes/知识库/_云端知识库/10_政策与目录/政策数据库/企策顾问"
)
DEFAULT_INDEX_ROOT = Path("/Volumes/知识库/_云端迁移索引")
SUPPORTED_CONTENT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".json",
    ".md",
    ".pdf",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
}
CONTROL_FILES = {
    "README.md",
    "整理摘要.json",
    "网站上传索引.csv",
    "网站上传索引.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="重建四市政策资料的本地全文与元数据索引")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_extraction_cache(path: Path) -> dict[str, tuple[str, str]]:
    cache: dict[str, tuple[str, str]] = {}
    if not path.is_file():
        return cache
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            record = json.loads(line)
            status = str(record["status"])
            if cache_status_reusable(status):
                cache[str(record["sha256"])] = (str(record["text"]), status)
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
    return cache


def append_extraction_cache(path: Path, sha256: str, text: str, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as target:
        target.write(
            json.dumps(
                {"sha256": sha256, "status": status, "text": text},
                ensure_ascii=False,
            )
            + "\n"
        )


def relative_source(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root).as_posix()
    return f"政策数据库/企策顾问/{relative}"


def path_metadata(path: Path, source_root: Path) -> dict[str, str]:
    parts = path.relative_to(source_root).parts
    file_type = parts[0] if len(parts) > 0 else "政策资料"
    city = parts[1] if len(parts) > 1 else ""
    category = parts[2] if len(parts) > 2 else "综合政策"
    project_directory = parts[3] if len(parts) > 3 else path.parent.name
    project_title = project_directory
    if "__" in project_directory:
        segments = project_directory.split("__")
        if len(segments) >= 2:
            project_title = segments[1]
    title = project_title
    if path.name not in {"项目说明.md", "通知原文.md"}:
        title = f"{project_title}—{path.name}"
    return {
        "file_type": file_type,
        "city": city,
        "category": category,
        "project_title": project_title,
        "title": title,
    }


def contextualize(text: str, metadata: dict[str, str]) -> str:
    context = "\n".join(
        (
            f"归档地区：{metadata['city']}",
            f"文件类型：{metadata['file_type']}",
            f"项目类别：{metadata['category']}",
            f"项目标题：{metadata['project_title']}",
        )
    )
    return f"{context}\n\n{text}".strip()


def inventory_mode(extension: str) -> str:
    if extension in SUPPORTED_CONTENT_EXTENSIONS:
        return "extract_text"
    return "archive_only"


def scan_files(source_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in source_root.rglob("*"):
        if not path.is_file() or path.name.startswith("._") or path.name in CONTROL_FILES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.as_posix())


def rebuild_content_database(
    database_path: Path,
    files: list[Path],
    source_root: Path,
    extraction_cache: dict[str, tuple[str, str]],
    cache_path: Path,
) -> tuple[Counter[str], int]:
    status_counts: Counter[str] = Counter()
    indexed = 0
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DELETE FROM documents WHERE source LIKE '政策数据库/企策顾问/%'")
        for position, path in enumerate(files, start=1):
            extension = path.suffix.lower()
            if extension not in SUPPORTED_CONTENT_EXTENSIONS:
                status_counts["archive_only"] += 1
                continue
            sha256 = sha256_file(path)
            if sha256 in extraction_cache:
                text, status = extraction_cache[sha256]
            else:
                try:
                    text, status = extract(path, extension)
                except Exception as error:
                    text, status = "", f"error:{type(error).__name__}"
                append_extraction_cache(cache_path, sha256, text, status)
                if cache_status_reusable(status):
                    extraction_cache[sha256] = (text, status)
            status_counts[status] += 1
            if status != "indexed":
                continue
            metadata = path_metadata(path, source_root)
            source = relative_source(path, source_root)
            updated_at = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat()
            source_key = hashlib.sha256(f"regional-policy:{source}".encode()).hexdigest()
            connection.execute(
                """
                INSERT INTO documents(
                    source_key,title,content,source,cloud_path,document_role,
                    sensitivity,sha256,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    source_key,
                    metadata["title"],
                    contextualize(text, metadata),
                    source,
                    f"10_政策与通知/{source}",
                    "10_政策与通知",
                    "public_reference",
                    sha256,
                    updated_at,
                ),
            )
            indexed += 1
            if position % 500 == 0:
                print(f"content_processed={position}/{len(files)} indexed={indexed}", flush=True)
        connection.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"全文索引完整性检查失败：{integrity}")
    finally:
        connection.close()
    return status_counts, indexed


def rebuild_inventory_database(
    database_path: Path,
    files: list[Path],
    source_root: Path,
) -> None:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DELETE FROM documents WHERE relative_path LIKE '政策数据库/企策顾问/%'")
        for position, path in enumerate(files, start=1):
            source = relative_source(path, source_root)
            extension = path.suffix.lower()
            stat = path.stat()
            connection.execute(
                """
                INSERT INTO documents(
                    source_path,relative_path,cloud_path,name,extension,size_bytes,
                    modified_at,sha256,top_category,document_role,sensitivity,
                    index_mode,upload_priority,upload_action,canonical_path
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(path),
                    source,
                    f"10_政策与通知/{source}",
                    path.name,
                    extension,
                    stat.st_size,
                    datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    None,
                    "政策数据库",
                    "10_政策与通知",
                    "public_reference",
                    inventory_mode(extension),
                    1,
                    "upload",
                    source,
                ),
            )
            if position % 1000 == 0:
                print(f"inventory_processed={position}/{len(files)}", flush=True)
        connection.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"元数据索引完整性检查失败：{integrity}")
    finally:
        connection.close()


def replace_with_backup(source: Path, rebuilt: Path, backup_root: Path, stamp: str) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"{source.stem}.before-regional-policy-{stamp}{source.suffix}"
    shutil.copy2(source, backup)
    staged = source.with_name(f".{source.name}.regional-policy-{stamp}.new")
    shutil.copy2(rebuilt, staged)
    staged.replace(source)
    return backup


def main() -> None:
    args = parse_args()
    source_root = args.source_root.expanduser().resolve()
    index_root = args.index_root.expanduser().resolve()
    cache_path = args.cache.expanduser().resolve()
    content_database = index_root / "knowledge_content.sqlite3"
    inventory_database = index_root / "knowledge_inventory.sqlite3"
    if not source_root.is_dir():
        raise SystemExit(f"政策资料目录不存在：{source_root}")
    if not content_database.is_file() or not inventory_database.is_file():
        raise SystemExit("本地全文或元数据索引不存在")

    files = scan_files(source_root)
    extraction_cache = load_extraction_cache(cache_path)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    with tempfile.TemporaryDirectory(prefix="regional-policy-index-") as temporary:
        temporary_root = Path(temporary)
        rebuilt_content = temporary_root / content_database.name
        rebuilt_inventory = temporary_root / inventory_database.name
        shutil.copy2(content_database, rebuilt_content)
        shutil.copy2(inventory_database, rebuilt_inventory)
        status_counts, indexed = rebuild_content_database(
            rebuilt_content,
            files,
            source_root,
            extraction_cache,
            cache_path,
        )
        rebuild_inventory_database(rebuilt_inventory, files, source_root)
        backup_root = index_root / "backups"
        content_backup = replace_with_backup(
            content_database, rebuilt_content, backup_root, stamp
        )
        inventory_backup = replace_with_backup(
            inventory_database, rebuilt_inventory, backup_root, stamp
        )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "scanned_files": len(files),
        "indexed_documents": indexed,
        "status_counts": dict(status_counts),
        "content_backup": str(content_backup),
        "inventory_backup": str(inventory_backup),
    }
    summary_path = index_root / "regional_policy_2025plus_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

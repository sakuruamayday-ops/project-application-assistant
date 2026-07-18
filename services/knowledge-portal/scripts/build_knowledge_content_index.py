from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


MAX_TEXT_CHARS = 200_000
MIN_TEXT_CHARS = 40
DEFAULT_CACHE_PATH = Path(
    os.environ.get(
        "JIAOTANG_EXTRACTION_CACHE",
        Path.home() / ".cache/project-application-assistant/knowledge-extraction-cache.jsonl",
    )
)
LEGACY_CONVERSION_ROOT = Path(
    os.environ.get(
        "JIAOTANG_LEGACY_CONVERSION_ROOT",
        Path.home() / ".cache/project-application-assistant/legacy-office-conversion",
    )
)
SOFFICE = Path(os.environ.get("SOFFICE_PATH") or shutil.which("soffice") or "soffice")
ENTERPRISE_PATTERN = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9（）()·—\-]{2,80}?"
    r"(?:股份有限公司|有限责任公司|集团有限公司|有限公司)"
)
HTML_ROW_PATTERN = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
HTML_CELL_PATTERN = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def cache_status_reusable(status: str) -> bool:
    return status in {"indexed", "unrecoverable_corrupt"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从知识库清单生成全文索引和云端导入文件")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(os.environ.get("JIAOTANG_MANIFEST_PATH", Path.cwd() / "knowledge-migration/manifest.jsonl")),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    return parser.parse_args()


def clean_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\x00", " ").splitlines()]
    return "\n".join(line for line in lines if line).strip()[:MAX_TEXT_CHARS]


def extract_pdf(path: Path) -> str:
    parts: list[str] = []
    character_count = 0
    try:
        import fitz
    except ImportError:
        from pypdf import PdfReader

        document = PdfReader(path)
        for page in document.pages:
            page_text = page.extract_text() or ""
            parts.append(page_text)
            character_count += len(page_text)
            if character_count >= MAX_TEXT_CHARS:
                break
    else:
        fitz.TOOLS.mupdf_display_errors(False)
        fitz.TOOLS.mupdf_display_warnings(False)
        with fitz.open(path) as document:
            for page in document:
                page_text = page.get_text("text")
                parts.append(page_text)
                character_count += len(page_text)
                if character_count >= MAX_TEXT_CHARS:
                    break
    return clean_text("\n".join(parts))


def extract_pdf_isolated(path: Path) -> str:
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--extract-pdf-worker", str(path)],
        capture_output=True,
        check=False,
        timeout=45,
    )
    if process.returncode != 0:
        return ""
    return process.stdout.decode("utf-8", errors="ignore")[:MAX_TEXT_CHARS]


def extract_docx(path: Path) -> str:
    from docx import Document

    document = Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return clean_text("\n".join(parts))


def extract_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(path.open("rb"), data_only=True, read_only=True)
    parts: list[str] = []
    character_count = 0
    try:
        for sheet in workbook.worksheets:
            parts.append(f"工作表：{sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                line = " | ".join("" if value is None else str(value) for value in row)
                if line.strip(" |"):
                    parts.append(line)
                    character_count += len(line)
                if character_count >= MAX_TEXT_CHARS:
                    return clean_text("\n".join(parts))
    finally:
        workbook.close()
    return clean_text("\n".join(parts))


def extract_xls(path: Path) -> str:
    import xlrd

    workbook = xlrd.open_workbook(path, on_demand=True)
    parts: list[str] = []
    character_count = 0
    try:
        for sheet_name in workbook.sheet_names():
            sheet = workbook.sheet_by_name(sheet_name)
            parts.append(f"工作表：{sheet_name}")
            for row_index in range(sheet.nrows):
                line = " | ".join(str(value) for value in sheet.row_values(row_index))
                parts.append(line)
                character_count += len(line)
                if character_count >= MAX_TEXT_CHARS:
                    return clean_text("\n".join(parts))
    finally:
        workbook.release_resources()
    return clean_text("\n".join(parts))


def extract_pptx(path: Path) -> str:
    from pptx import Presentation

    presentation = Presentation(path)
    parts: list[str] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_parts: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_parts.append(shape.text)
        if slide_parts:
            parts.append(f"第{slide_number}页\n" + "\n".join(slide_parts))
    return clean_text("\n".join(parts))


def extract_legacy_office(path: Path) -> str:
    process = subprocess.run(
        ["/usr/bin/textutil", "-convert", "txt", "-stdout", str(path)],
        capture_output=True,
        check=False,
        timeout=120,
    )
    text = clean_text(process.stdout.decode("utf-8", errors="ignore"))
    if process.returncode == 0 and len(text) >= MIN_TEXT_CHARS:
        return text

    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    output = LEGACY_CONVERSION_ROOT / digest
    output.mkdir(parents=True, exist_ok=True)
    target_extension = ".pptx" if path.suffix.lower() == ".ppt" else ".docx"
    converted = output / f"{path.stem}{target_extension}"
    if not converted.exists() and SOFFICE.exists():
        subprocess.run(
            [
                str(SOFFICE), "--headless", "--convert-to", target_extension.lstrip("."),
                "--outdir", str(output), str(path),
            ],
            capture_output=True,
            check=False,
            timeout=240,
        )
    if not converted.exists():
        return ""
    if target_extension == ".pptx":
        return extract_pptx(converted)
    return extract_docx(converted)


def extract_plain(path: Path) -> str:
    return clean_text(path.read_text(encoding="utf-8", errors="ignore"))


def flatten_plist(value: object) -> list[str]:
    if isinstance(value, dict):
        parts: list[str] = []
        for key, child in value.items():
            parts.append(str(key))
            parts.extend(flatten_plist(child))
        return parts
    if isinstance(value, list):
        parts = []
        for child in value:
            parts.extend(flatten_plist(child))
        return parts
    if isinstance(value, bytes):
        return [value.decode("utf-8", errors="ignore")]
    return [str(value)]


def extract_manual(path: Path) -> tuple[str, str]:
    if path.name == ".WeDrive":
        return "", "non_content_placeholder"
    if ".obsidian/plugins" in path.as_posix():
        return "", "non_content_placeholder"
    extension = path.suffix.lower()
    if extension in {".js", ".css"}:
        text = extract_plain(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty_non_content"
    if extension == ".textclipping":
        try:
            text = clean_text("\n".join(flatten_plist(plistlib.loads(path.read_bytes()))))
        except Exception:
            text = ""
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty_non_content"
    if extension == ".emmx":
        parts: list[str] = []
        try:
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.lower().endswith((".xml", ".json", ".txt")):
                        parts.append(archive.read(name).decode("utf-8", errors="ignore"))
        except zipfile.BadZipFile:
            pass
        text = clean_text("\n".join(parts))
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty_non_content"

    header = path.read_bytes()[:8]
    if header.startswith(b"%PDF"):
        text = extract_pdf_isolated(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "ocr_required"
    if header.startswith(b"PK"):
        try:
            text = extract_docx(path)
        except Exception:
            text = ""
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "convert_required"
    if header.startswith(bytes.fromhex("d0cf11e0")):
        text = extract_legacy_office(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "convert_required"
    return "", "non_content_manual_review"


def extract(path: Path, extension: str) -> tuple[str, str]:
    header = path.read_bytes()[:8]
    if extension == ".pdf":
        text = extract_pdf_isolated(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "ocr_required"
    if extension in {".docx", ".docm"}:
        if header.startswith(bytes.fromhex("d0cf11e0")) or extension == ".docm":
            text = extract_legacy_office(path)
        else:
            try:
                text = extract_docx(path)
            except (ValueError, zipfile.BadZipFile):
                text = extract_legacy_office(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty"
    if extension in {".xlsx", ".xlsm"}:
        text = extract_xls(path) if header.startswith(bytes.fromhex("d0cf11e0")) else extract_xlsx(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty"
    if extension == ".xls":
        text = extract_xlsx(path) if header.startswith(b"PK") else extract_xls(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty"
    if extension == ".pptx":
        text = extract_pptx(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty"
    if extension in {".doc", ".ppt", ".wps"}:
        text = extract_legacy_office(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty_non_content"
    if extension in {
        ".txt",
        ".md",
        ".csv",
        ".json",
        ".jsonl",
        ".html",
        ".xml",
        ".yaml",
        ".yml",
    }:
        text = extract_plain(path)
        return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty"
    if header and not header.startswith((b"PK", b"%PDF", bytes.fromhex("d0cf11e0"))):
        raw = path.read_bytes()
        for encoding in ("utf-8", "gb18030"):
            try:
                text = clean_text(raw.decode(encoding))
                return text, "indexed" if len(text) >= MIN_TEXT_CHARS else "empty_non_content"
            except UnicodeDecodeError:
                continue
    return "", "not_text"


def iter_chunks(text: str, size: int = 1_200, overlap: int = 180):
    if not text:
        return
    start = 0
    chunk_number = 1
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind("。", start, end))
            if boundary > start + size // 2:
                end = boundary + 1
        yield chunk_number, text[start:end]
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        chunk_number += 1


def enterprise_mentions(text: str) -> list[tuple[str, str, str]]:
    mentions: list[tuple[str, str, str]] = []
    previous_sequence = ""
    seen: set[tuple[str, str]] = set()

    for row_html in HTML_ROW_PATTERN.findall(text):
        cells = [
            html.unescape(HTML_TAG_PATTERN.sub("", cell)).strip()
            for cell in HTML_CELL_PATTERN.findall(row_html)
        ]
        sequence = cells[0] if cells and cells[0].isdigit() else ""
        context = " | ".join(cells)[:500]
        for cell in cells:
            for match in ENTERPRISE_PATTERN.finditer(cell):
                name = match.group(0).strip(" ：:，,、；;。")
                key = (name, sequence)
                if len(name) >= 6 and key not in seen:
                    seen.add(key)
                    mentions.append((name, sequence, context))

    plain_text = HTML_ROW_PATTERN.sub("", text)
    for line in plain_text.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            previous_sequence = stripped
            continue
        cells = [cell.strip() for cell in stripped.split("|")]
        sequence = cells[0] if cells and cells[0].isdigit() else previous_sequence
        for match in ENTERPRISE_PATTERN.finditer(stripped):
            name = match.group(0).strip(" ：:，,、；;。")
            name = re.sub(r"^\d+[.、\s]*", "", name)
            key = (name, sequence)
            if len(name) < 6 or key in seen:
                continue
            seen.add(key)
            mentions.append((name, sequence, stripped[:500]))
        if stripped and not stripped.isdigit():
            previous_sequence = ""
    return mentions


def create_database(path: Path, rows: list[dict[str, object]]) -> None:
    with tempfile.TemporaryDirectory(prefix="jiaotang-kb-content-") as directory:
        temporary_path = Path(directory) / path.name
        connection = sqlite3.connect(temporary_path)
        try:
            connection.executescript(
                """
                CREATE TABLE documents (
                    id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    cloud_path TEXT NOT NULL,
                    document_role TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE documents_fts USING fts5(
                    title,
                    content,
                    source,
                    document_role,
                    content='documents',
                    content_rowid='id',
                    tokenize='unicode61'
                );
                CREATE VIRTUAL TABLE documents_fts_trigram USING fts5(
                    title,
                    content,
                    source,
                    document_role,
                    content='documents',
                    content_rowid='id',
                    tokenize='trigram'
                );
                CREATE TABLE document_chunks (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id),
                    chunk_number INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    UNIQUE(document_id, chunk_number)
                );
                CREATE VIRTUAL TABLE document_chunks_fts USING fts5(
                    document_id UNINDEXED,
                    chunk_number UNINDEXED,
                    title,
                    content,
                    source,
                    tokenize='trigram'
                );
                CREATE TABLE enterprise_mentions (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id),
                    enterprise_name TEXT NOT NULL,
                    sequence_no TEXT NOT NULL,
                    context TEXT NOT NULL,
                    UNIQUE(document_id, enterprise_name, sequence_no)
                );
                CREATE INDEX enterprise_mentions_name_idx
                    ON enterprise_mentions(enterprise_name);
                """
            )
            connection.executemany(
                """
                INSERT INTO documents(
                    source_key,title,content,source,cloud_path,document_role,
                    sensitivity,sha256,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    (
                        row["source_key"],
                        row["title"],
                        row["content"],
                        row["source"],
                        row["cloud_path"],
                        row["document_role"],
                        row["sensitivity"],
                        row["sha256"],
                        row["updated_at"],
                    )
                    for row in rows
                ),
            )
            connection.execute(
                "INSERT INTO documents_fts(rowid,title,content,source,document_role) "
                "SELECT id,title,content,source,document_role FROM documents"
            )
            connection.execute(
                "INSERT INTO documents_fts_trigram(rowid,title,content,source,document_role) "
                "SELECT id,title,content,source,document_role FROM documents"
            )
            documents = connection.execute(
                "SELECT id,title,content,source FROM documents"
            ).fetchall()
            chunk_rows: list[tuple[int, int, str, str, str]] = []
            mention_rows: list[tuple[int, str, str, str]] = []
            for document_id, title, content, source in documents:
                for chunk_number, chunk in iter_chunks(str(content)):
                    chunk_rows.append(
                        (int(document_id), chunk_number, str(title), chunk, str(source))
                    )
                for name, sequence, context in enterprise_mentions(str(content)):
                    mention_rows.append((int(document_id), name, sequence, context))
            connection.executemany(
                "INSERT INTO document_chunks(document_id,chunk_number,content) VALUES (?,?,?)",
                ((row[0], row[1], row[3]) for row in chunk_rows),
            )
            connection.executemany(
                "INSERT INTO document_chunks_fts(document_id,chunk_number,title,content,source) "
                "VALUES (?,?,?,?,?)",
                chunk_rows,
            )
            connection.executemany(
                "INSERT OR IGNORE INTO enterprise_mentions(" 
                "document_id,enterprise_name,sequence_no,context) VALUES (?,?,?,?)",
                mention_rows,
            )
            connection.commit()
        finally:
            connection.close()
        shutil.copy2(temporary_path, path)


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    output = (args.output or manifest_path.parent).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    cache_path = args.cache.expanduser().resolve()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    extraction_cache: dict[str, tuple[str, str]] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                cached = json.loads(line)
                if cache_status_reusable(str(cached["status"])):
                    extraction_cache[cached["sha256"]] = (cached["text"], cached["status"])
            except (KeyError, TypeError, json.JSONDecodeError):
                continue

    manifest = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    rows: list[dict[str, object]] = []
    report: list[dict[str, object]] = []
    status_counts: Counter[str] = Counter()
    for position, item in enumerate(manifest, start=1):
        if item["upload_action"] not in {"upload", "reference_duplicate"}:
            status = str(item["upload_action"])
            text = ""
        elif item["upload_action"] == "reference_duplicate":
            status = "duplicate_alias"
            text = ""
        elif item["sha256"] in extraction_cache:
            text, status = extraction_cache[item["sha256"]]
        elif item["index_mode"] == "manual_review":
            try:
                text, status = extract_manual(Path(item["source_path"]))
            except Exception as error:
                text = ""
                status = f"error:{type(error).__name__}"
        elif item["index_mode"] in {"archive_only", "ocr_required"}:
            status = str(item["index_mode"])
            text = ""
        else:
            try:
                text, status = extract(Path(item["source_path"]), item["extension"])
            except Exception as error:
                text = ""
                status = f"error:{type(error).__name__}"
            with cache_path.open("a", encoding="utf-8") as cache_target:
                cache_target.write(
                    json.dumps(
                        {"sha256": item["sha256"], "status": status, "text": text},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        status_counts[status] += 1
        report.append(
            {
                "relative_path": item["relative_path"],
                "status": status,
                "text_chars": len(text),
                "sha256": item["sha256"],
            }
        )
        if status == "indexed":
            rows.append(
                {
                    "source_key": item["sha256"] or item["relative_path"],
                    "title": item["name"],
                    "content": text,
                    "source": item["relative_path"],
                    "cloud_path": item["cloud_path"],
                    "document_role": item["document_role"],
                    "sensitivity": item["sensitivity"],
                    "sha256": item["sha256"],
                    "updated_at": item["modified_at"],
                }
            )
        if position % 250 == 0:
            print(f"processed={position}/{len(manifest)} indexed={len(rows)}", flush=True)

    with (output / "documents.jsonl").open("w", encoding="utf-8") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output / "extraction_report.csv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(
            target, fieldnames=["relative_path", "status", "text_chars", "sha256"]
        )
        writer.writeheader()
        writer.writerows(report)
    create_database(output / "knowledge_content.sqlite3", rows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_files": len(manifest),
        "indexed_documents": len(rows),
        "status_counts": dict(status_counts),
        "content_characters": sum(len(str(row["content"])) for row in rows),
    }
    (output / "extraction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--extract-pdf-worker":
        sys.stdout.write(extract_pdf(Path(sys.argv[2])))
    else:
        main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("/Users/zsh/JiaotangData/知识库")
DEFAULT_MANIFEST = Path("/Users/zsh/JiaotangData/索引/current/manifest.jsonl")
DEFAULT_AUDIT = Path("/Users/zsh/JiaotangData/索引/current/knowledge_ingest_audit.jsonl")
PIPELINE = Path(__file__).with_name("sync_archived_knowledge_to_production.sh")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按哈希查重、版本识别、条目核验和定向OSS同步接收知识库文件"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--relative-target", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument(
        "--profile",
        choices=("generic", "first-batch-directory"),
        default="generic",
    )
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--execute-pipeline", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_text(path: Path, pages: int = 3) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join(
        (reader.pages[index].extract_text() or "")
        for index in range(min(pages, len(reader.pages)))
    )
    return text, len(reader.pages)


def detect_version(path: Path) -> dict[str, Any]:
    content = ""
    page_count = None
    if path.suffix.lower() == ".pdf":
        content, page_count = pdf_text(path)
    value = f"{path.name}\n{content}"
    years = [int(year) for year in re.findall(r"20\d{2}", value)]
    document_number = ""
    match = re.search(
        r"([A-Za-z\u4e00-\u9fff]{1,12})\s*〔\s*((?:19|20)\d{2})\s*〕\s*(\d{1,5})\s*号",
        value,
    )
    if match:
        document_number = f"{match.group(1)}〔{match.group(2)}〕{int(match.group(3))}号"
    status = (
        "draft"
        if any(term in value for term in ("公示稿", "征求意见稿", "草案"))
        else "formal"
        if document_number or any(term in value for term in ("关于印发", "现予印发", "正式公布"))
        else "unclassified"
    )
    return {
        "year": max(years) if years else None,
        "document_number": document_number,
        "version_status": status,
        "page_count": page_count,
    }


def verify_first_batch_directory(path: Path, expected_count: int | None) -> dict[str, Any]:
    import pdfplumber

    sequence_numbers: set[int] = set()
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    if row and str(row[0] or "").strip().isdigit():
                        sequence_numbers.add(int(str(row[0]).strip()))
    actual_count = len(sequence_numbers)
    continuous = (
        sorted(sequence_numbers) == list(range(1, max(sequence_numbers) + 1))
        if sequence_numbers
        else False
    )
    if not continuous:
        raise RuntimeError("首批次目录序号不连续")
    if expected_count is not None and actual_count != expected_count:
        raise RuntimeError(
            f"首批次目录预期{expected_count}项，实际{actual_count}项"
        )
    return {
        "verification_profile": "first-batch-directory",
        "entry_count": actual_count,
        "sequence_continuous": continuous,
    }


def manifest_hash_paths(path: Path, digest: str) -> list[str]:
    if not path.is_file():
        return []
    matches = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("sha256") or "") == digest:
            matches.append(str(row.get("relative_path") or ""))
    return sorted(set(matches))


def append_audit(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_pipeline(relative_target: Path) -> None:
    environment = os.environ.copy()
    environment["JIAOTANG_OSS_RELATIVE_PREFIXES"] = relative_target.parent.as_posix()
    subprocess.run([str(PIPELINE)], check=True, env=environment)


def main() -> None:
    args = parse_args()
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"源文件不存在：{source}")
    relative_target = Path(args.relative_target.as_posix().lstrip("/"))
    target = args.knowledge_root / relative_target
    digest = sha256_file(source)
    duplicates = manifest_hash_paths(args.manifest, digest)
    version = detect_version(source)
    verification = (
        verify_first_batch_directory(source, args.expected_count)
        if args.profile == "first-batch-directory"
        else {"verification_profile": "generic", "entry_count": None}
    )
    copied = False
    if target.is_file():
        target_digest = sha256_file(target)
        if target_digest != digest:
            raise SystemExit(f"目标已存在不同内容，禁止静默覆盖：{target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied = True
    duplicate_content = bool(duplicates)
    action = (
        "same_hash_archived_without_rebuild"
        if duplicate_content
        else "new_content_pipeline_required"
    )
    payload = {
        "ingested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": str(source),
        "target": str(target),
        "relative_target": relative_target.as_posix(),
        "sha256": digest,
        "size_bytes": source.stat().st_size,
        "copied": copied,
        "duplicate_content": duplicate_content,
        "duplicate_manifest_paths": duplicates,
        "action": action,
        **version,
        **verification,
    }
    append_audit(args.audit_log, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if duplicate_content:
        return
    if args.execute_pipeline:
        run_pipeline(relative_target)
    else:
        print("新内容已归档；未指定--execute-pipeline，尚未重建索引或同步OSS。")


if __name__ == "__main__":
    main()

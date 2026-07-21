from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

LIST_CATEGORY = "专精特新和小巨人公示名单与认定名单"
CASE_EXTENSIONS = {".doc", ".docx", ".docm", ".wps"}
CASE_TERMS = (
    "申请书",
    "申报书",
    "建设方案",
    "可行性报告",
    "规划方案",
    "实施方案",
    "项目方案",
    "建设报告",
)
CASE_EXCLUDED_TERMS = (
    "审计",
    "合同",
    "证书",
    "营业执照",
    "身份证",
    "社保",
    "养老保险",
    "发票",
    "纳税申报",
    "银行流水",
    "科创空间",
)
CREDENTIAL_PATTERNS = {
    "credential": re.compile(
        r"(?i)(?:access[_ -]?token|api[_ -]?key|password|cookie|secret)\s*[:=]"
    ),
    "private_key": re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="补齐专精特新名单及申报案例 Word 文件")
    parser.add_argument("--knowledge-root", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_KNOWLEDGE_ROOT", Path.cwd() / "knowledge")))
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def package_hashes(package_root: Path, manifest_path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            source = Path(str(item.get("source_path", "")))
            digest = str(item.get("sha256", ""))
            if digest and source.exists():
                hashes.setdefault(digest, str(source))
        if hashes:
            return hashes
    for path in package_root.rglob("*"):
        if path.is_file() and not path.name.startswith("._"):
            hashes.setdefault(sha256_file(path), str(path))
    return hashes


def unique_destination(destination: Path, digest: str) -> Path:
    if not destination.exists():
        return destination
    if sha256_file(destination) == digest:
        return destination
    return destination.with_name(f"{destination.stem}__{digest[:8]}{destination.suffix}")


def credential_hits(path: Path) -> list[str]:
    texts: list[str] = []
    try:
        payload = path.read_bytes()
    except OSError:
        return []
    texts.extend(
        (
            payload.decode("utf-8", errors="ignore"),
            payload.decode("utf-16le", errors="ignore"),
            payload.decode("latin-1", errors="ignore"),
        )
    )
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith((".xml", ".rels", ".txt")):
                        texts.append(archive.read(name).decode("utf-8", errors="ignore"))
        except (OSError, zipfile.BadZipFile, KeyError):
            pass
    return [
        name
        for name, pattern in CREDENTIAL_PATTERNS.items()
        if any(pattern.search(text) for text in texts)
    ]


def is_case_word(relative_path: str, extension: str) -> bool:
    normalized = relative_path.lower()
    return (
        extension.lower() in CASE_EXTENSIONS
        and any(term.lower() in normalized for term in CASE_TERMS)
        and not any(term.lower() in normalized for term in CASE_EXCLUDED_TERMS)
    )


def main() -> None:
    args = parse_args()
    knowledge_root = args.knowledge_root.expanduser().resolve()
    package_root = knowledge_root / "_云端知识库"
    index_root = knowledge_root / "_云端迁移索引"
    manifest_path = index_root / "manifest.jsonl"
    manifest = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    existing_hashes = package_hashes(
        package_root, index_root / "cloud_package_index" / "manifest.jsonl"
    )
    records: list[dict[str, object]] = []

    for item in manifest:
        relative_path = str(item["relative_path"])
        if relative_path.startswith(("_云端知识库/", "_云端迁移索引/")):
            continue
        source = Path(str(item["source_path"]))
        if not source.exists() or source.name.startswith(("._", "~$")):
            continue
        digest = str(item.get("sha256") or sha256_file(source))
        top_category = str(item.get("top_category", ""))

        kind = ""
        destination: Path | None = None
        if top_category == LIST_CATEGORY:
            kind = "specialized_sme_list"
            remainder = Path(relative_path).relative_to(LIST_CATEGORY)
            destination = package_root / "50_名单与对标" / LIST_CATEGORY / remainder
        elif is_case_word(relative_path, source.suffix):
            kind = "application_or_construction_case"
            parts = Path(relative_path).parts
            category = parts[0] if len(parts) > 1 else "未分类"
            remainder = Path(*parts[1:]) if len(parts) > 1 else Path(source.name)
            destination = package_root / "60_申报案例与建设方案" / category / remainder
        else:
            continue

        if digest in existing_hashes:
            action = "existing_duplicate"
            destination_or_existing = existing_hashes[digest]
            hits: list[str] = []
        else:
            hits = credential_hits(source)
            if hits:
                action = "blocked_credential"
                destination_or_existing = ""
            else:
                destination = unique_destination(destination, digest)
                destination_or_existing = str(destination)
                action = "copied" if args.execute else "would_copy"
                if args.execute:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    existing_hashes[digest] = str(destination)

        records.append(
            {
                "kind": kind,
                "action": action,
                "sha256": digest,
                "size_bytes": source.stat().st_size,
                "source": str(source),
                "destination_or_existing": destination_or_existing,
                "credential_hits": "|".join(hits),
            }
        )

    tag = "executed" if args.execute else "dry_run"
    report_path = index_root / f"all_lists_case_words_{tag}.csv"
    fields = [
        "kind",
        "action",
        "sha256",
        "size_bytes",
        "source",
        "destination_or_existing",
        "credential_hits",
    ]
    with report_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execute": args.execute,
        "files": len(records),
        "bytes": sum(int(record["size_bytes"]) for record in records),
        "kinds": dict(Counter(str(record["kind"]) for record in records)),
        "actions": dict(Counter(str(record["action"]) for record in records)),
        "report": str(report_path),
    }
    summary_path = index_root / f"all_lists_case_words_{tag}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

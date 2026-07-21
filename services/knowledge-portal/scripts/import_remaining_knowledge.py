from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic",
}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}
CERTIFICATE_TERMS = (
    "证书", "证照", "营业执照", "毕业证", "学位证", "职称证", "资质证",
)
AUDIT_GUIDE_TERMS = ("指南", "复核", "要点", "模板", "培训", "指引", "规范")
SOCIAL_SECURITY_EVIDENCE_TERMS = (
    "社保清单", "社保名单", "社保证明", "社保缴纳", "社保记录", "人员社保", "员工社保",
)
CREDENTIAL_PATTERNS = {
    "credential": re.compile(
        r"(?i)(?:access[_ -]?token|api[_ -]?key|password|cookie|secret)\s*[:=]|"
        r"(?:密码|口令|密钥)\s*[:：=]"
    ),
    "private_key": re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
}
CREDENTIAL_BYTE_PATTERNS = {
    "credential": re.compile(
        rb"(?i)(?:access[_ -]?token|api[_ -]?key|password|cookie|secret)\s*[:=]"
    ),
    "private_key": re.compile(rb"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
}
SENSITIVE_CREDENTIAL_FILENAME_PATTERN = re.compile(
    r"账号密码|账户密码|用户名密码|登录密码|访问密钥|私钥", re.I
)
ROLE_TO_LAYER = {
    "10_政策与通知": "10_政策与目录",
    "20_项目规则与指南": "20_申报指南与规则",
    "30_申报案例": "60_申报案例与建设方案",
    "40_项目与客户资料": "60_申报案例与建设方案",
    "50_名单与对标": "50_名单与对标",
    "60_模板培训": "40_内部培训与方法",
    "70_知识产权": "70_知识产权方法",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入明确排除项之外的全部剩余知识库资料")
    parser.add_argument("--knowledge-root", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_KNOWLEDGE_ROOT", Path.cwd() / "knowledge")))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--reuse-dry-run", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def exclusion_reason(path: Path) -> str | None:
    extension = path.suffix.lower()
    normalized = str(path).replace("\\", "/").lower()
    filename = path.name.lower()
    if extension in IMAGE_EXTENSIONS:
        return "excluded_image"
    if extension in ARCHIVE_EXTENSIONS:
        return "excluded_archive"
    if "专利" in normalized:
        return "excluded_patent"
    if "企业标准" in normalized and "中小企业标准" not in normalized:
        return "excluded_enterprise_standard"
    if any(term.lower() in normalized for term in CERTIFICATE_TERMS):
        return "excluded_certificate"
    if "审计报告" in normalized and not any(term in filename for term in AUDIT_GUIDE_TERMS):
        return "excluded_audit_report"
    if "养老保险" in normalized:
        return "excluded_social_security"
    if any(term in normalized for term in SOCIAL_SECURITY_EVIDENCE_TERMS):
        return "excluded_social_security"
    return None


def load_indexed_content(database_path: Path) -> dict[str, str]:
    if not database_path.exists():
        return {}
    with sqlite3.connect(database_path) as connection:
        return {
            str(digest): str(content)
            for digest, content in connection.execute("SELECT sha256, content FROM documents")
        }


def credential_hits(path: Path, indexed_text: str) -> list[str]:
    if SENSITIVE_CREDENTIAL_FILENAME_PATTERN.search(path.name):
        return ["credential_filename"]
    if indexed_text:
        return [
            name
            for name, pattern in CREDENTIAL_PATTERNS.items()
            if pattern.search(indexed_text)
        ]
    hits: set[str] = set()
    try:
        with path.open("rb") as source:
            tail = b""
            while chunk := source.read(4 * 1024 * 1024):
                payload = tail + chunk
                compact_payload = payload.replace(b"\x00", b"")
                for name, pattern in CREDENTIAL_BYTE_PATTERNS.items():
                    if pattern.search(payload) or pattern.search(compact_payload):
                        hits.add(name)
                tail = payload[-256:]
    except OSError:
        return []
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith((".xml", ".rels", ".txt")):
                        member = archive.read(name)
                        for hit_name, pattern in CREDENTIAL_BYTE_PATTERNS.items():
                            if pattern.search(member):
                                hits.add(hit_name)
        except (OSError, zipfile.BadZipFile, KeyError):
            pass
    return sorted(hits)


def unique_destination(destination: Path, digest: str) -> Path:
    if not destination.exists():
        return destination
    if sha256_file(destination) == digest:
        return destination
    return destination.with_name(f"{destination.stem}__{digest[:8]}{destination.suffix}")


def write_report(index_root: Path, rows: list[dict[str, object]], execute: bool) -> dict[str, object]:
    tag = "executed" if execute else "dry_run"
    report_path = index_root / f"remaining_knowledge_import_{tag}.csv"
    fields = [
        "action", "sha256", "size_bytes", "document_role", "top_category",
        "source", "destination", "credential_hits",
    ]
    with report_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execute": execute,
        "files_reviewed": len(rows),
        "bytes_reviewed": sum(int(row["size_bytes"]) for row in rows),
        "actions": dict(Counter(str(row["action"]) for row in rows)),
        "bytes_by_action": {
            action: sum(int(row["size_bytes"]) for row in rows if row["action"] == action)
            for action in {str(row["action"]) for row in rows}
        },
        "report": str(report_path),
    }
    summary_path = index_root / f"remaining_knowledge_import_{tag}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def execute_dry_run(
    index_root: Path, package_hashes: dict[str, str]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    dry_run_path = index_root / "remaining_knowledge_import_dry_run.csv"
    with dry_run_path.open(encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    for position, row in enumerate(rows, start=1):
        if row["action"] != "would_copy":
            continue
        digest = row["sha256"]
        source_path = Path(row["source"])
        if digest in package_hashes:
            row["action"] = "existing_duplicate"
            row["destination"] = package_hashes[digest]
            continue
        if not source_path.exists():
            row["action"] = "source_missing"
            continue
        destination = unique_destination(Path(row["destination"]), digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        row["destination"] = str(destination)
        row["action"] = "copied"
        package_hashes[digest] = str(destination)
        if position % 250 == 0:
            print(f"copy_position={position}", flush=True)
    return rows, write_report(index_root, rows, execute=True)


def main() -> None:
    args = parse_args()
    knowledge_root = args.knowledge_root.expanduser().resolve()
    index_root = knowledge_root / "_云端迁移索引"
    package_root = knowledge_root / "_云端知识库"
    source_manifest = [
        json.loads(line)
        for line in (index_root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    cloud_manifest = [
        json.loads(line)
        for line in (index_root / "cloud_package_index" / "manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    package_hashes = {
        str(item["sha256"]): str(item["source_path"])
        for item in cloud_manifest
        if item.get("sha256") and Path(str(item.get("source_path", ""))).exists()
    }
    if args.execute and args.reuse_dry_run:
        _, summary = execute_dry_run(index_root, package_hashes)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    indexed_content = load_indexed_content(index_root / "knowledge_content.sqlite3")
    rows: list[dict[str, object]] = []

    for position, item in enumerate(source_manifest, start=1):
        relative_path = str(item.get("relative_path", ""))
        source = Path(str(item.get("source_path", "")))
        if relative_path.startswith(("_云端知识库/", "_云端迁移索引/")):
            continue
        if not source.exists() or source.name.startswith(("._", "~$")):
            continue
        digest = str(item.get("sha256") or sha256_file(source))
        if digest in package_hashes:
            continue

        excluded = exclusion_reason(source)
        destination = ""
        hits: list[str] = []
        if excluded:
            action = excluded
        else:
            hits = credential_hits(source, indexed_content.get(digest, ""))
            if hits:
                action = "blocked_credential"
            else:
                role = str(item.get("document_role", ""))
                layer = ROLE_TO_LAYER.get(role, "60_申报案例与建设方案")
                destination_path = unique_destination(
                    package_root / layer / Path(relative_path), digest
                )
                destination = str(destination_path)
                action = "copied" if args.execute else "would_copy"
                if args.execute:
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination_path)
                    package_hashes[digest] = str(destination_path)

        rows.append(
            {
                "action": action,
                "sha256": digest,
                "size_bytes": source.stat().st_size,
                "document_role": item.get("document_role", ""),
                "top_category": item.get("top_category", ""),
                "source": str(source),
                "destination": destination,
                "credential_hits": "|".join(hits),
            }
        )
        if len(rows) % 250 == 0:
            print(f"reviewed={len(rows)} manifest_position={position}", flush=True)

    summary = write_report(index_root, rows, execute=args.execute)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

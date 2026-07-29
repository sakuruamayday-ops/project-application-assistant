from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


KNOWLEDGE_ROOT = Path("/Users/zsh/JiaotangData/知识库")
REGIONAL_ROOT = KNOWLEDGE_ROOT / "10_政策与目录/政策数据库/企策顾问"
COMPANY_LAW_PATH = (
    KNOWLEDGE_ROOT
    / "10_政策与目录/综合政策/法律法规底库/公司法/2026-07-21_新公司法下企业合规自查与风险防范.md"
)
LAYER_GUIDE_PATH = KNOWLEDGE_ROOT / "10_政策与目录/政策检索分层说明.md"
HANGZHOU_INSTITUTE_ROOT = KNOWLEDGE_ROOT / "10_政策与目录/研究院/杭州市企业研究院"
SUPPLEMENTARY_ROOTS = (
    KNOWLEDGE_ROOT / "50_名单与对标/优质中小企业梯度培育/_省级专精特新",
    KNOWLEDGE_ROOT / "50_名单与对标/优质中小企业梯度培育/_覆盖矩阵",
    KNOWLEDGE_ROOT / "50_名单与对标/优质中小企业梯度培育/_全国小巨人批次主表",
    KNOWLEDGE_ROOT / "50_名单与对标/优质中小企业梯度培育/来源归档",
    KNOWLEDGE_ROOT / "50_名单与对标/优质中小企业梯度培育/企策顾问动态索引",
    KNOWLEDGE_ROOT / "50_名单与对标/三首项目/_结构化数据",
    KNOWLEDGE_ROOT / "50_名单与对标/企业身份时间轴",
    KNOWLEDGE_ROOT / "90_方法与复盘",
    KNOWLEDGE_ROOT / "10_政策与目录/三首项目/浙江省首批次新材料/应用示范指导目录",
)
MANIFEST_PATH = Path("/Users/zsh/JiaotangData/索引/current/manifest.jsonl")
MANIFEST_CSV_PATH = MANIFEST_PATH.with_suffix(".csv")
CONTROL_FILES = {"README.md", "整理摘要.json", "网站上传索引.csv", "网站上传索引.json"}
EXTRACT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".json",
    ".jsonl",
    ".md",
    ".pdf",
    ".pptx",
    ".txt",
    ".wps",
    ".xls",
    ".xlsx",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metadata_for(path: Path) -> tuple[str, str]:
    relative = path.relative_to(REGIONAL_ROOT)
    parts = relative.parts
    document_type = parts[0] if len(parts) > 0 else "政策资料"
    city = parts[1] if len(parts) > 1 else ""
    category = parts[2] if len(parts) > 2 else "综合政策"
    directory = parts[3] if len(parts) > 3 else path.parent.name
    segments = directory.split("__")
    project_title = segments[1] if len(segments) >= 2 else directory
    title = project_title if path.name in {"项目说明.md", "通知原文.md"} else f"{project_title}—{path.name}"
    prefix = "\n".join(
        (
            f"归档地区：{city}",
            f"文件类型：{document_type}",
            f"项目类别：{category}",
            f"项目标题：{project_title}",
        )
    )
    return title, prefix


def manifest_row(path: Path, previous: dict[str, object] | None = None) -> dict[str, object]:
    relative = path.relative_to(KNOWLEDGE_ROOT).as_posix()
    extension = path.suffix.lower()
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    unchanged = bool(
        previous
        and int(previous.get("size_bytes") or -1) == stat.st_size
        and str(previous.get("modified_at") or "") == modified_at
        and previous.get("sha256")
    )
    digest = str(previous["sha256"]) if unchanged and previous else sha256_file(path)
    title = path.name
    content_prefix = ""
    if path.is_relative_to(REGIONAL_ROOT):
        title, content_prefix = metadata_for(path)
    is_team_list_data = relative.startswith("50_名单与对标/")
    document_role = "50_名单与对标" if is_team_list_data else "10_政策与通知"
    cloud_path = relative if is_team_list_data else f"10_政策与通知/{relative}"
    # Files suffixed with ``.source.*`` are immutable evidence snapshots for
    # provenance replay. Their normalized Markdown companion is the searchable
    # representation; indexing both would emit duplicate lifecycle events.
    is_source_snapshot = ".source." in path.name.lower()
    return {
        "source_path": str(path),
        "relative_path": relative,
        "cloud_path": cloud_path,
        "name": path.name,
        "title": title,
        "content_prefix": content_prefix,
        "extension": extension,
        "size_bytes": stat.st_size,
        "modified_at": modified_at,
        "sha256": digest,
        "source_key": hashlib.sha256(f"cloud-path:{relative}".encode()).hexdigest(),
        "top_category": "50_名单与对标" if is_team_list_data else "10_政策与目录",
        "document_role": document_role,
        "sensitivity": "internal" if is_team_list_data else "public_reference",
        "index_mode": (
            "archive_only"
            if is_source_snapshot
            else ("extract_text" if extension in EXTRACT_EXTENSIONS else "archive_only")
        ),
        "upload_priority": 1,
        "upload_action": "upload",
        "canonical_path": relative,
    }


def regional_files() -> list[Path]:
    return sorted(
        (
            path
            for path in REGIONAL_ROOT.rglob("*")
            if path.is_file()
            and not path.name.startswith("._")
            and path.name not in CONTROL_FILES
        ),
        key=lambda path: path.as_posix(),
    )


def hangzhou_institute_files() -> list[Path]:
    return sorted(
        (
            path
            for path in HANGZHOU_INSTITUTE_ROOT.rglob("*")
            if path.is_file() and not path.name.startswith("._")
        ),
        key=lambda path: path.as_posix(),
    )


def supplementary_files() -> list[Path]:
    return sorted(
        (
            path
            for root in SUPPLEMENTARY_ROOTS
            if root.exists()
            for path in root.rglob("*")
            if path.is_file()
            and not path.name.startswith("._")
            and path.name not in CONTROL_FILES
        ),
        key=lambda path: path.as_posix(),
    )


def write_atomic(path: Path, payload: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def reconcile_ocr_companions(rows: list[dict[str, object]]) -> int:
    relative_paths = {str(row.get("relative_path") or "") for row in rows}
    reconciled = 0
    for row in rows:
        relative_path = str(row.get("relative_path") or "")
        if not relative_path.lower().endswith(".pdf"):
            continue
        markdown_path = str(Path(relative_path).with_suffix(".md")).replace("\\", "/")
        if markdown_path not in relative_paths:
            continue
        row["index_mode"] = "archive_only"
        row["ocr_companion_path"] = markdown_path
        row["ocr_companion_status"] = "available"
        reconciled += 1
    return reconciled


def main() -> None:
    existing = [
        json.loads(line)
        for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    existing_by_path = {str(row.get("relative_path") or ""): row for row in existing}
    replacement_prefix = "10_政策与目录/政策数据库/企策顾问/"
    institute_prefix = "10_政策与目录/研究院/杭州市企业研究院/"
    supplementary_prefixes = tuple(
        f"{root.relative_to(KNOWLEDGE_ROOT).as_posix()}/" for root in SUPPLEMENTARY_ROOTS
    )
    replaced_paths = {str(COMPANY_LAW_PATH.relative_to(KNOWLEDGE_ROOT)), str(LAYER_GUIDE_PATH.relative_to(KNOWLEDGE_ROOT))}
    retained = [
        row
        for row in existing
        if not str(row.get("relative_path", "")).startswith(replacement_prefix)
        and not str(row.get("relative_path", "")).startswith(institute_prefix)
        and not str(row.get("relative_path", "")).startswith(supplementary_prefixes)
        and str(row.get("relative_path", "")) not in replaced_paths
    ]
    additions = [
        manifest_row(
            path,
            existing_by_path.get(path.relative_to(KNOWLEDGE_ROOT).as_posix()),
        )
        for path in regional_files()
    ]
    additions.extend(
        manifest_row(
            path,
            existing_by_path.get(path.relative_to(KNOWLEDGE_ROOT).as_posix()),
        )
        for path in (COMPANY_LAW_PATH, LAYER_GUIDE_PATH)
    )
    institute_additions = [
        manifest_row(
            path,
            existing_by_path.get(path.relative_to(KNOWLEDGE_ROOT).as_posix()),
        )
        for path in hangzhou_institute_files()
    ]
    additions.extend(institute_additions)
    supplementary_additions = [
        manifest_row(
            path,
            existing_by_path.get(path.relative_to(KNOWLEDGE_ROOT).as_posix()),
        )
        for path in supplementary_files()
    ]
    additions.extend(supplementary_additions)
    rows = sorted(retained + additions, key=lambda row: str(row["relative_path"]))
    reconciled_companions = reconcile_ocr_companions(rows)

    backup = MANIFEST_PATH.with_name(
        f"manifest.before-policy-update-{datetime.now().strftime('%Y%m%d%H%M%S')}.jsonl"
    )
    shutil.copy2(MANIFEST_PATH, backup)
    write_atomic(
        MANIFEST_PATH,
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
    )
    fieldnames = sorted({key for row in rows for key in row})
    temporary_csv = MANIFEST_CSV_PATH.with_name(f".{MANIFEST_CSV_PATH.name}.tmp")
    with temporary_csv.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary_csv, MANIFEST_CSV_PATH)
    print(
        json.dumps(
            {
                "retained": len(retained),
                "regional_added": len(additions) - 2 - len(institute_additions),
                "guides_added": 2,
                "hangzhou_institute_added": len(institute_additions),
                "supplementary_added": len(supplementary_additions),
                "manifest_total": len(rows),
                "ocr_companions_reconciled": reconciled_companions,
                "backup": str(backup),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

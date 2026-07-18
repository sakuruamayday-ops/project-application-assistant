from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.import_shichen_curated import EXCLUDED_TERMS, SENSITIVE_TERMS
except ModuleNotFoundError:
    from import_shichen_curated import EXCLUDED_TERMS, SENSITIVE_TERMS


EXCLUDED_TOP_CATEGORIES = {"1.谈单资料", "各类答辩ppt", ".obsidian", "_云端知识库"}
CORE_ROLES = {"10_政策与通知", "20_项目规则与指南", "50_名单与对标"}
INTERNAL_ALLOWED_CATEGORIES = {
    "人才项目",
    "优质中小企业梯度培育",
    "加计扣除",
    "工业新产品",
    "技术改造和未来工厂",
    "研究院",
    "科技计划",
    "首版次",
    "高新",
}
HIGH_RISK_PATTERNS = {
    "mobile_phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "id_card": re.compile(r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)"),
    "bank_card": re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "credential": re.compile(r"(?i)(?:access[_ -]?token|api[_ -]?key|password|cookie|secret)\s*[:=]"),
}
ALLOWED_PACKAGE_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx",
    ".wps", ".md", ".txt", ".csv", ".json",
}
PUBLIC_POLICY_SIGNALS = (
    "通知", "办法", "指南", "指引", "细则", "条件", "要求", "目录", "规范",
    "规则", "政策", "评价", "管理", "工作方案", "实施方案", "征集", "认定",
    "验收", "申报", "评审", "操作规程",
)
PUBLIC_LIST_SIGNALS = (
    "名单", "公示", "公布", "认定", "拟认定", "入选", "推荐", "备案", "结果",
)
SUSPICIOUS_PATH_TERMS = (
    "客户", "初稿", "终稿", "上报稿", "提交稿", "打印版", "材料汇总", "整套材料",
    "案例", "案列", "答辩", "佐证", "证明材料", "已填写",
    "交科", "华味亨", "申新新材料", "康纳", "城西杭口", "养老保险",
)
INTERNAL_METHOD_SIGNALS = (
    "模板", "空白", "培训", "总结", "指引", "资料清单", "计算逻辑", "进度搜集",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建自包含的云端知识库上传包")
    parser.add_argument("--knowledge-root", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_KNOWLEDGE_ROOT", Path.cwd() / "knowledge")))
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def content_by_hash(database_path: Path) -> dict[str, str]:
    if not database_path.exists():
        return {}
    with sqlite3.connect(database_path) as connection:
        return {
            str(digest): str(content)
            for digest, content in connection.execute("SELECT sha256, content FROM documents")
        }


def high_risk_hits(content: str) -> list[str]:
    return [name for name, pattern in HIGH_RISK_PATTERNS.items() if pattern.search(content)]


def path_rejection(relative_path: str) -> str | None:
    lowered = relative_path.lower()
    for term in SENSITIVE_TERMS:
        if term.lower() not in lowered:
            continue
        if term in {"申报书", "申请书"} and any(marker in lowered for marker in ("模板", "空白", "样表")):
            continue
        return "sensitive_or_customer_specific_path"
    if any(term.lower() in lowered for term in EXCLUDED_TERMS):
        return "low_value_or_duplicate_name"
    return None


def source_scope_rejection(record: dict[str, object], selection: str) -> str | None:
    relative = Path(str(record["relative_path"]))
    path_text = str(relative).lower()
    filename = relative.name.lower()
    if relative.suffix.lower() not in ALLOWED_PACKAGE_EXTENSIONS:
        return "unsupported_package_extension"
    if any(term.lower() in path_text for term in SUSPICIOUS_PATH_TERMS):
        return "non_public_or_case_path"
    if selection == "internal_method":
        if not any(term.lower() in filename for term in INTERNAL_METHOD_SIGNALS):
            return "internal_not_reusable_method"
        return None
    role = str(record["document_role"])
    if role == "50_名单与对标":
        if not any(term.lower() in filename for term in PUBLIC_LIST_SIGNALS):
            return "public_list_title_not_verified"
    elif not any(term.lower() in filename for term in PUBLIC_POLICY_SIGNALS):
        return "public_policy_title_not_verified"
    return None


def package_destination(package_root: Path, record: dict[str, object]) -> Path:
    role = str(record["document_role"])
    category = str(record["top_category"])
    relative = Path(str(record["relative_path"]))
    remainder = Path(*relative.parts[1:]) if len(relative.parts) > 1 else Path(relative.name)
    if role == "10_政策与通知":
        layer = "10_政策与目录"
    elif role == "20_项目规则与指南":
        layer = "20_申报指南与规则"
    elif role == "50_名单与对标":
        layer = "50_名单与对标"
    else:
        layer = "40_内部培训与方法"
    return package_root / layer / category / remainder


def unique_destination(destination: Path, digest: str) -> Path:
    if not destination.exists():
        return destination
    if sha256_file(destination) == digest:
        return destination
    return destination.with_name(f"{destination.stem}__{digest[:8]}{destination.suffix}")


def main() -> None:
    args = parse_args()
    knowledge_root = args.knowledge_root.expanduser().resolve()
    index_root = knowledge_root / "_云端迁移索引"
    package_root = knowledge_root / "_云端知识库"
    manifest_path = index_root / "manifest.jsonl"
    manifest = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    content = content_by_hash(index_root / "knowledge_content.sqlite3")

    package_hashes: dict[str, str] = {}
    for path in package_root.rglob("*"):
        if path.is_file() and not path.name.startswith("._"):
            package_hashes.setdefault(sha256_file(path), str(path))

    results: list[dict[str, object]] = []
    for record in manifest:
        if str(record["relative_path"]).startswith("_云端知识库/"):
            continue
        if record["upload_action"] != "upload":
            continue
        top_category = str(record["top_category"])
        role = str(record["document_role"])
        sensitivity = str(record["sensitivity"])
        if top_category in EXCLUDED_TOP_CATEGORIES:
            continue

        selection = ""
        if sensitivity == "public_reference" and role in CORE_ROLES:
            selection = "public_core"
        elif (
            sensitivity == "internal"
            and role == "60_模板培训"
            and top_category in INTERNAL_ALLOWED_CATEGORIES
        ):
            selection = "internal_method"
        else:
            continue

        source = Path(str(record["source_path"]))
        reason = path_rejection(str(record["relative_path"])) or source_scope_rejection(record, selection)
        if reason:
            results.append(
                {
                    "source": str(source),
                    "selection": selection,
                    "action": "skipped",
                    "reason": reason,
                    "sha256": record["sha256"],
                    "size_bytes": record["size_bytes"],
                }
            )
            continue

        if selection == "internal_method":
            extracted = content.get(str(record["sha256"]))
            if not extracted:
                results.append(
                    {
                        "source": str(source),
                        "selection": selection,
                        "action": "skipped",
                        "reason": "internal_without_fulltext",
                        "sha256": record["sha256"],
                        "size_bytes": record["size_bytes"],
                    }
                )
                continue
            hits = high_risk_hits(extracted)
            if hits:
                results.append(
                    {
                        "source": str(source),
                        "selection": selection,
                        "action": "skipped",
                        "reason": "content_dlp:" + "|".join(hits),
                        "sha256": record["sha256"],
                        "size_bytes": record["size_bytes"],
                    }
                )
                continue

        digest = str(record["sha256"])
        if digest in package_hashes:
            results.append(
                {
                    "source": str(source),
                    "selection": selection,
                    "action": "package_duplicate",
                    "reason": "same_sha256",
                    "sha256": digest,
                    "size_bytes": record["size_bytes"],
                    "destination": package_hashes[digest],
                }
            )
            continue

        destination = unique_destination(package_destination(package_root, record), digest)
        if args.execute:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        package_hashes[digest] = str(destination)
        results.append(
            {
                "source": str(source),
                "selection": selection,
                "action": "copied" if args.execute else "would_copy",
                "reason": "selected_unique",
                "sha256": digest,
                "size_bytes": record["size_bytes"],
                "destination": str(destination),
            }
        )

    mode = "executed" if args.execute else "dry_run"
    report_path = index_root / f"cloud_package_{mode}.csv"
    fields = ["source", "selection", "action", "reason", "sha256", "size_bytes", "destination"]
    with report_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    selected_actions = {"copied", "would_copy"}
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "actions": dict(Counter(str(row["action"]) for row in results)),
        "reasons": dict(Counter(str(row["reason"]) for row in results)),
        "selected_bytes": sum(
            int(row.get("size_bytes", 0)) for row in results if row["action"] in selected_actions
        ),
        "report": str(report_path),
    }
    (index_root / f"cloud_package_{mode}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

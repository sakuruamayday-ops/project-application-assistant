from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


HIGH_RISK_PATTERNS = {
    "id_card": re.compile(
        r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])"
        r"(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)"
    ),
    "credential": re.compile(
        r"(?i)(?:access[_ -]?token|api[_ -]?key|password|cookie|secret)\s*[:=]|"
        r"(?:密码|口令|密钥)\s*[:：=]"
    ),
    "private_key": re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
    "bank_account_context": re.compile(
        r"(?:银行账号|银行卡号|收款账号|账户号码|卡号)\s*[:：]?\s*\d{12,30}"
    ),
}
REVIEW_PATTERNS = {
    "mobile_phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "long_numeric_identifier": re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
}
NO_SEMANTIC_TEXT_STATUSES = {
    "archive_only",
    "empty",
    "empty_non_content",
    "manual_review",
    "non_content_manual_review",
    "non_content_placeholder",
    "not_text",
    "unrecoverable_corrupt",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成云端对象存储与语义索引白名单")
    parser.add_argument("--index-root", type=Path, required=True)
    return parser.parse_args()


def load_content(database_path: Path) -> dict[str, str]:
    with sqlite3.connect(database_path) as connection:
        return {
            str(digest): str(content)
            for digest, content in connection.execute("SELECT sha256, content FROM documents")
        }


def has_ocr_sidecar(relative_path: str, manifest_paths: set[str]) -> bool:
    path = Path(relative_path)
    return path.suffix.lower() == ".pdf" and path.with_suffix(".md").as_posix() in manifest_paths


def main() -> None:
    args = parse_args()
    index_root = args.index_root.expanduser().resolve()
    manifest = [
        json.loads(line)
        for line in (index_root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    manifest_paths = {str(item["relative_path"]) for item in manifest}
    with (index_root / "extraction_report.csv").open(encoding="utf-8-sig") as source:
        extraction = {row["sha256"]: row["status"] for row in csv.DictReader(source)}
    content = load_content(index_root / "knowledge_content.sqlite3")

    rows: list[dict[str, object]] = []
    for item in manifest:
        relative_path = str(item["relative_path"])
        layer = relative_path.split("/", 1)[0]
        digest = str(item["sha256"])
        text = content.get(digest, "")
        detected_high_hits = [
            name for name, pattern in HIGH_RISK_PATTERNS.items() if pattern.search(text)
        ]
        high_hits = [
            name for name in detected_high_hits if name in {"credential", "private_key"}
        ]
        review_hits = [name for name, pattern in REVIEW_PATTERNS.items() if pattern.search(text)]
        review_hits.extend(
            name for name in detected_high_hits if name not in {"credential", "private_key"}
        )
        extraction_status = extraction.get(digest, "not_processed")

        object_allowed = False
        semantic_allowed = False
        decision = "excluded"
        rights_status = "not_applicable"

        if layer == "00_系统与索引" or relative_path == "README.md":
            decision = "metadata_sidecar"
        elif layer == "90_受限资料" or item["upload_action"] == "restricted_excluded":
            decision = "restricted_excluded"
        elif item["sensitivity"] in {"confidential", "restricted"}:
            decision = "confidential_excluded"
        elif high_hits:
            decision = "blocked_high_risk_dlp"
        elif extraction_status in NO_SEMANTIC_TEXT_STATUSES:
            object_allowed = layer not in {"00_系统与索引", "90_受限资料"}
            decision = "object_only_no_semantic_text"
            rights_status = (
                "public_source_provenance_pending"
                if layer in {"10_政策与目录", "20_申报指南与规则", "50_名单与对标"}
                else "owner_or_public_source_confirmed_2026-07-17"
            )
        elif extraction_status == "ocr_required" and has_ocr_sidecar(
            relative_path, manifest_paths
        ):
            object_allowed = True
            decision = "ocr_sidecar_ready"
            rights_status = (
                "public_source_provenance_pending"
                if layer in {"10_政策与目录", "20_申报指南与规则", "50_名单与对标"}
                else "owner_or_public_source_confirmed_2026-07-17"
            )
        elif layer in {"10_政策与目录", "20_申报指南与规则", "50_名单与对标"}:
            object_allowed = True
            semantic_allowed = extraction_status == "indexed"
            decision = "semantic_ready" if semantic_allowed else "object_only_pending_extraction"
            rights_status = "public_source_provenance_pending"
        elif layer in {
            "30_空白模板",
            "40_内部培训与方法",
            "60_脱敏案例",
            "60_申报案例与建设方案",
            "70_知识产权方法",
        }:
            object_allowed = True
            semantic_allowed = extraction_status == "indexed"
            decision = "semantic_ready" if semantic_allowed else "object_only_pending_extraction"
            rights_status = "owner_or_public_source_confirmed_2026-07-17"

        rows.append(
            {
                "relative_path": relative_path,
                "sha256": digest,
                "size_bytes": item["size_bytes"],
                "layer": layer,
                "sensitivity": item["sensitivity"],
                "extraction_status": extraction_status,
                "high_risk_hits": "|".join(high_hits),
                "review_hits": "|".join(review_hits),
                "rights_status": rights_status,
                "object_storage_allowed": str(object_allowed).lower(),
                "semantic_index_allowed": str(semantic_allowed).lower(),
                "decision": decision,
            }
        )

    fields = [
        "relative_path", "sha256", "size_bytes", "layer", "sensitivity",
        "extraction_status", "high_risk_hits", "review_hits", "rights_status",
        "object_storage_allowed", "semantic_index_allowed", "decision",
    ]
    with (index_root / "upload_allowlist.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": len(rows),
        "decisions": dict(Counter(str(row["decision"]) for row in rows)),
        "object_storage_allowed": sum(row["object_storage_allowed"] == "true" for row in rows),
        "semantic_index_allowed": sum(row["semantic_index_allowed"] == "true" for row in rows),
        "high_risk_blocked": sum(bool(row["high_risk_hits"]) for row in rows),
        "review_flagged": sum(bool(row["review_hits"]) for row in rows),
    }
    (index_root / "upload_allowlist_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    from scripts.build_small_giant_identity_graph import (
        DEFAULT_REGISTRY,
        USCC_PATTERN,
        normalize_name,
    )
except ModuleNotFoundError:
    from build_small_giant_identity_graph import DEFAULT_REGISTRY, USCC_PATTERN, normalize_name


DEFAULT_DB = Path("/Volumes/知识库/_云端迁移索引/cloud_package_index/knowledge_content.sqlite3")
DEFAULT_OUTPUT = Path(
    "/Volumes/知识库/_云端知识库/50_名单与对标/优质中小企业梯度培育/"
    "_全国小巨人批次主表/企业身份关联"
)
DEFAULT_IMPORT = DEFAULT_OUTPUT / "企业身份公开信息核验结果.csv"
ALLOWED_SOURCE_TYPES = {
    "qcc",
    "government_public",
    "listed_company_disclosure",
    "company_official",
    "manual_verified",
}
ALLOWED_EVENT_TYPES = {
    "exact_identity",
    "former_name",
    "rename",
    "relocation",
    "merger",
    "reorganization",
    "same_name_disambiguation",
}
REGION_PATTERN = re.compile(
    r"^(|北京市|天津市|上海市|重庆市|.+省|.+自治区|新疆生产建设兵团)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立企业更名、同名、迁址与合并公开证据队列")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--import-file", type=Path, default=DEFAULT_IMPORT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {key: str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def write_template(path: Path) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "enterprise_name",
                "former_name",
                "unified_social_credit_code",
                "province",
                "city",
                "former_province",
                "former_city",
                "event_type",
                "source_type",
                "source_reference",
                "source_name",
                "verified_at",
                "verification_note",
            ],
        )
        writer.writeheader()


def write_queue(connection: sqlite3.Connection, output: Path) -> int:
    rows = connection.execute(
        """
        SELECT enterprise_name,normalized_name,region,city,qice_eid,
               GROUP_CONCAT(DISTINCT batch) AS batches,
               GROUP_CONCAT(DISTINCT recognition_year) AS recognition_years
        FROM national_small_giant_master
        WHERE unified_social_credit_code=''
        GROUP BY normalized_name,region,city,qice_eid
        ORDER BY region,city,enterprise_name
        """
    ).fetchall()
    fields = [
        "enterprise_name",
        "normalized_name",
        "expected_region",
        "expected_city",
        "qice_eid",
        "batches",
        "recognition_years",
        "qcc_query",
        "public_query",
        "required_checks",
        "status",
    ]
    with (output / "企业身份多源待核验队列.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            name = str(row["enterprise_name"])
            writer.writerow(
                {
                    "enterprise_name": name,
                    "normalized_name": row["normalized_name"],
                    "expected_region": row["region"],
                    "expected_city": row["city"],
                    "qice_eid": row["qice_eid"],
                    "batches": row["batches"],
                    "recognition_years": row["recognition_years"],
                    "qcc_query": name,
                    "public_query": f'"{name}" 更名 OR 曾用名 OR 迁址 OR 合并',
                    "required_checks": "同名主体、曾用名、迁址、合并重组、信用代码",
                    "status": "pending_multi_source_identity_check",
                }
            )
    return len(rows)


def validate(item: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    if not item.get("enterprise_name"):
        reasons.append("企业名称为空")
    code = item.get("unified_social_credit_code", "").upper()
    if code and not USCC_PATTERN.fullmatch(code):
        reasons.append("统一社会信用代码格式无效")
    if not REGION_PATTERN.fullmatch(item.get("province", "")):
        reasons.append("省级地区字段无效")
    if item.get("event_type") not in ALLOWED_EVENT_TYPES:
        reasons.append("事件类型不在允许清单")
    if item.get("source_type") not in ALLOWED_SOURCE_TYPES:
        reasons.append("来源类型不在允许清单")
    if not item.get("source_reference"):
        reasons.append("来源引用为空")
    return reasons


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    write_template(args.import_file)
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    pending_count = write_queue(connection, args.output)
    imported = read_csv(args.import_file)
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for item in imported:
        reasons = validate(item)
        if reasons:
            rejected.append({**item, "rejection_reason": "；".join(reasons)})
        else:
            accepted.append(
                {
                    **item,
                    "unified_social_credit_code": item.get(
                        "unified_social_credit_code", ""
                    ).upper(),
                }
            )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS enterprise_identity_evidence(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            former_name TEXT NOT NULL DEFAULT '',
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            province TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            former_province TEXT NOT NULL DEFAULT '',
            former_city TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_reference TEXT NOT NULL,
            source_name TEXT NOT NULL DEFAULT '',
            verified_at TEXT NOT NULL,
            verification_note TEXT NOT NULL DEFAULT '',
            imported_at TEXT NOT NULL,
            UNIQUE(normalized_name,event_type,source_type,source_reference)
        );
        CREATE INDEX IF NOT EXISTS enterprise_identity_evidence_name_idx
            ON enterprise_identity_evidence(normalized_name,unified_social_credit_code);
        """
    )
    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    connection.executemany(
        """
        INSERT OR REPLACE INTO enterprise_identity_evidence(
            enterprise_name,normalized_name,former_name,unified_social_credit_code,
            province,city,former_province,former_city,event_type,source_type,
            source_reference,source_name,verified_at,verification_note,imported_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                item["enterprise_name"],
                normalize_name(item["enterprise_name"]),
                item.get("former_name", ""),
                item.get("unified_social_credit_code", ""),
                item.get("province", ""),
                item.get("city", ""),
                item.get("former_province", ""),
                item.get("former_city", ""),
                item["event_type"],
                item["source_type"],
                item["source_reference"],
                item.get("source_name", ""),
                item.get("verified_at", "") or imported_at,
                item.get("verification_note", ""),
                imported_at,
            )
            for item in accepted
        ],
    )

    registry_rows = read_csv(args.registry)
    registry_keys = {
        (
            normalize_name(item.get("enterprise_name", "")),
            item.get("unified_social_credit_code", "").upper(),
        )
        for item in registry_rows
    }
    for item in accepted:
        code = item.get("unified_social_credit_code", "")
        if not code:
            continue
        key = (normalize_name(item["enterprise_name"]), code)
        if key in registry_keys:
            continue
        registry_rows.append(
            {
                "enterprise_name": item["enterprise_name"],
                "unified_social_credit_code": code,
                "province": item.get("province", ""),
                "city": item.get("city", ""),
                "former_name": item.get("former_name", ""),
                "event_type": item["event_type"],
                "source_url": item["source_reference"],
                "source_name": item.get("source_name", "") or item["source_type"],
                "verified_at": item.get("verified_at", "") or imported_at,
            }
        )
        registry_keys.add(key)
    registry_fields = [
        "enterprise_name",
        "unified_social_credit_code",
        "province",
        "city",
        "former_name",
        "event_type",
        "source_url",
        "source_name",
        "verified_at",
    ]
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    with args.registry.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=registry_fields)
        writer.writeheader()
        writer.writerows(
            [{key: item.get(key, "") for key in registry_fields} for item in registry_rows]
        )
    connection.commit()
    connection.close()

    rejection_fields = sorted(
        {key for item in rejected for key in item} | {"rejection_reason"}
    )
    with (args.output / "企业身份公开信息导入拒绝清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=rejection_fields)
        writer.writeheader()
        writer.writerows(rejected)
    report = {
        "generated_at": imported_at,
        "schema_version": 1,
        "pending_identity_checks": pending_count,
        "accepted_evidence_rows": len(accepted),
        "rejected_rows": len(rejected),
        "registry_rows": len(registry_rows),
        "rules": [
            "精确规范名称优先，模糊名称只能生成候选。",
            "企查查可用于更名、同名、迁址和合并重组的增强核验。",
            "企查查不可用时使用政府公开信息、上市公司公告或企业官网交叉核验。",
            "同名多主体、跨地区冲突和合并重组不得自动覆盖。",
            "统一社会信用代码仅接受来源明确的证据，不根据名称推算。",
        ],
    }
    (args.output / "企业身份多源核验报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

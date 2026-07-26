#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from scripts.build_small_giant_identity_graph import DEFAULT_REGISTRY, USCC_PATTERN, normalize_name
except ModuleNotFoundError:
    from build_small_giant_identity_graph import DEFAULT_REGISTRY, USCC_PATTERN, normalize_name


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_OUTPUT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/"
    "_全国小巨人批次主表/企业身份关联"
)
DEFAULT_IMPORT = DEFAULT_OUTPUT / "国家企业信用信息公示系统核验结果.csv"
GSXT_HOME = "https://www.gsxt.gov.cn/index.html"
REGION_PATTERN = re.compile(
    r"^(北京市|天津市|上海市|重庆市|.+省|.+自治区|新疆生产建设兵团)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成国家企业信用信息公示系统核验队列并导入权威映射")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--import-file", type=Path, default=DEFAULT_IMPORT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    return parser.parse_args()


def official_gsxt_url(value: str) -> bool:
    try:
        hostname = (urlparse(value).hostname or "").lower()
    except ValueError:
        return False
    return hostname == "gsxt.gov.cn" or hostname.endswith(".gsxt.gov.cn")


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
                "unified_social_credit_code",
                "province",
                "city",
                "source_url",
                "source_name",
                "verified_at",
                "verification_note",
            ],
        )
        writer.writeheader()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    write_template(args.import_file)
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
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
    queue_fields = [
        "enterprise_name",
        "normalized_name",
        "expected_region",
        "expected_city",
        "qice_eid",
        "batches",
        "recognition_years",
        "exact_query",
        "official_search_url",
        "status",
    ]
    with (args.output / "国家企业信用信息公示系统待核验队列.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=queue_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "enterprise_name": row["enterprise_name"],
                    "normalized_name": row["normalized_name"],
                    "expected_region": row["region"],
                    "expected_city": row["city"],
                    "qice_eid": row["qice_eid"],
                    "batches": row["batches"],
                    "recognition_years": row["recognition_years"],
                    "exact_query": row["enterprise_name"],
                    "official_search_url": GSXT_HOME,
                    "status": "pending_official_exact_name_query",
                }
            )
    imported = read_csv(args.import_file)
    valid: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for item in imported:
        code = item.get("unified_social_credit_code", "").upper()
        name = item.get("enterprise_name", "")
        region = item.get("province", "")
        source_url = item.get("source_url", "")
        reasons = []
        if not name:
            reasons.append("企业名称为空")
        if not USCC_PATTERN.fullmatch(code):
            reasons.append("统一社会信用代码格式无效")
        if not REGION_PATTERN.fullmatch(region):
            reasons.append("省级地区字段无效")
        if not official_gsxt_url(source_url):
            reasons.append("来源链接不是国家企业信用信息公示系统域名")
        if reasons:
            rejected.append({**item, "rejection_reason": "；".join(reasons)})
        else:
            valid.append({**item, "unified_social_credit_code": code})
    by_name: dict[str, set[str]] = {}
    for item in valid:
        by_name.setdefault(normalize_name(item["enterprise_name"]), set()).add(
            item["unified_social_credit_code"]
        )
    conflict_names = {name for name, codes in by_name.items() if len(codes) > 1}
    accepted = [
        item for item in valid if normalize_name(item["enterprise_name"]) not in conflict_names
    ]
    registry_rows = read_csv(args.registry)
    registry_key = {
        (
            normalize_name(item.get("enterprise_name", "")),
            item.get("unified_social_credit_code", "").upper(),
        )
        for item in registry_rows
    }
    for item in accepted:
        key = (normalize_name(item["enterprise_name"]), item["unified_social_credit_code"])
        if key in registry_key:
            continue
        registry_rows.append(
            {
                "enterprise_name": item["enterprise_name"],
                "unified_social_credit_code": item["unified_social_credit_code"],
                "province": item["province"],
                "city": item.get("city", ""),
                "former_name": "",
                "event_type": "gsxt_exact_name_identity",
                "source_url": item["source_url"],
                "source_name": item.get("source_name", "") or "国家企业信用信息公示系统",
                "verified_at": item.get("verified_at", "") or datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        )
        registry_key.add(key)
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
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS gsxt_enterprise_identity_evidence(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            unified_social_credit_code TEXT NOT NULL,
            province TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL,
            source_name TEXT NOT NULL,
            verified_at TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            UNIQUE(normalized_name,unified_social_credit_code,source_url)
        );
        """
    )
    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    connection.executemany(
        """
        INSERT OR REPLACE INTO gsxt_enterprise_identity_evidence(
            enterprise_name,normalized_name,unified_social_credit_code,
            province,city,source_url,source_name,verified_at,imported_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                item["enterprise_name"],
                normalize_name(item["enterprise_name"]),
                item["unified_social_credit_code"],
                item["province"],
                item.get("city", ""),
                item["source_url"],
                item.get("source_name", "") or "国家企业信用信息公示系统",
                item.get("verified_at", "") or imported_at,
                imported_at,
            )
            for item in accepted
        ],
    )
    connection.commit()
    connection.close()
    rejection_fields = sorted(
        {key for item in rejected for key in item} | {"rejection_reason"}
    )
    with (args.output / "国家企业信用信息公示系统导入拒绝清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=rejection_fields)
        writer.writeheader()
        writer.writerows(rejected)
    conflicts = [
        {
            "normalized_name": name,
            "candidate_codes": "、".join(sorted(by_name[name])),
            "reason": "同一规范化企业名称对应多个统一社会信用代码",
        }
        for name in sorted(conflict_names)
    ]
    with (args.output / "国家企业信用信息公示系统导入冲突清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["normalized_name", "candidate_codes", "reason"],
        )
        writer.writeheader()
        writer.writerows(conflicts)
    report = {
        "generated_at": imported_at,
        "schema_version": 1,
        "pending_exact_name_queries": len(rows),
        "import_file": str(args.import_file),
        "accepted_evidence_rows": len(accepted),
        "rejected_rows": len(rejected),
        "conflict_names": len(conflict_names),
        "registry_rows": len(registry_rows),
        "rules": [
            "禁止调用企查查补全统一社会信用代码。",
            "只接受国家企业信用信息公示系统官方域名页面作为来源。",
            "验证码、实名登录和访问频率限制必须由人工合规完成，不绕过访问控制。",
            "同名多代码、地区冲突和更名迁址进入人工核验，不自动覆盖。",
        ],
    }
    (args.output / "国家企业信用信息公示系统映射报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

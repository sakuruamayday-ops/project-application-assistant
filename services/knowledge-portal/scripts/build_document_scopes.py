from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ZHEJIANG_CITIES = (
    "杭州市",
    "宁波市",
    "温州市",
    "嘉兴市",
    "湖州市",
    "绍兴市",
    "金华市",
    "衢州市",
    "舟山市",
    "台州市",
    "丽水市",
)
PROVINCE_REGIONS = (
    "北京市",
    "天津市",
    "上海市",
    "重庆市",
    "河北省",
    "山西省",
    "辽宁省",
    "吉林省",
    "黑龙江省",
    "江苏省",
    "浙江省",
    "安徽省",
    "福建省",
    "江西省",
    "山东省",
    "河南省",
    "湖北省",
    "湖南省",
    "广东省",
    "海南省",
    "四川省",
    "贵州省",
    "云南省",
    "陕西省",
    "甘肃省",
    "青海省",
    "内蒙古自治区",
    "广西壮族自治区",
    "西藏自治区",
    "宁夏回族自治区",
    "新疆维吾尔自治区",
    "新疆生产建设兵团",
)
YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
RULE_VERSION = "document-scopes-v1.0.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立规范文档、作用域和虚拟目录索引")
    parser.add_argument("--database", type=Path, required=True)
    return parser.parse_args()


def create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS canonical_documents (
            canonical_document_id INTEGER PRIMARY KEY REFERENCES documents(id),
            sha256 TEXT NOT NULL UNIQUE,
            duplicate_count INTEGER NOT NULL,
            preferred_basis TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS document_duplicates (
            document_id INTEGER PRIMARY KEY REFERENCES documents(id),
            canonical_document_id INTEGER NOT NULL REFERENCES documents(id),
            duplicate_kind TEXT NOT NULL,
            duplicate_basis TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS document_duplicates_canonical_idx
            ON document_duplicates(canonical_document_id,document_id);
        CREATE TABLE IF NOT EXISTS document_scopes (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            scope_type TEXT NOT NULL,
            scope_value TEXT NOT NULL,
            scope_level TEXT NOT NULL,
            scope_basis TEXT NOT NULL,
            confidence TEXT NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            rule_version TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(document_id,scope_type,scope_value)
        );
        CREATE INDEX IF NOT EXISTS document_scopes_lookup_idx
            ON document_scopes(scope_type,scope_value,document_id);
        CREATE TABLE IF NOT EXISTS virtual_catalog_entries (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            virtual_path TEXT NOT NULL,
            catalog_role TEXT NOT NULL,
            sort_key TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(document_id,virtual_path)
        );
        CREATE INDEX IF NOT EXISTS virtual_catalog_path_idx
            ON virtual_catalog_entries(virtual_path,document_id);
        """
    )


def official_source_score(content: str, source: str) -> int:
    value = f"{content[:4000]} {source}".lower()
    if any(host in value for host in (".gov.cn", "gov.cn/", "miit.gov.cn")):
        return 0
    return 1


def role_score(role: str, stage: str) -> int:
    if stage in {"公示名单", "认定名单"}:
        order = {"50_名单与对标": 0, "10_政策与通知": 1, "10_政策与目录": 1}
    else:
        order = {
            "10_政策与通知": 0,
            "10_政策与目录": 0,
            "20_项目规则与指南": 1,
            "20_申报指南与规则": 1,
            "50_名单与对标": 2,
        }
    return order.get(role, 5)


def evidence_stage_score(row: sqlite3.Row) -> int:
    value = " ".join(
        (
            str(row["title"] or ""),
            str(row["source"] or ""),
            str(row["cloud_path"] or ""),
            str(row["document_stage"] or ""),
        )
    )
    if any(term in value for term in ("正式认定_", "复核通过_", "认定名单", "公布名单", "通过名单")):
        return 0
    if any(term in value for term in ("公示过程_", "拟认定", "公示名单", "推荐名单")):
        return 2
    return 1


def canonical_sort_key(row: sqlite3.Row) -> tuple[object, ...]:
    source = str(row["source"] or "")
    cloud_path = str(row["cloud_path"] or "")
    return (
        evidence_stage_score(row),
        role_score(str(row["document_role"]), str(row["document_stage"])),
        official_source_score(str(row["content"] or ""), source),
        1 if "/政策数据库/企策顾问/" in source else 0,
        len(cloud_path or source),
        int(row["id"]),
    )


def path_regions(value: str) -> set[tuple[str, str]]:
    regions: set[tuple[str, str]] = set()
    for province in PROVINCE_REGIONS:
        if province in value:
            regions.add((province, "province"))
    for city in ZHEJIANG_CITIES:
        if city in value or city.removesuffix("市") in value:
            regions.add((city, "city"))
    return regions


def document_regions(row: sqlite3.Row) -> set[tuple[str, str]]:
    regions = path_regions(
        " ".join(
            (
                str(row["region"] or ""),
                str(row["source"] or ""),
                str(row["cloud_path"] or ""),
                str(row["title"] or ""),
            )
        )
    )
    region = str(row["region"] or "").strip()
    if region:
        if region in PROVINCE_REGIONS:
            regions.add((region, "province"))
        elif region.endswith("市"):
            regions.add((region, "city"))
        else:
            regions.add((region, "administrative"))
    return regions


def scope_rows(
    canonical: sqlite3.Row,
    members: list[sqlite3.Row],
    now: str,
) -> list[tuple[object, ...]]:
    scopes: dict[tuple[str, str], tuple[str, str, str, int]] = {}

    def add(
        scope_type: str,
        scope_value: str,
        scope_level: str,
        basis: str,
        confidence: str,
        is_primary: int = 0,
    ) -> None:
        if not scope_value:
            return
        key = (scope_type, scope_value)
        previous = scopes.get(key)
        candidate = (scope_level, basis, confidence, is_primary)
        if previous is None or is_primary > previous[3]:
            scopes[key] = candidate

    canonical_regions = document_regions(canonical)
    all_regions: set[tuple[str, str]] = set()
    for member in members:
        all_regions.update(document_regions(member))
    for value, level in all_regions:
        add(
            "administrative",
            value,
            level,
            "canonical_metadata" if (value, level) in canonical_regions else "duplicate_source_path",
            "high" if (value, level) in canonical_regions else "medium",
            1 if (value, level) in canonical_regions else 0,
        )
    title_regions = path_regions(str(canonical["title"] or ""))
    has_city_specific_title = any(level == "city" for _, level in title_regions)
    if ("浙江省", "province") in all_regions and not has_city_specific_title:
        for city in ZHEJIANG_CITIES:
            add(
                "applicable_city",
                city,
                "city",
                "province_to_city_inheritance",
                "high",
            )
    project_name = str(canonical["canonical_project_name"] or "").strip()
    add("project", project_name, "project", "canonical_metadata", "high", 1)
    stage = str(canonical["document_stage"] or "").strip()
    add("document_stage", stage, "stage", "canonical_metadata", "high", 1)
    year = canonical["policy_year"]
    if year:
        add("year", str(year), "year", "canonical_metadata", "high", 1)
    batch = str(canonical["batch"] or "").strip()
    add("batch", batch, "batch", "canonical_metadata", "high", 1)
    source_layer = (
        "动态层"
        if any("/政策数据库/企策顾问/" in str(member["source"] or "") for member in members)
        else "规则层"
    )
    add("source_layer", source_layer, "source_layer", "source_path", "high", 1)
    return [
        (
            int(canonical["id"]),
            scope_type,
            scope_value,
            scope_level,
            basis,
            confidence,
            is_primary,
            RULE_VERSION,
            now,
        )
        for (scope_type, scope_value), (
            scope_level,
            basis,
            confidence,
            is_primary,
        ) in sorted(scopes.items())
    ]


def virtual_catalog_role(role: str, stage: str) -> str:
    if role.startswith("50_") or stage in {"公示名单", "认定名单"}:
        return "结构化名单"
    if role.startswith(("10_", "20_")):
        return "政策原文"
    if role.startswith("60_"):
        return "申报案例"
    if role.startswith(("30_", "40_")):
        return "模板与方法"
    return "知识资料"


def safe_segment(value: object, fallback: str) -> str:
    normalized = re.sub(r"[/\\:\n\r\t]+", "／", str(value or "").strip())
    return normalized or fallback


def virtual_paths(
    canonical: sqlite3.Row,
    scopes: list[tuple[object, ...]],
    now: str,
) -> list[tuple[object, ...]]:
    catalog_role = virtual_catalog_role(
        str(canonical["document_role"]), str(canonical["document_stage"])
    )
    regions = [
        str(scope[2])
        for scope in scopes
        if scope[1] in {"administrative", "applicable_city"}
    ] or ["全国"]
    project = safe_segment(canonical["canonical_project_name"], "未归类项目")
    stage = safe_segment(canonical["document_stage"], "其他")
    year = canonical["policy_year"]
    if not year:
        match = YEAR_PATTERN.search(str(canonical["title"]))
        year = int(match.group(1)) if match else None
    year_segment = str(year) if year else "未标年度"
    title = safe_segment(canonical["title"], f"文档{canonical['id']}")
    rows: list[tuple[object, ...]] = []
    for region in sorted(set(regions)):
        virtual_path = "/".join(
            (
                catalog_role,
                safe_segment(region, "全国"),
                project,
                year_segment,
                stage,
                title,
            )
        )
        rows.append(
            (
                int(canonical["id"]),
                virtual_path,
                catalog_role,
                f"{catalog_role}|{region}|{project}|{year_segment}|{stage}|{title}",
                RULE_VERSION,
                now,
            )
        )
    return rows


def rebuild_document_scopes(connection: sqlite3.Connection) -> dict[str, int]:
    connection.row_factory = sqlite3.Row
    create_tables(connection)
    rows = connection.execute(
        """
        SELECT id,source_key,title,content,source,cloud_path,document_role,sha256,
               canonical_project_name,region,document_stage,policy_year,batch
        FROM documents
        ORDER BY id
        """
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[str(row["sha256"] or f"document:{row['id']}")].append(row)

    connection.execute("DELETE FROM virtual_catalog_entries")
    connection.execute("DELETE FROM document_scopes")
    connection.execute("DELETE FROM document_duplicates")
    connection.execute("DELETE FROM canonical_documents")
    now = datetime.now(timezone.utc).isoformat()
    canonical_rows: list[tuple[object, ...]] = []
    duplicate_rows: list[tuple[object, ...]] = []
    all_scope_rows: list[tuple[object, ...]] = []
    all_virtual_rows: list[tuple[object, ...]] = []
    duplicate_groups = 0
    duplicate_documents = 0
    for sha256, members in grouped.items():
        canonical = min(members, key=canonical_sort_key)
        if len(members) > 1:
            duplicate_groups += 1
            duplicate_documents += len(members) - 1
        canonical_rows.append(
            (
                int(canonical["id"]),
                sha256,
                len(members),
                "role_official_dynamic_path_priority",
                RULE_VERSION,
                now,
            )
        )
        for member in members:
            duplicate_rows.append(
                (
                    int(member["id"]),
                    int(canonical["id"]),
                    "canonical" if member["id"] == canonical["id"] else "exact_sha256",
                    "sha256",
                    RULE_VERSION,
                    now,
                )
            )
        scopes = scope_rows(canonical, members, now)
        all_scope_rows.extend(scopes)
        all_virtual_rows.extend(virtual_paths(canonical, scopes, now))

    connection.executemany(
        """
        INSERT INTO canonical_documents(
            canonical_document_id,sha256,duplicate_count,preferred_basis,rule_version,updated_at
        ) VALUES (?,?,?,?,?,?)
        """,
        canonical_rows,
    )
    connection.executemany(
        """
        INSERT INTO document_duplicates(
            document_id,canonical_document_id,duplicate_kind,duplicate_basis,rule_version,updated_at
        ) VALUES (?,?,?,?,?,?)
        """,
        duplicate_rows,
    )
    connection.executemany(
        """
        INSERT INTO document_scopes(
            document_id,scope_type,scope_value,scope_level,scope_basis,confidence,
            is_primary,rule_version,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        all_scope_rows,
    )
    connection.executemany(
        """
        INSERT INTO virtual_catalog_entries(
            document_id,virtual_path,catalog_role,sort_key,rule_version,updated_at
        ) VALUES (?,?,?,?,?,?)
        """,
        all_virtual_rows,
    )
    connection.commit()
    return {
        "documents": len(rows),
        "canonical_documents": len(grouped),
        "duplicate_groups": duplicate_groups,
        "duplicate_documents": duplicate_documents,
        "document_scopes": len(all_scope_rows),
        "virtual_catalog_entries": len(all_virtual_rows),
    }


def main() -> None:
    args = parse_args()
    database = args.database.expanduser().resolve()
    connection = sqlite3.connect(database)
    try:
        result = rebuild_document_scopes(connection)
    finally:
        connection.close()
    print(result)


if __name__ == "__main__":
    main()

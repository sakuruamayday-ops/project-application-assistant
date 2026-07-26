#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_SMALL_GIANT_MASTER = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/"
    "_全国小巨人批次主表/全国小巨人企业级主表.csv"
)
DEFAULT_THREE_FIRST = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/三首项目/"
    "_结构化数据/三首项目企业产品年度记录.jsonl"
)
DEFAULT_OUTPUT = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省")
DEFAULT_TYC_ENRICHMENT = DEFAULT_OUTPUT / "天眼查企业身份核验结果.csv"
USCC_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
YEAR_PATTERN = re.compile(r"20\d{2}")
TARGET_PROJECTS = {
    "国家专精特新“小巨人”企业",
    "浙江省专精特新中小企业",
    "专精特新中小企业",
    "地方科技小巨人企业",
    "浙江制造精品",
    "浙江省首版次软件产品",
    "浙江省首批次新材料",
    "浙江省制造业首台（套）装备",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建浙江省企业身份与认定事件时间轴")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--small-giant-master", type=Path, default=DEFAULT_SMALL_GIANT_MASTER)
    parser.add_argument("--three-first", type=Path, default=DEFAULT_THREE_FIRST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tyc-enrichment", type=Path, default=DEFAULT_TYC_ENRICHMENT)
    return parser.parse_args()


def normalize_name(value: str) -> str:
    value = re.sub(r"[“”\"'‘’]", "", value or "")
    return re.sub(r"[\s·•（）()\-—_，,。．]+", "", value).lower()


def normalize_region(value: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in re.split(r"[|/、]", value or "") if part.strip()]
    province = next((part for part in parts if part.endswith(("省", "自治区"))), "")
    city = next((part for part in parts if part.endswith("市") and part not in {"浙江省"}), "")
    county = next(
        (
            part
            for part in parts
            if part.endswith(("区", "县", "市"))
            and part not in {province, city}
        ),
        "",
    )
    if "浙江" in value and not province:
        province = "浙江省"
    return province, city, county


def first_year(*values: Any) -> int | None:
    years: list[int] = []
    for value in values:
        years.extend(int(item) for item in YEAR_PATTERN.findall(str(value or "")))
    return min(years) if years else None


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {key: str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def ensure_tyc_template(path: Path) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query_name",
                "enterprise_name",
                "unified_social_credit_code",
                "tyc_company_id",
                "former_names_json",
                "name_events_json",
                "current_province",
                "current_city",
                "current_county",
                "current_address",
                "registration_authority",
                "source_tools",
                "source_data_updated_at",
                "verified_at",
                "verification_note",
            ],
        )
        writer.writeheader()


def add_event(
    events: dict[tuple[str, str, int | None, str, str], dict[str, Any]],
    *,
    enterprise_name: str,
    project_name: str,
    year: int | None,
    batch: str,
    status: str,
    province: str,
    city: str,
    county: str,
    source_title: str,
    source_path: str,
    source_url: str,
    sequence_no: str = "",
    source_kind: str = "official_or_archived_list",
) -> None:
    enterprise_name = enterprise_name.strip()
    if not enterprise_name:
        return
    key = (normalize_name(enterprise_name), project_name, year, batch, status)
    item = events.setdefault(
        key,
        {
            "enterprise_name_at_event": enterprise_name,
            "normalized_name": normalize_name(enterprise_name),
            "project_name": project_name,
            "recognition_year": year,
            "batch": batch,
            "status": status,
            "recognition_province": province,
            "recognition_city": city,
            "recognition_county": county,
            "source_title": source_title,
            "source_paths": set(),
            "source_urls": set(),
            "sequence_numbers": set(),
            "source_kinds": set(),
        },
    )
    if source_path:
        item["source_paths"].add(source_path)
    if source_url:
        item["source_urls"].add(source_url)
    if sequence_no:
        item["sequence_numbers"].add(sequence_no)
    if source_kind:
        item["source_kinds"].add(source_kind)
    if not item["recognition_city"] and city:
        item["recognition_city"] = city
    if not item["recognition_county"] and county:
        item["recognition_county"] = county


def load_small_giant_events(
    path: Path,
    events: dict[tuple[str, str, int | None, str, str], dict[str, Any]],
) -> None:
    for row in read_csv(path):
        if row.get("region") != "浙江省":
            continue
        add_event(
            events,
            enterprise_name=row.get("enterprise_name", ""),
            project_name="国家专精特新“小巨人”企业",
            year=int(row["recognition_year"]) if row.get("recognition_year", "").isdigit() else None,
            batch=row.get("batch", ""),
            status=row.get("status", ""),
            province="浙江省",
            city=row.get("city", ""),
            county=row.get("county", ""),
            source_title="全国小巨人企业级主表",
            source_path="、".join(json.loads(row.get("source_paths") or "[]")),
            source_url=row.get("official_url", ""),
            sequence_no=row.get("sequence_no", ""),
            source_kind=row.get("official_url_role", "") or "official_batch_master",
        )


def load_list_events(
    database: Path,
    events: dict[tuple[str, str, int | None, str, str], dict[str, Any]],
) -> None:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT e.enterprise_name,e.sequence_no,e.canonical_project_name,e.policy_year,
               e.batch,e.region,e.list_status,d.title,d.source,d.cloud_path,
               d.canonical_project_name AS document_project,d.policy_year AS document_year
        FROM public_list_entities e
        JOIN documents d ON d.id=e.document_id
        WHERE d.document_role='50_名单与对标'
          AND (
              e.region LIKE '%浙江%'
              OR d.region LIKE '%浙江%'
              OR d.title LIKE '%浙江%'
          )
        """
    ).fetchall()
    connection.close()
    for row in rows:
        project_name = str(row["canonical_project_name"] or row["document_project"] or "").strip()
        if project_name == "国家专精特新“小巨人”企业":
            continue
        if project_name not in TARGET_PROJECTS:
            continue
        province, city, county = normalize_region(str(row["region"]))
        add_event(
            events,
            enterprise_name=str(row["enterprise_name"]),
            project_name=project_name,
            year=row["policy_year"] or row["document_year"] or first_year(row["title"]),
            batch=str(row["batch"] or ""),
            status=str(row["list_status"] or ""),
            province=province or "浙江省",
            city=city,
            county=county,
            source_title=str(row["title"]),
            source_path=str(row["cloud_path"] or row["source"] or ""),
            source_url="",
            sequence_no=str(row["sequence_no"] or ""),
        )


def load_three_first_events(
    path: Path,
    events: dict[tuple[str, str, int | None, str, str], dict[str, Any]],
) -> None:
    for row in read_jsonl(path):
        province = str(row.get("province") or "")
        if province not in {"浙江", "浙江省", ""}:
            continue
        project_name = str(row.get("project_name") or "")
        if project_name not in TARGET_PROJECTS:
            continue
        add_event(
            events,
            enterprise_name=str(row.get("enterprise_name") or ""),
            project_name=project_name,
            year=int(row["year"]) if str(row.get("year") or "").isdigit() else None,
            batch="",
            status=str(row.get("list_status") or ""),
            province="浙江省",
            city=str(row.get("city") or ""),
            county=str(row.get("county") or ""),
            source_title=str(row.get("source_title") or ""),
            source_path="",
            source_url=str(row.get("source_url") or ""),
            source_kind=str(row.get("confidence") or "three_first_product_record"),
        )


def load_tyc_enrichment(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in read_csv(path):
        code = row.get("unified_social_credit_code", "").upper()
        if code and not USCC_PATTERN.fullmatch(code):
            continue
        names = [row.get("query_name", ""), row.get("enterprise_name", "")]
        try:
            names.extend(json.loads(row.get("former_names_json") or "[]"))
        except json.JSONDecodeError:
            pass
        item = {**row, "unified_social_credit_code": code}
        for name in names:
            if name:
                result[normalize_name(str(name))] = item
    return result


def write_outputs(
    database: Path,
    output: Path,
    events: dict[tuple[str, str, int | None, str, str], dict[str, Any]],
    tyc: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    profiles: dict[str, dict[str, Any]] = {}
    event_rows: list[dict[str, Any]] = []
    aliases: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in events.values():
        enrichment = tyc.get(str(item["normalized_name"]), {})
        identity_key = (
            str(enrichment.get("unified_social_credit_code") or "")
            or f"name:{item['normalized_name']}"
        )
        profile = profiles.setdefault(
            identity_key,
            {
                "identity_key": identity_key,
                "unified_social_credit_code": str(enrichment.get("unified_social_credit_code") or ""),
                "current_name": str(enrichment.get("enterprise_name") or item["enterprise_name_at_event"]),
                "tyc_company_id": str(enrichment.get("tyc_company_id") or ""),
                "current_province": str(enrichment.get("current_province") or ""),
                "current_city": str(enrichment.get("current_city") or ""),
                "current_county": str(enrichment.get("current_county") or ""),
                "current_address": str(enrichment.get("current_address") or ""),
                "registration_authority": str(enrichment.get("registration_authority") or ""),
                "identity_source": str(enrichment.get("source_tools") or "list_name_pending_business_registry"),
                "source_data_updated_at": str(enrichment.get("source_data_updated_at") or ""),
                "verified_at": str(enrichment.get("verified_at") or ""),
                "verification_status": "tyc_verified" if enrichment else "pending_business_identity",
                "recognition_names": set(),
                "recognition_regions": set(),
                "recognition_projects": set(),
            },
        )
        profile["recognition_names"].add(str(item["enterprise_name_at_event"]))
        region = "/".join(
            value
            for value in (
                item["recognition_province"],
                item["recognition_city"],
                item["recognition_county"],
            )
            if value
        )
        if region:
            profile["recognition_regions"].add(region)
        profile["recognition_projects"].add(str(item["project_name"]))
        event_rows.append(
            {
                **item,
                "identity_key": identity_key,
                "source_paths": sorted(item["source_paths"]),
                "source_urls": sorted(item["source_urls"]),
                "sequence_numbers": sorted(item["sequence_numbers"]),
                "source_kinds": sorted(item["source_kinds"]),
            }
        )
        aliases[(identity_key, str(item["enterprise_name_at_event"]), "recognition_name")] = {
            "identity_key": identity_key,
            "alias_name": str(item["enterprise_name_at_event"]),
            "alias_type": "recognition_name",
            "valid_from": "",
            "valid_to": "",
            "source": str(item["source_title"]),
        }
    for enrichment in {id(value): value for value in tyc.values()}.values():
        code = str(enrichment.get("unified_social_credit_code") or "")
        current_name = str(enrichment.get("enterprise_name") or "")
        identity_key = code or f"name:{normalize_name(current_name)}"
        profiles.setdefault(
            identity_key,
            {
                "identity_key": identity_key,
                "unified_social_credit_code": code,
                "current_name": current_name,
                "tyc_company_id": str(enrichment.get("tyc_company_id") or ""),
                "current_province": str(enrichment.get("current_province") or ""),
                "current_city": str(enrichment.get("current_city") or ""),
                "current_county": str(enrichment.get("current_county") or ""),
                "current_address": str(enrichment.get("current_address") or ""),
                "registration_authority": str(enrichment.get("registration_authority") or ""),
                "identity_source": str(enrichment.get("source_tools") or "tyc-mcp"),
                "source_data_updated_at": str(enrichment.get("source_data_updated_at") or ""),
                "verified_at": str(enrichment.get("verified_at") or ""),
                "verification_status": "tyc_verified",
                "recognition_names": set(),
                "recognition_regions": set(),
                "recognition_projects": set(),
            },
        )
        try:
            former_names = json.loads(str(enrichment.get("former_names_json") or "[]"))
        except json.JSONDecodeError:
            former_names = []
        for name in former_names:
            aliases[(identity_key, str(name), "former_name")] = {
                "identity_key": identity_key,
                "alias_name": str(name),
                "alias_type": "former_name",
                "valid_from": "",
                "valid_to": "",
                "source": str(enrichment.get("source_tools") or "tyc-mcp"),
            }
        try:
            name_events = json.loads(str(enrichment.get("name_events_json") or "[]"))
        except json.JSONDecodeError:
            name_events = []
        for event in name_events:
            name = str(event.get("name") or "")
            if not name:
                continue
            aliases[(identity_key, name, str(event.get("event_type") or "name_event"))] = {
                "identity_key": identity_key,
                "alias_name": name,
                "alias_type": str(event.get("event_type") or "name_event"),
                "valid_from": str(event.get("valid_from") or ""),
                "valid_to": str(event.get("valid_to") or ""),
                "source": str(event.get("source") or enrichment.get("source_tools") or "tyc-mcp"),
            }
    profile_rows: list[dict[str, Any]] = []
    for item in profiles.values():
        profile_rows.append(
            {
                **item,
                "recognition_names": sorted(item["recognition_names"]),
                "recognition_regions": sorted(item["recognition_regions"]),
                "recognition_projects": sorted(item["recognition_projects"]),
            }
        )
    profile_rows.sort(key=lambda row: row["current_name"])
    event_rows.sort(
        key=lambda row: (
            row["enterprise_name_at_event"],
            row["recognition_year"] or 0,
            row["project_name"],
        )
    )
    alias_rows = sorted(aliases.values(), key=lambda row: (row["identity_key"], row["alias_name"]))

    with (output / "浙江省企业身份主表.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "identity_key",
            "unified_social_credit_code",
            "current_name",
            "recognition_names",
            "tyc_company_id",
            "current_province",
            "current_city",
            "current_county",
            "current_address",
            "registration_authority",
            "recognition_regions",
            "recognition_projects",
            "identity_source",
            "source_data_updated_at",
            "verified_at",
            "verification_status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in profile_rows:
            writer.writerow(
                {
                    **item,
                    "recognition_names": "、".join(item["recognition_names"]),
                    "recognition_regions": "、".join(item["recognition_regions"]),
                    "recognition_projects": "、".join(item["recognition_projects"]),
                }
            )
    for filename, rows in (
        ("浙江省企业认定事件.jsonl", event_rows),
        ("浙江省企业名称历史.jsonl", alias_rows),
        ("浙江省企业身份档案.jsonl", profile_rows),
    ):
        with (output / filename).open("w", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    connection = sqlite3.connect(database)
    connection.executescript(
        """
        DROP TABLE IF EXISTS enterprise_identity_profiles;
        DROP TABLE IF EXISTS enterprise_identity_names;
        DROP TABLE IF EXISTS enterprise_recognition_events;
        CREATE TABLE enterprise_identity_profiles(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            current_name TEXT NOT NULL,
            tyc_company_id TEXT NOT NULL DEFAULT '',
            current_province TEXT NOT NULL DEFAULT '',
            current_city TEXT NOT NULL DEFAULT '',
            current_county TEXT NOT NULL DEFAULT '',
            current_address TEXT NOT NULL DEFAULT '',
            registration_authority TEXT NOT NULL DEFAULT '',
            identity_source TEXT NOT NULL,
            source_data_updated_at TEXT NOT NULL DEFAULT '',
            verified_at TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL,
            recognition_names_json TEXT NOT NULL,
            recognition_regions_json TEXT NOT NULL,
            recognition_projects_json TEXT NOT NULL
        );
        CREATE TABLE enterprise_identity_names(
            id INTEGER PRIMARY KEY,
            identity_key TEXT NOT NULL,
            alias_name TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '',
            valid_to TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            UNIQUE(identity_key,normalized_alias,alias_type,valid_from)
        );
        CREATE TABLE enterprise_recognition_events(
            id INTEGER PRIMARY KEY,
            identity_key TEXT NOT NULL,
            enterprise_name_at_event TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            recognition_year INTEGER,
            batch TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            recognition_province TEXT NOT NULL DEFAULT '',
            recognition_city TEXT NOT NULL DEFAULT '',
            recognition_county TEXT NOT NULL DEFAULT '',
            source_title TEXT NOT NULL DEFAULT '',
            source_paths_json TEXT NOT NULL DEFAULT '[]',
            source_urls_json TEXT NOT NULL DEFAULT '[]',
            sequence_numbers_json TEXT NOT NULL DEFAULT '[]',
            source_kinds_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(identity_key,project_name,recognition_year,batch,status)
        );
        CREATE INDEX enterprise_identity_name_lookup_idx
        ON enterprise_identity_names(normalized_alias);
        CREATE INDEX enterprise_recognition_lookup_idx
        ON enterprise_recognition_events(normalized_name,project_name,recognition_year);
        """
    )
    connection.executemany(
        """
        INSERT INTO enterprise_identity_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                row["identity_key"],
                row["unified_social_credit_code"],
                row["current_name"],
                row["tyc_company_id"],
                row["current_province"],
                row["current_city"],
                row["current_county"],
                row["current_address"],
                row["registration_authority"],
                row["identity_source"],
                row["source_data_updated_at"],
                row["verified_at"],
                row["verification_status"],
                json.dumps(row["recognition_names"], ensure_ascii=False),
                json.dumps(row["recognition_regions"], ensure_ascii=False),
                json.dumps(row["recognition_projects"], ensure_ascii=False),
            )
            for row in profile_rows
        ],
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO enterprise_identity_names(
            identity_key,alias_name,normalized_alias,alias_type,valid_from,valid_to,source
        ) VALUES(?,?,?,?,?,?,?)
        """,
        [
            (
                row["identity_key"],
                row["alias_name"],
                normalize_name(row["alias_name"]),
                row["alias_type"],
                row["valid_from"],
                row["valid_to"],
                row["source"],
            )
            for row in alias_rows
        ],
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO enterprise_recognition_events(
            identity_key,enterprise_name_at_event,normalized_name,project_name,
            recognition_year,batch,status,recognition_province,recognition_city,
            recognition_county,source_title,source_paths_json,source_urls_json,
            sequence_numbers_json,source_kinds_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                row["identity_key"],
                row["enterprise_name_at_event"],
                row["normalized_name"],
                row["project_name"],
                row["recognition_year"],
                row["batch"],
                row["status"],
                row["recognition_province"],
                row["recognition_city"],
                row["recognition_county"],
                row["source_title"],
                json.dumps(row["source_paths"], ensure_ascii=False),
                json.dumps(row["source_urls"], ensure_ascii=False),
                json.dumps(row["sequence_numbers"], ensure_ascii=False),
                json.dumps(row["source_kinds"], ensure_ascii=False),
            )
            for row in event_rows
        ],
    )
    connection.commit()
    integrity = (
        "ok"
        if connection.execute(
            "SELECT COUNT(*) FROM enterprise_identity_profiles"
        ).fetchone()[0]
        == len(profile_rows)
        else "identity_profile_count_mismatch"
    )
    connection.close()
    report = {
        "generated_at": generated_at,
        "schema_version": 1,
        "scope": "浙江省优质中小企业梯度培育、科技小巨人、三首与浙江制造精品",
        "enterprise_profiles": len(profile_rows),
        "recognition_events": len(event_rows),
        "name_records": len(alias_rows),
        "tyc_verified_profiles": sum(row["verification_status"] == "tyc_verified" for row in profile_rows),
        "pending_business_identity": sum(
            row["verification_status"] == "pending_business_identity" for row in profile_rows
        ),
        "database_integrity": integrity,
        "rules": [
            "认定时名称、地区、年度、批次和状态来自名单侧，不被当前工商信息覆盖。",
            "当前名称、信用代码、当前地区和地址来自天眼查等企业身份源。",
            "省级名单未提供城市时保留城市待核验，不通过企业名称猜测城市。",
            "统一社会信用代码缺失时使用规范名称临时键，禁止自动推算信用代码。",
            "同名、迁址、合并和重组冲突必须进入人工核验。",
        ],
    }
    (output / "浙江省企业身份时间轴构建报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    args = parse_args()
    ensure_tyc_template(args.tyc_enrichment)
    events: dict[tuple[str, str, int | None, str, str], dict[str, Any]] = {}
    load_small_giant_events(args.small_giant_master, events)
    load_list_events(args.database, events)
    load_three_first_events(args.three_first, events)
    report = write_outputs(
        args.database,
        args.output,
        events,
        load_tyc_enrichment(args.tyc_enrichment),
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_HISTORY = Path.home() / "Downloads" / "qice_three_first_history_full.json"
DEFAULT_OUTPUT = Path("/Volumes/知识库/_云端知识库/50_名单与对标/三首项目/_结构化数据")
DEFAULT_DB = Path("/Volumes/知识库/_云端迁移索引/cloud_package_index/knowledge_content.sqlite3")
DEFAULT_SUPPLEMENTS = DEFAULT_OUTPUT / "三首项目官方公开补充.jsonl"
DEFAULT_DIRECTORY_STATUS = DEFAULT_OUTPUT / "三首项目目录状态.jsonl"
PROJECT_NAMES = {
    "10": "浙江省首版次软件产品",
    "11": "浙江省首批次新材料",
    "12": "浙江省制造业首台（套）装备",
}
MISSING_PRODUCT_STATUS = "missing_user_lookup_required"
MISSING_PRODUCT_MESSAGE = "仅检索到企业名称，未取得可核验的具体产品名称，请用户自行查找并补充对应产品名称。"
TIMELINE_STAGE_ORDER = {
    "publicity": 10,
    "recognition": 20,
    "reward": 30,
    "directory_exit": 40,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立三首项目企业—产品—档次—年度跨年对标图谱")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--details", type=Path)
    parser.add_argument("--supplements", type=Path, default=DEFAULT_SUPPLEMENTS)
    parser.add_argument("--directory-status", type=Path, default=DEFAULT_DIRECTORY_STATUS)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def normalize_enterprise(value: str) -> str:
    value = re.sub(r"[\s·•]+", "", value or "")
    return re.sub(r"[（(](?:原名|曾用名).*?[）)]", "", value)


def normalize_product(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" |,，;；")


def subject_fields(value: str) -> dict[str, str]:
    result = {"product_name": "", "recognition_tier": "", "product_category": ""}
    for part in (normalize_product(item) for item in str(value or "").split("::")):
        if not part:
            continue
        match = re.match(r"([^：:]+)[：:](.+)", part)
        if not match:
            if any(term in part for term in ("首台", "首版次", "首批次")):
                result["recognition_tier"] = part
            continue
        key, item = normalize_product(match.group(1)), normalize_product(match.group(2))
        if any(term in key for term in ("产品名称", "材料名称", "装备名称", "软件名称")):
            result["product_name"] = item
        elif any(term in key for term in ("拟认定档次", "认定档次", "档次")):
            result["recognition_tier"] = item
        elif any(term in key for term in ("产品类别", "装备类别", "材料类别", "软件类别", "类别")):
            result["product_category"] = item
    return result


def parse_years(value: Any) -> list[int]:
    return sorted({int(year) for year in re.findall(r"20\d{2}", str(value or ""))})


def first_value(record: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            if isinstance(value, list):
                return "、".join(str(item) for item in value if item not in (None, ""))
            return str(value)
    return ""


def history_projects(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("projects"), list):
        return payload["projects"]
    if isinstance(payload, list):
        return payload
    raise ValueError("企策历史获批文件缺少 projects 数组")


def expand_history(payload: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    identities: dict[str, dict[str, Any]] = {}
    for project in history_projects(payload):
        project_id = str(project.get("projectId") or "")
        project_name = str(project.get("projectName") or PROJECT_NAMES.get(project_id, ""))
        for item in project.get("records", []):
            eid = str(item.get("eid") or "")
            enterprise_name = str(item.get("entName") or "").strip()
            aliases = [
                str(alias.get("entHisName") or "").strip()
                for alias in (item.get("entHisList") or [])
                if alias.get("entHisName")
            ]
            identity_key = eid or normalize_enterprise(enterprise_name)
            identities[identity_key] = {
                "enterprise_key": identity_key,
                "eid": eid,
                "enterprise_name": enterprise_name,
                "aliases": aliases,
                "province": str(item.get("province") or ""),
                "city": str(item.get("city") or ""),
                "county": str(item.get("county") or ""),
                "industry": str(item.get("industryName") or ""),
                "registration_date": str(item.get("registrationDate") or ""),
            }
            for year in parse_years(item.get("subsidyYear")):
                records.append({
                    "enterprise_key": identity_key,
                    "eid": eid,
                    "enterprise_name": enterprise_name,
                    "enterprise_aliases": aliases,
                    "province": str(item.get("province") or ""),
                    "city": str(item.get("city") or ""),
                    "county": str(item.get("county") or ""),
                    "industry": str(item.get("industryName") or ""),
                    "project_id": project_id,
                    "project_name": project_name,
                    "year": year,
                    "product_name": "",
                    "recognition_tier": "",
                    "product_category": "",
                    "list_status": "platform_history",
                    "source_policy_id": "",
                    "source_index_id": "",
                    "source_title": "",
                    "source_url": "",
                    "source_tier": "licensed_platform",
                    "evidence_semantics": "platform_history_claim",
                    "confidence": "discovery_only",
                })
    return records, identities


def detail_projects(payload: Any) -> list[dict[str, Any]]:
    if not payload:
        return []
    if isinstance(payload, dict) and isinstance(payload.get("projects"), list):
        return payload["projects"]
    if isinstance(payload, list):
        return payload
    return []


def flattened_detail_rows(policy: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    rows = policy.get("records") or policy.get("data", {}).get("records") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ent_list = row.get("entList")
        if isinstance(ent_list, list) and ent_list:
            for enterprise in ent_list:
                if isinstance(enterprise, dict):
                    yield row, enterprise
        else:
            yield row, row


def normalize_details(payload: Any, identities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    alias_to_key: dict[str, str] = {}
    for key, identity in identities.items():
        alias_to_key[normalize_enterprise(identity["enterprise_name"])] = key
        for alias in identity["aliases"]:
            alias_to_key[normalize_enterprise(alias)] = key
    output: list[dict[str, Any]] = []
    for project in detail_projects(payload):
        project_id = str(project.get("projectId") or "")
        project_name = str(project.get("projectName") or PROJECT_NAMES.get(project_id, ""))
        for policy in project.get("policies", []):
            policy_meta = policy.get("policy") if isinstance(policy.get("policy"), dict) else policy
            policy_id = str(policy_meta.get("id") or policy_meta.get("policyId") or "")
            index_id = str(policy_meta.get("indexId") or "")
            title = str(policy_meta.get("title") or "")
            url = str(policy_meta.get("originalLink") or policy_meta.get("url") or "")
            policy_years = parse_years(first_value(policy_meta, ("assessYear", "year", "publishTime", "title")))
            for row, enterprise in flattened_detail_rows(policy):
                enterprise_name = first_value(enterprise, ("entName", "enterpriseName", "companyName", "name"))
                if not enterprise_name:
                    enterprise_name = first_value(row, ("entName", "enterpriseName", "companyName"))
                eid = first_value(enterprise, ("eid", "entInfoId", "enterpriseId")) or first_value(row, ("eid", "entInfoId"))
                identity_key = eid or alias_to_key.get(normalize_enterprise(enterprise_name), normalize_enterprise(enterprise_name))
                years = parse_years(first_value(enterprise, ("assessYear", "subsidyYear", "year"))) or parse_years(first_value(row, ("assessYear", "subsidyYear", "year"))) or policy_years
                product_name = normalize_product(first_value(enterprise, ("production", "productName", "softwareName", "materialName", "equipmentName", "projectName")))
                if not product_name:
                    product_name = normalize_product(first_value(row, ("production", "productName", "softwareName", "materialName", "equipmentName", "projectName")))
                tier = normalize_product(first_value(enterprise, ("recognitionTier", "assessLevel", "grade", "levelName", "accreditOrg")))
                if not tier:
                    tier = normalize_product(first_value(row, ("recognitionTier", "assessLevel", "grade", "levelName", "accreditOrg")))
                category = normalize_product(first_value(enterprise, ("productCategory", "equipmentCategory", "materialCategory", "softwareCategory", "category")))
                if not category:
                    category = normalize_product(first_value(row, ("productCategory", "equipmentCategory", "materialCategory", "softwareCategory", "category")))
                parsed_subject = subject_fields(first_value(enterprise, ("subject",)) or first_value(row, ("subject",)))
                product_name = product_name or parsed_subject["product_name"]
                tier = tier or parsed_subject["recognition_tier"]
                category = category or parsed_subject["product_category"]
                for year in years or [None]:
                    output.append({
                        "enterprise_key": identity_key,
                        "eid": eid,
                        "enterprise_name": enterprise_name,
                        "enterprise_aliases": identities.get(identity_key, {}).get("aliases", []),
                        "province": first_value(enterprise, ("province",)) or identities.get(identity_key, {}).get("province", ""),
                        "city": first_value(enterprise, ("city",)) or identities.get(identity_key, {}).get("city", ""),
                        "county": first_value(enterprise, ("county", "area")) or identities.get(identity_key, {}).get("county", ""),
                        "industry": first_value(enterprise, ("industryName", "industry")) or identities.get(identity_key, {}).get("industry", ""),
                        "project_id": project_id,
                        "project_name": project_name,
                        "year": year,
                        "product_name": product_name,
                        "recognition_tier": tier,
                        "product_category": category,
                        "list_status": first_value(policy_meta, ("listStatus", "evidenceType")) or "public_list",
                        "source_policy_id": policy_id,
                        "source_index_id": index_id,
                        "source_title": title,
                        "source_url": url,
                        "source_tier": "licensed_platform",
                        "evidence_semantics": "annual_list_row",
                        "confidence": "product_level" if product_name and enterprise_name else "partial_product_level",
                    })
    return output


def detail_is_final(record: dict[str, Any]) -> bool:
    title = str(record.get("source_title") or "")
    return any(term in title for term in ("关于公布", "名单的通知", "正式公布"))


def canonicalize_details(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int | None], list[dict[str, Any]]] = defaultdict(list)
    for record in details:
        grouped[(str(record.get("project_id")), record.get("year"))].append(record)
    canonical: list[dict[str, Any]] = []
    for records in grouped.values():
        final_records = [record for record in records if detail_is_final(record)]
        candidates = final_records or [
            record
            for record in records
            if not any(term in str(record.get("source_title") or "") for term in ("会员新闻", "喜讯"))
        ]
        if not candidates:
            candidates = records
        if not final_records:
            title_counts: dict[str, set[str]] = defaultdict(set)
            for record in candidates:
                title_counts[str(record.get("source_title") or "")].add(
                    str(record.get("enterprise_key") or "")
                )
            preferred_title = max(
                title_counts,
                key=lambda title: (len(title_counts[title]), len(title)),
            )
            candidates = [
                record
                for record in candidates
                if str(record.get("source_title") or "") == preferred_title
            ]
        keyed: dict[tuple[str, str], dict[str, Any]] = {}
        for record in candidates:
            key = (
                str(record.get("enterprise_key") or ""),
                normalize_product(record.get("product_name") or ""),
            )
            previous = keyed.get(key)
            if previous is None or (
                detail_is_final(record) and not detail_is_final(previous)
            ):
                keyed[key] = record
        canonical.extend(keyed.values())
    return canonical


def load_supplements(path: Path | None, identities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not path or not path.is_file():
        return []
    alias_to_key: dict[str, str] = {}
    for key, identity in identities.items():
        alias_to_key[normalize_enterprise(identity["enterprise_name"])] = key
        for alias in identity["aliases"]:
            alias_to_key[normalize_enterprise(alias)] = key
    output = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        source = json.loads(line)
        enterprise_name = str(source.get("enterprise_name") or "").strip()
        enterprise_key = alias_to_key.get(normalize_enterprise(enterprise_name), normalize_enterprise(enterprise_name))
        identity = identities.get(enterprise_key, {})
        output.append(
            {
                "enterprise_key": enterprise_key,
                "eid": identity.get("eid", ""),
                "enterprise_name": enterprise_name,
                "enterprise_aliases": identity.get("aliases", []),
                "province": source.get("province") or identity.get("province", ""),
                "city": source.get("city") or identity.get("city", ""),
                "county": source.get("county") or identity.get("county", ""),
                "industry": identity.get("industry", ""),
                "project_id": str(source.get("project_id") or ""),
                "project_name": str(source.get("project_name") or ""),
                "year": source.get("year"),
                "product_name": normalize_product(source.get("product_name")),
                "recognition_tier": normalize_product(source.get("recognition_tier")),
                "product_category": normalize_product(source.get("product_category")),
                "list_status": str(source.get("list_status") or ""),
                "event_date": str(source.get("event_date") or ""),
                "source_policy_id": "",
                "source_index_id": "",
                "source_title": str(source.get("source_title") or ""),
                "source_url": str(source.get("source_url") or ""),
                "source_tier": str(source.get("source_tier") or "public_source"),
                "evidence_semantics": str(source.get("evidence_semantics") or "annual_list_row"),
                "confidence": str(source.get("confidence") or "product_level"),
            }
        )
    return output


def source_priority(record: dict[str, Any]) -> int:
    tier = str(record.get("source_tier") or "")
    status = str(record.get("list_status") or "")
    confidence = str(record.get("confidence") or "")
    return (
        {"official": 500, "public_archive": 400, "licensed_platform": 300, "public_repost": 200}.get(tier, 100)
        + (80 if status.startswith("final_recognition") else 40 if status == "publicity" else 0)
        + (20 if confidence == "product_level" else 0)
    )


def merge_records(history: list[dict[str, Any]], details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    detailed_enterprise_years = {
        (
            str(record.get("enterprise_key")),
            str(record.get("project_id")),
            record.get("year"),
        )
        for record in details
    }
    keyed: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in [*history, *details]:
        enterprise_year = (
            str(record.get("enterprise_key")),
            str(record.get("project_id")),
            record.get("year"),
        )
        if record.get("confidence") == "discovery_only" and enterprise_year in detailed_enterprise_years:
            continue
        key = (
            record.get("enterprise_key"), record.get("project_id"), record.get("year"),
            normalize_product(record.get("product_name") or ""),
        )
        previous = keyed.get(key)
        if previous is None or source_priority(record) > source_priority(previous):
            keyed[key] = record
    records = list(keyed.values())
    for record in records:
        if normalize_product(record.get("product_name") or ""):
            record["product_name_status"] = "verified"
            record["user_action"] = ""
        else:
            record["product_name"] = ""
            record["product_name_status"] = MISSING_PRODUCT_STATUS
            record["user_action"] = MISSING_PRODUCT_MESSAGE
    return sorted(records, key=lambda item: (str(item.get("project_id")), int(item.get("year") or 0), str(item.get("enterprise_name")), str(item.get("product_name"))))


def timeline_event_types(record: dict[str, Any]) -> list[str]:
    status = str(record.get("list_status") or "").lower()
    title = str(record.get("source_title") or "")
    events: list[str] = []
    if status == "publicity" or any(term in title for term in ("公示", "拟认定")):
        events.append("publicity")
    if (
        status in {"final_recognition", "standard_guided_recognition"}
        or status.startswith("final_recognition")
        or detail_is_final(record)
    ):
        events.append("recognition")
    if "reward" in status or any(term in title for term in ("奖励", "奖补", "奖励名单")):
        events.append("reward")
    if any(term in status for term in ("directory_exit", "exit", "removed")) or any(
        term in title for term in ("退出目录", "移出目录", "目录退出", "撤销目录资格")
    ):
        events.append("directory_exit")
    return sorted(set(events), key=TIMELINE_STAGE_ORDER.get)


def build_status_timeline(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in evidence:
        product_name = normalize_product(record.get("product_name") or "")
        for event_type in timeline_event_types(record):
            key = (
                record.get("enterprise_key"),
                record.get("project_id"),
                record.get("year"),
                product_name,
                event_type,
                record.get("source_title"),
                record.get("source_url"),
            )
            timeline_id = hashlib.sha256(
                "|".join(str(item or "") for item in key).encode("utf-8")
            ).hexdigest()
            keyed[key] = {
                "timeline_id": timeline_id,
                "enterprise_key": str(record.get("enterprise_key") or ""),
                "enterprise_name": str(record.get("enterprise_name") or ""),
                "project_id": str(record.get("project_id") or ""),
                "project_name": str(record.get("project_name") or ""),
                "year": record.get("year"),
                "product_name": product_name,
                "product_name_status": "verified" if product_name else MISSING_PRODUCT_STATUS,
                "event_type": event_type,
                "event_stage_order": TIMELINE_STAGE_ORDER[event_type],
                "event_status": (
                    "scheduled"
                    if str(record.get("list_status") or "").startswith("scheduled_")
                    else "confirmed"
                ),
                "event_date": str(record.get("event_date") or ""),
                "source_title": str(record.get("source_title") or ""),
                "source_url": str(record.get("source_url") or ""),
                "source_tier": str(record.get("source_tier") or ""),
                "evidence_semantics": str(record.get("evidence_semantics") or ""),
                "confidence": str(record.get("confidence") or ""),
                "note": "" if product_name else MISSING_PRODUCT_MESSAGE,
            }
    return sorted(
        keyed.values(),
        key=lambda item: (
            item["enterprise_name"],
            item["project_name"],
            int(item["year"] or 0),
            item["product_name"],
            item["event_stage_order"],
        ),
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_graph(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for record in records:
        enterprise_id = f"enterprise:{record['enterprise_key']}"
        nodes[enterprise_id] = {"id": enterprise_id, "type": "enterprise", "label": record["enterprise_name"], "eid": record["eid"]}
        product_label = normalize_product(record.get("product_name") or "")
        product_digest_source = product_label or "|".join(
            (
                str(record.get("enterprise_key") or ""),
                str(record.get("project_id") or ""),
                str(record.get("year") or ""),
                str(record.get("source_title") or ""),
            )
        )
        product_digest = hashlib.sha256(product_digest_source.encode("utf-8")).hexdigest()[:16]
        award_id = f"award:{record['project_id']}:{record.get('year')}:{record['enterprise_key']}:{product_digest}"
        nodes[award_id] = {
            "id": award_id,
            "type": "recognition",
            "label": record["project_name"],
            "year": record.get("year"),
            "tier": record.get("recognition_tier"),
            "category": record.get("product_category"),
            "status": record.get("list_status"),
            "product_name_status": record.get("product_name_status"),
            "user_action": record.get("user_action"),
        }
        edges.append({"source": enterprise_id, "target": award_id, "relation": "received"})
        if product_label:
            product_id = "product:" + re.sub(r"\s+", "", product_label)
            nodes[product_id] = {"id": product_id, "type": "product", "label": product_label}
            edges.append({"source": award_id, "target": product_id, "relation": "recognized_product"})
    return list(nodes.values()), edges


def import_database(
    database: Path,
    records: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            DROP TABLE IF EXISTS three_first_project_awards;
            DROP TABLE IF EXISTS enterprise_product_graph_nodes;
            DROP TABLE IF EXISTS enterprise_product_graph_edges;
            DROP TABLE IF EXISTS three_first_award_evidence;
            DROP TABLE IF EXISTS three_first_status_timeline;
            CREATE TABLE three_first_project_awards(
                id INTEGER PRIMARY KEY,
                enterprise_key TEXT NOT NULL,
                eid TEXT NOT NULL,
                enterprise_name TEXT NOT NULL,
                enterprise_aliases TEXT NOT NULL,
                province TEXT NOT NULL,
                city TEXT NOT NULL,
                county TEXT NOT NULL,
                industry TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                year INTEGER,
                product_name TEXT NOT NULL,
                recognition_tier TEXT NOT NULL,
                product_category TEXT NOT NULL,
                list_status TEXT NOT NULL,
                source_policy_id TEXT NOT NULL,
                source_index_id TEXT NOT NULL,
                source_title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_tier TEXT NOT NULL,
                evidence_semantics TEXT NOT NULL,
                confidence TEXT NOT NULL,
                product_name_status TEXT NOT NULL,
                user_action TEXT NOT NULL
            );
            CREATE INDEX three_first_awards_lookup_idx ON three_first_project_awards(enterprise_name,project_name,year);
            CREATE INDEX three_first_awards_product_idx ON three_first_project_awards(product_name,recognition_tier,year);
            CREATE TABLE three_first_award_evidence(
                id INTEGER PRIMARY KEY,
                enterprise_key TEXT NOT NULL,
                enterprise_name TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                year INTEGER,
                product_name TEXT NOT NULL,
                recognition_tier TEXT NOT NULL,
                product_category TEXT NOT NULL,
                list_status TEXT NOT NULL,
                source_policy_id TEXT NOT NULL,
                source_title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_tier TEXT NOT NULL,
                evidence_semantics TEXT NOT NULL,
                confidence TEXT NOT NULL,
                product_name_status TEXT NOT NULL,
                user_action TEXT NOT NULL
            );
            CREATE INDEX three_first_evidence_lookup_idx
                ON three_first_award_evidence(project_name,year,enterprise_name);
            CREATE TABLE three_first_status_timeline(
                timeline_id TEXT PRIMARY KEY,
                enterprise_key TEXT NOT NULL,
                enterprise_name TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                year INTEGER,
                product_name TEXT NOT NULL,
                product_name_status TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_stage_order INTEGER NOT NULL,
                event_status TEXT NOT NULL,
                event_date TEXT NOT NULL,
                source_title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_tier TEXT NOT NULL,
                evidence_semantics TEXT NOT NULL,
                confidence TEXT NOT NULL,
                note TEXT NOT NULL
            );
            CREATE INDEX three_first_timeline_lookup_idx
                ON three_first_status_timeline(enterprise_name,project_name,year,event_stage_order);
            CREATE INDEX three_first_timeline_product_idx
                ON three_first_status_timeline(product_name,year,event_stage_order);
            CREATE TABLE enterprise_product_graph_nodes(id TEXT PRIMARY KEY,type TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE enterprise_product_graph_edges(id INTEGER PRIMARY KEY,source TEXT NOT NULL,target TEXT NOT NULL,relation TEXT NOT NULL);
            """
        )
        connection.executemany(
            """INSERT INTO three_first_project_awards(
                enterprise_key,eid,enterprise_name,enterprise_aliases,province,city,county,industry,
                project_id,project_name,year,product_name,recognition_tier,product_category,list_status,
                source_policy_id,source_index_id,source_title,source_url,confidence
                ,source_tier,evidence_semantics,product_name_status,user_action
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(
                row["enterprise_key"], row["eid"], row["enterprise_name"], json.dumps(row["enterprise_aliases"], ensure_ascii=False),
                row["province"], row["city"], row["county"], row["industry"], row["project_id"], row["project_name"], row["year"],
                row["product_name"], row["recognition_tier"], row["product_category"], row["list_status"], row["source_policy_id"],
                row["source_index_id"], row["source_title"], row["source_url"], row["confidence"],
                row["source_tier"], row["evidence_semantics"],
                row["product_name_status"], row["user_action"],
            ) for row in records],
        )
        connection.executemany(
            """INSERT INTO three_first_award_evidence(
                enterprise_key,enterprise_name,project_id,project_name,year,product_name,
                recognition_tier,product_category,list_status,source_policy_id,source_title,
                source_url,confidence,source_tier,evidence_semantics,product_name_status,user_action
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    row["enterprise_key"],
                    row["enterprise_name"],
                    row["project_id"],
                    row["project_name"],
                    row["year"],
                    row["product_name"],
                    row["recognition_tier"],
                    row["product_category"],
                    row["list_status"],
                    row["source_policy_id"],
                    row["source_title"],
                    row["source_url"],
                    row["confidence"],
                    row["source_tier"],
                    row["evidence_semantics"],
                    "verified" if normalize_product(row.get("product_name") or "") else MISSING_PRODUCT_STATUS,
                    "" if normalize_product(row.get("product_name") or "") else MISSING_PRODUCT_MESSAGE,
                )
                for row in evidence
            ],
        )
        connection.executemany(
            """INSERT INTO three_first_status_timeline(
                timeline_id,enterprise_key,enterprise_name,project_id,project_name,year,
                product_name,product_name_status,event_type,event_stage_order,event_status,event_date,
                source_title,source_url,source_tier,evidence_semantics,confidence,note
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    row["timeline_id"],
                    row["enterprise_key"],
                    row["enterprise_name"],
                    row["project_id"],
                    row["project_name"],
                    row["year"],
                    row["product_name"],
                    row["product_name_status"],
                    row["event_type"],
                    row["event_stage_order"],
                    row["event_status"],
                    row["event_date"],
                    row["source_title"],
                    row["source_url"],
                    row["source_tier"],
                    row["evidence_semantics"],
                    row["confidence"],
                    row["note"],
                )
                for row in timeline
            ],
        )
        connection.executemany(
            "INSERT INTO enterprise_product_graph_nodes(id,type,payload) VALUES(?,?,?)",
            [(node["id"], node["type"], json.dumps(node, ensure_ascii=False)) for node in nodes],
        )
        connection.executemany(
            "INSERT INTO enterprise_product_graph_edges(source,target,relation) VALUES(?,?,?)",
            [(edge["source"], edge["target"], edge["relation"]) for edge in edges],
        )
        connection.commit()
    finally:
        connection.close()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    history_payload = json.loads(args.history.read_text(encoding="utf-8"))
    history, identities = expand_history(history_payload)
    detail_payload = json.loads(args.details.read_text(encoding="utf-8")) if args.details and args.details.is_file() else None
    detail_evidence = normalize_details(detail_payload, identities)
    details = canonicalize_details(detail_evidence)
    supplements = load_supplements(args.supplements, identities)
    directory_status = load_supplements(args.directory_status, identities)
    supplemented_project_years = {
        (str(record.get("project_id")), record.get("year"))
        for record in supplements
        if record.get("evidence_semantics") == "annual_list_row"
    }
    details = [
        record
        for record in details
        if (str(record.get("project_id")), record.get("year")) not in supplemented_project_years
    ]
    records = merge_records(history, [*details, *supplements])
    nodes, edges = build_graph(records)
    all_evidence = [*detail_evidence, *supplements, *directory_status]
    timeline = build_status_timeline(all_evidence)
    write_jsonl(args.output / "三首项目企业产品年度记录.jsonl", records)
    write_jsonl(args.output / "三首项目状态时间轴.jsonl", timeline)
    write_jsonl(args.output / "三首项目图谱节点.jsonl", nodes)
    write_jsonl(args.output / "三首项目图谱关系.jsonl", edges)
    identity_rows = list(identities.values())
    write_jsonl(args.output / "三首项目企业身份别名.jsonl", identity_rows)
    product_records = sum(bool(row["product_name"]) for row in records)
    summary = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "records": len(records),
        "product_level_records": product_records,
        "discovery_only_records": len(records) - product_records,
        "detail_evidence_records": len(detail_evidence),
        "canonical_detail_records": len(details),
        "supplement_records": len(supplements),
        "directory_status_records": len(directory_status),
        "timeline_events": len(timeline),
        "timeline_publicity": sum(row["event_type"] == "publicity" for row in timeline),
        "timeline_recognition": sum(row["event_type"] == "recognition" for row in timeline),
        "timeline_reward": sum(row["event_type"] == "reward" for row in timeline),
        "timeline_directory_exit": sum(row["event_type"] == "directory_exit" for row in timeline),
        "enterprises": len(identities),
        "nodes": len(nodes),
        "edges": len(edges),
    }
    (args.output / "三首项目跨年对标图谱说明.md").write_text(
        "\n".join([
            "# 三首项目跨年对标图谱",
            "",
            f"更新时间：{datetime.now().astimezone().strftime('%Y年%m月%d日%H:%M:%S')}",
            "",
            "## 图谱关系",
            "",
            "企业通过 received 关系连接年度认定记录，年度认定记录再通过 recognized_product 连接产品。",
            "同一企业优先按企策 eid 关联；没有 eid 时才使用规范化企业名称。曾用名保留在身份别名表中。",
            "",
            "## 证据等级",
            "",
            "- product_level：已从历年公示详情提取企业、产品、档次或类别。",
            "- partial_product_level：公示详情字段不完整，需抽样复核。",
            "- discovery_only：仅历史获批页确认企业和年度，不能据此断言具体产品或认定档次。",
            f"- 缺少产品名称时固定标记 `{MISSING_PRODUCT_STATUS}`，并提示：{MISSING_PRODUCT_MESSAGE}",
            "- 状态时间轴仅依据原文分别记录公示、认定、奖励和目录退出；没有明确退出证据时不得推断已退出。",
            "",
            "## 汇总",
            "",
            *[f"- {key}: {value}" for key, value in summary.items()],
            "",
        ]),
        encoding="utf-8",
    )
    import_database(args.database, records, all_evidence, timeline, nodes, edges)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

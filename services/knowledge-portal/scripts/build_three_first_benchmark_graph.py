#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_HISTORY = Path.home() / "Downloads" / "qice_three_first_history_full.json"
DEFAULT_OUTPUT = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/三首项目/_结构化数据")
DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_SUPPLEMENTS = DEFAULT_OUTPUT / "三首项目官方公开补充.jsonl"
DEFAULT_DIRECTORY_STATUS = DEFAULT_OUTPUT / "三首项目目录状态.jsonl"
DEFAULT_GUIDANCE_DIRECTORIES = Path(
    "/Users/zsh/JiaotangData/知识库/10_政策与目录/三首项目/浙江省首批次新材料/应用示范指导目录/"
    "浙江省重点新材料首批次应用示范指导目录_结构化条目.jsonl"
)
PROJECT_NAMES = {
    "10": "浙江省首版次软件产品",
    "11": "浙江省首批次新材料",
    "12": "浙江省制造业首台（套）装备",
}
MISSING_PRODUCT_STATUS = "missing_user_lookup_required"
MISSING_PRODUCT_MESSAGE = "仅检索到企业名称，未取得可核验的具体产品名称，请用户自行查找并补充对应产品名称。"
SCOPE_UNRESOLVED_STATUS = "platform_history_scope_unresolved"
SCOPE_UNRESOLVED_MESSAGE = "平台历史关联未能与同年度正式名单逐项对应；不得把其他年度产品静默回填为本年度认定产品。"
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
    parser.add_argument("--guidance-directories", type=Path, default=DEFAULT_GUIDANCE_DIRECTORIES)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def normalize_enterprise(value: str) -> str:
    value = re.sub(r"[\s·•]+", "", value or "")
    return re.sub(r"[（(](?:原名|曾用名).*?[）)]", "", value)


def normalize_product(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" |,，;；")


def normalize_material_key(value: str) -> str:
    return re.sub(r"\s+", "", normalize_product(value)).replace("（", "(").replace("）", ")")


def normalize_clause(value: str) -> str:
    return re.sub(
        r"[\s，。；：、,.;:（）()【】\[\]]+",
        "",
        str(value or ""),
    ).lower()


def material_similarity(left: str, right: str) -> tuple[float, str]:
    left_key = normalize_material_key(left).lower()
    right_key = normalize_material_key(right).lower()
    if not left_key or not right_key:
        return 0.0, "none"
    if left_key == right_key:
        return 1.0, "exact_material_name"
    shorter, longer = sorted((left_key, right_key), key=len)
    if len(shorter) >= 4 and shorter in longer and len(shorter) / len(longer) >= 0.6:
        return 0.94, "material_name_contains"
    score = difflib.SequenceMatcher(None, left_key, right_key).ratio()
    return score, "fuzzy_material_name"


def directory_version_diffs(
    guidance_directories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in guidance_directories:
        by_year[int(row["directory_year"])].append(row)
    differences: list[dict[str, Any]] = []
    fields = (
        "material_name",
        "top_category",
        "major_category",
        "sub_category",
        "performance_requirements",
        "application_field",
    )
    for from_year, to_year in zip(sorted(by_year), sorted(by_year)[1:]):
        previous = by_year[from_year]
        current = by_year[to_year]
        current_by_key = {
            normalize_material_key(row["material_name"]): row for row in current
        }
        matched_current: set[int] = set()
        pairs: list[tuple[dict[str, Any], dict[str, Any], float, str]] = []
        unmatched_previous: list[dict[str, Any]] = []
        for old in previous:
            exact = current_by_key.get(normalize_material_key(old["material_name"]))
            if exact:
                matched_current.add(int(exact["sequence_no"]))
                pairs.append((old, exact, 1.0, "exact_material_name"))
            else:
                unmatched_previous.append(old)
        unmatched_current = [
            row for row in current if int(row["sequence_no"]) not in matched_current
        ]
        fuzzy_candidates = sorted(
            (
                (material_similarity(old["material_name"], new["material_name"])[0], old, new)
                for old in unmatched_previous
                for new in unmatched_current
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        matched_previous_sequences: set[int] = set()
        for score, old, new in fuzzy_candidates:
            if score < 0.88:
                break
            old_sequence = int(old["sequence_no"])
            new_sequence = int(new["sequence_no"])
            if old_sequence in matched_previous_sequences or new_sequence in matched_current:
                continue
            _, match_type = material_similarity(old["material_name"], new["material_name"])
            matched_previous_sequences.add(old_sequence)
            matched_current.add(new_sequence)
            pairs.append((old, new, score, match_type))
        for old, new, score, match_type in pairs:
            changed_fields = [
                field
                for field in fields
                if normalize_clause(old.get(field, "")) != normalize_clause(new.get(field, ""))
            ]
            differences.append(
                {
                    "from_year": from_year,
                    "to_year": to_year,
                    "change_type": "modified" if changed_fields else "retained",
                    "from_sequence_no": old["sequence_no"],
                    "to_sequence_no": new["sequence_no"],
                    "from_material_name": old["material_name"],
                    "to_material_name": new["material_name"],
                    "match_type": match_type,
                    "match_score": round(score, 4),
                    "changed_fields": changed_fields,
                    "before_values": {field: old.get(field, "") for field in changed_fields},
                    "after_values": {field: new.get(field, "") for field in changed_fields},
                }
            )
        for old in unmatched_previous:
            if int(old["sequence_no"]) in matched_previous_sequences:
                continue
            differences.append(
                {
                    "from_year": from_year,
                    "to_year": to_year,
                    "change_type": "removed",
                    "from_sequence_no": old["sequence_no"],
                    "to_sequence_no": None,
                    "from_material_name": old["material_name"],
                    "to_material_name": "",
                    "match_type": "unmatched",
                    "match_score": 0.0,
                    "changed_fields": [],
                    "before_values": {},
                    "after_values": {},
                }
            )
        for new in current:
            if int(new["sequence_no"]) in matched_current:
                continue
            differences.append(
                {
                    "from_year": from_year,
                    "to_year": to_year,
                    "change_type": "added",
                    "from_sequence_no": None,
                    "to_sequence_no": new["sequence_no"],
                    "from_material_name": "",
                    "to_material_name": new["material_name"],
                    "match_type": "unmatched",
                    "match_score": 0.0,
                    "changed_fields": [],
                    "before_values": {},
                    "after_values": {},
                }
            )
    return sorted(
        differences,
        key=lambda row: (
            row["from_year"],
            row["to_year"],
            str(row["change_type"]),
            int(row["from_sequence_no"] or 0),
            int(row["to_sequence_no"] or 0),
        ),
    )


def enterprise_product_directory_matches(
    records: list[dict[str, Any]],
    guidance_directories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for directory in guidance_directories:
        by_year[int(directory["directory_year"])].append(directory)
    matches: list[dict[str, Any]] = []
    for award in records:
        if str(award.get("project_id")) != "11":
            continue
        product_name = normalize_product(award.get("product_name") or "")
        if not product_name:
            continue
        for directory_year, candidates in by_year.items():
            ranked = []
            for directory in candidates:
                score, match_type = material_similarity(
                    product_name, directory["material_name"]
                )
                if score >= 0.88:
                    ranked.append((score, match_type, directory))
            if not ranked:
                continue
            best_score = max(item[0] for item in ranked)
            for score, match_type, directory in ranked:
                if score < best_score:
                    continue
                matches.append(
                    {
                        "enterprise_name": award["enterprise_name"],
                        "award_year": award.get("year"),
                        "product_name": product_name,
                        "directory_year": directory_year,
                        "directory_sequence_no": directory["sequence_no"],
                        "directory_material_name": directory["material_name"],
                        "match_type": match_type,
                        "match_score": round(score, 4),
                        "match_confidence": "high" if score >= 0.94 else "medium",
                        "review_status": (
                            "auto_confirmed"
                            if score >= 0.94
                            else "candidate_requires_review"
                        ),
                    }
                )
    unique = {
        (
            row["enterprise_name"],
            row["award_year"],
            row["product_name"],
            row["directory_year"],
            row["directory_sequence_no"],
        ): row
        for row in matches
    }
    return sorted(
        unique.values(),
        key=lambda row: (
            row["enterprise_name"],
            int(row["award_year"] or 0),
            row["product_name"],
            row["directory_year"],
        ),
    )


SUBJECT_CATEGORY_TERMS = {
    "成套装备",
    "整机装备",
    "零部件",
    "关键零部件",
    "基础软件",
    "工业软件",
    "嵌入式软件",
    "新兴技术软件",
}


def subject_fields(value: str) -> dict[str, str]:
    result = {"product_name": "", "recognition_tier": "", "product_category": ""}
    unkeyed: list[str] = []
    for part in (normalize_product(item) for item in str(value or "").split("::")):
        if not part:
            continue
        match = re.match(r"([^：:]+)[：:](.+)", part)
        key = normalize_product(match.group(1)) if match else ""
        recognized_key = any(
            term in key
            for term in (
                "产品名称",
                "材料名称",
                "装备名称",
                "软件名称",
                "拟认定档次",
                "认定档次",
                "档次",
                "产品类别",
                "装备类别",
                "材料类别",
                "软件类别",
                "类别",
                "备注",
            )
        )
        if not match or not recognized_key:
            if any(term in part for term in ("首台", "首版次", "首批次")):
                result["recognition_tier"] = part
            else:
                unkeyed.append(part)
            continue
        item = normalize_product(match.group(2))
        if any(term in key for term in ("产品名称", "材料名称", "装备名称", "软件名称")):
            result["product_name"] = item
        elif any(term in key for term in ("拟认定档次", "认定档次", "档次")):
            result["recognition_tier"] = item
        elif any(term in key for term in ("产品类别", "装备类别", "材料类别", "软件类别", "类别")):
            result["product_category"] = item
        elif key == "备注" and item in SUBJECT_CATEGORY_TERMS:
            result["product_category"] = item
    remaining: list[str] = []
    for part in unkeyed:
        if part in SUBJECT_CATEGORY_TERMS and not result["product_category"]:
            result["product_category"] = part
        else:
            remaining.append(part)
    if not result["product_name"] and remaining:
        result["product_name"] = remaining[-1]
    return result


def infer_list_status(title: str) -> str:
    if any(term in title for term in ("关于公布", "名单的通知", "正式公布")):
        return "final_recognition"
    if any(term in title for term in ("公示", "拟认定", "入围名单")):
        return "publicity"
    return "public_list"


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
                product_name = normalize_product(first_value(enterprise, ("production", "productName", "softwareName", "materialName", "equipmentName")))
                if not product_name:
                    product_name = normalize_product(first_value(row, ("production", "productName", "softwareName", "materialName", "equipmentName")))
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
                        "list_status": first_value(policy_meta, ("listStatus", "evidenceType")) or infer_list_status(title),
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


def load_guidance_directories(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def source_priority(record: dict[str, Any]) -> int:
    tier = str(record.get("source_tier") or "")
    status = str(record.get("list_status") or "")
    confidence = str(record.get("confidence") or "")
    return (
        {
            "official": 500,
            "user_provided_official_screenshot": 450,
            "public_archive": 400,
            "licensed_platform": 300,
            "public_repost": 200,
        }.get(tier, 100)
        + (80 if status.startswith("final_recognition") else 40 if status.startswith("publicity") else 0)
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
        if normalize_product(record.get("product_name") or "")
    }
    keyed: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in [*history, *details]:
        enterprise_year = (
            str(record.get("enterprise_key")),
            str(record.get("project_id")),
            record.get("year"),
        )
        if (
            not normalize_product(record.get("product_name") or "")
            and enterprise_year in detailed_enterprise_years
        ):
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
        elif (
            record.get("confidence") == "discovery_only"
            or record.get("evidence_semantics") == "platform_history_claim"
        ):
            record["product_name"] = ""
            record["product_name_status"] = SCOPE_UNRESOLVED_STATUS
            record["user_action"] = SCOPE_UNRESOLVED_MESSAGE
        else:
            record["product_name"] = ""
            record["product_name_status"] = MISSING_PRODUCT_STATUS
            record["user_action"] = MISSING_PRODUCT_MESSAGE
    return sorted(records, key=lambda item: (str(item.get("project_id")), int(item.get("year") or 0), str(item.get("enterprise_name")), str(item.get("product_name"))))


def attach_identity_topic_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    products_by_identity_project: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in records:
        product_name = normalize_product(record.get("product_name") or "")
        if not product_name:
            continue
        key = (str(record.get("enterprise_key") or ""), str(record.get("project_id") or ""))
        candidate = {
            "product_name": product_name,
            "recognition_year": record.get("year"),
            "source_title": str(record.get("source_title") or ""),
            "source_url": str(record.get("source_url") or ""),
            "source_tier": str(record.get("source_tier") or ""),
            "list_status": str(record.get("list_status") or ""),
            "confidence": str(record.get("confidence") or ""),
            "evidence_semantics": str(record.get("evidence_semantics") or ""),
        }
        previous = products_by_identity_project[key].get(product_name)
        if previous is None or source_priority(record) > source_priority(previous):
            products_by_identity_project[key][product_name] = candidate
    output: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        product_name = normalize_product(item.get("product_name") or "")
        if product_name:
            item["identity_topic_product_candidates"] = []
            item["topic_direction_status"] = "verified_annual_product"
        else:
            key = (str(item.get("enterprise_key") or ""), str(item.get("project_id") or ""))
            candidates = sorted(
                products_by_identity_project.get(key, {}).values(),
                key=lambda candidate: (
                    int(candidate.get("recognition_year") or 0),
                    str(candidate.get("product_name") or ""),
                ),
            )
            item["identity_topic_product_candidates"] = candidates[:20]
            item["topic_direction_status"] = (
                "candidate_from_same_enterprise_history"
                if candidates
                else "pending_external_product_lookup"
            )
        output.append(item)
    return output


def build_identity_profiles(
    records: list[dict[str, Any]], identities: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_identity[str(record.get("enterprise_key") or "")].append(record)
    profiles: list[dict[str, Any]] = []
    for enterprise_key, rows in by_identity.items():
        identity = identities.get(enterprise_key, {})
        signals: dict[tuple[str, int | None, str], dict[str, Any]] = {}
        projects: set[str] = set()
        years: set[int] = set()
        for row in rows:
            project_id = str(row.get("project_id") or "")
            projects.add(project_id)
            if row.get("year"):
                years.add(int(row["year"]))
            product_name = normalize_product(row.get("product_name") or "")
            if not product_name:
                continue
            signal_key = (project_id, row.get("year"), product_name)
            signals[signal_key] = {
                "project_id": project_id,
                "project_name": str(row.get("project_name") or ""),
                "recognition_year": row.get("year"),
                "product_name": product_name,
                "recognition_tier": str(row.get("recognition_tier") or ""),
                "product_category": str(row.get("product_category") or ""),
                "source_title": str(row.get("source_title") or ""),
                "source_url": str(row.get("source_url") or ""),
                "source_tier": str(row.get("source_tier") or ""),
                "evidence_semantics": str(row.get("evidence_semantics") or ""),
            }
        product_signals = sorted(
            signals.values(),
            key=lambda signal: (
                str(signal["project_id"]),
                int(signal.get("recognition_year") or 0),
                str(signal["product_name"]),
            ),
        )
        profiles.append(
            {
                "enterprise_key": enterprise_key,
                "eid": str(identity.get("eid") or next((row.get("eid") for row in rows if row.get("eid")), "")),
                "enterprise_name": str(identity.get("enterprise_name") or rows[0].get("enterprise_name") or ""),
                "aliases": list(identity.get("aliases") or []),
                "province": str(identity.get("province") or rows[0].get("province") or ""),
                "city": str(identity.get("city") or rows[0].get("city") or ""),
                "county": str(identity.get("county") or rows[0].get("county") or ""),
                "industry": str(identity.get("industry") or rows[0].get("industry") or ""),
                "three_first_projects": sorted(projects),
                "three_first_years": sorted(years),
                "product_signal_count": len(product_signals),
                "product_signal_status": (
                    "verified_product_signal"
                    if product_signals
                    else "identity_only_scope_unresolved"
                ),
                "product_signals": product_signals,
            }
        )
    return sorted(profiles, key=lambda profile: (profile["enterprise_name"], profile["enterprise_key"]))


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
    identity_profiles: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    guidance_directories: list[dict[str, Any]],
    directory_diffs: list[dict[str, Any]],
    directory_matches: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            DROP TABLE IF EXISTS three_first_project_awards;
            DROP TABLE IF EXISTS three_first_identity_profiles;
            DROP TABLE IF EXISTS enterprise_product_graph_nodes;
            DROP TABLE IF EXISTS enterprise_product_graph_edges;
            DROP TABLE IF EXISTS three_first_award_evidence;
            DROP TABLE IF EXISTS three_first_status_timeline;
            DROP TABLE IF EXISTS three_first_guidance_directory_entries;
            DROP TABLE IF EXISTS three_first_guidance_directory_diffs;
            DROP TABLE IF EXISTS three_first_award_directory_links;
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
            CREATE TABLE three_first_identity_profiles(
                enterprise_key TEXT PRIMARY KEY,
                eid TEXT NOT NULL,
                enterprise_name TEXT NOT NULL,
                aliases_json TEXT NOT NULL,
                province TEXT NOT NULL,
                city TEXT NOT NULL,
                county TEXT NOT NULL,
                industry TEXT NOT NULL,
                three_first_projects_json TEXT NOT NULL,
                three_first_years_json TEXT NOT NULL,
                product_signal_count INTEGER NOT NULL,
                product_signal_status TEXT NOT NULL,
                product_signals_json TEXT NOT NULL
            );
            CREATE INDEX three_first_identity_profiles_lookup_idx
                ON three_first_identity_profiles(enterprise_name,product_signal_status);
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
            CREATE TABLE three_first_guidance_directory_entries(
                id INTEGER PRIMARY KEY,
                project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                directory_year INTEGER NOT NULL,
                sequence_no INTEGER NOT NULL,
                material_name TEXT NOT NULL,
                top_category TEXT NOT NULL,
                major_category TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                performance_requirements TEXT NOT NULL,
                application_field TEXT NOT NULL,
                document_title TEXT NOT NULL,
                document_number TEXT NOT NULL,
                effective_date TEXT NOT NULL,
                validity_status TEXT NOT NULL,
                replacement_year INTEGER,
                source_url TEXT NOT NULL,
                source_tier TEXT NOT NULL,
                UNIQUE(directory_year,sequence_no)
            );
            CREATE INDEX three_first_guidance_material_idx
                ON three_first_guidance_directory_entries(material_name,directory_year);
            CREATE INDEX three_first_guidance_status_idx
                ON three_first_guidance_directory_entries(validity_status,directory_year);
            CREATE TABLE three_first_guidance_directory_diffs(
                id INTEGER PRIMARY KEY,
                from_year INTEGER NOT NULL,
                to_year INTEGER NOT NULL,
                change_type TEXT NOT NULL,
                from_sequence_no INTEGER,
                to_sequence_no INTEGER,
                from_material_name TEXT NOT NULL,
                to_material_name TEXT NOT NULL,
                match_type TEXT NOT NULL,
                match_score REAL NOT NULL,
                changed_fields TEXT NOT NULL,
                before_values TEXT NOT NULL,
                after_values TEXT NOT NULL,
                UNIQUE(from_year,to_year,change_type,from_sequence_no,to_sequence_no)
            );
            CREATE INDEX three_first_guidance_diff_lookup_idx
                ON three_first_guidance_directory_diffs(from_year,to_year,change_type);
            CREATE TABLE three_first_award_directory_links(
                id INTEGER PRIMARY KEY,
                enterprise_name TEXT NOT NULL,
                award_year INTEGER,
                product_name TEXT NOT NULL,
                directory_year INTEGER NOT NULL,
                directory_sequence_no INTEGER NOT NULL,
                directory_material_name TEXT NOT NULL,
                match_type TEXT NOT NULL,
                match_score REAL NOT NULL,
                match_confidence TEXT NOT NULL,
                review_status TEXT NOT NULL,
                UNIQUE(enterprise_name,award_year,product_name,directory_year,directory_sequence_no)
            );
            CREATE INDEX three_first_award_directory_lookup_idx
                ON three_first_award_directory_links(enterprise_name,award_year,product_name);
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
            """INSERT INTO three_first_identity_profiles(
                enterprise_key,eid,enterprise_name,aliases_json,province,city,county,industry,
                three_first_projects_json,three_first_years_json,product_signal_count,
                product_signal_status,product_signals_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    row["enterprise_key"], row["eid"], row["enterprise_name"],
                    json.dumps(row["aliases"], ensure_ascii=False), row["province"], row["city"],
                    row["county"], row["industry"],
                    json.dumps(row["three_first_projects"], ensure_ascii=False),
                    json.dumps(row["three_first_years"], ensure_ascii=False),
                    row["product_signal_count"], row["product_signal_status"],
                    json.dumps(row["product_signals"], ensure_ascii=False),
                )
                for row in identity_profiles
            ],
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
            """INSERT INTO three_first_guidance_directory_entries(
                project_id,project_name,directory_year,sequence_no,material_name,
                top_category,major_category,sub_category,performance_requirements,application_field,
                document_title,document_number,effective_date,validity_status,replacement_year,
                source_url,source_tier
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    row["project_id"], row["project_name"], row["directory_year"], row["sequence_no"],
                    row["material_name"], row["top_category"], row["major_category"], row["sub_category"],
                    row["performance_requirements"], row["application_field"], row["document_title"],
                    row["document_number"], row["effective_date"], row["validity_status"],
                    row.get("replacement_year"), row["source_url"], row["source_tier"],
                )
                for row in guidance_directories
            ],
        )
        connection.executemany(
            """INSERT INTO three_first_guidance_directory_diffs(
                from_year,to_year,change_type,from_sequence_no,to_sequence_no,
                from_material_name,to_material_name,match_type,match_score,
                changed_fields,before_values,after_values
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    row["from_year"],
                    row["to_year"],
                    row["change_type"],
                    row["from_sequence_no"],
                    row["to_sequence_no"],
                    row["from_material_name"],
                    row["to_material_name"],
                    row["match_type"],
                    row["match_score"],
                    json.dumps(row["changed_fields"], ensure_ascii=False),
                    json.dumps(row["before_values"], ensure_ascii=False),
                    json.dumps(row["after_values"], ensure_ascii=False),
                )
                for row in directory_diffs
            ],
        )
        connection.executemany(
            """INSERT OR IGNORE INTO three_first_award_directory_links(
                enterprise_name,award_year,product_name,directory_year,directory_sequence_no,
                directory_material_name,match_type,match_score,match_confidence,review_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    row["enterprise_name"],
                    row["award_year"],
                    row["product_name"],
                    row["directory_year"],
                    row["directory_sequence_no"],
                    row["directory_material_name"],
                    row["match_type"],
                    row["match_score"],
                    row["match_confidence"],
                    row["review_status"],
                )
                for row in directory_matches
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
    guidance_directories = load_guidance_directories(args.guidance_directories)
    # Official supplements supersede only an exact enterprise/project/year/product
    # duplicate. They must not erase every licensed detail row in the same
    # project-year, otherwise valid product signals disappear from the identity.
    records = attach_identity_topic_candidates(
        merge_records(history, [*details, *supplements])
    )
    identity_profiles = build_identity_profiles(records, identities)
    guidance_diffs = directory_version_diffs(guidance_directories)
    directory_matches = enterprise_product_directory_matches(
        records, guidance_directories
    )
    nodes, edges = build_graph(records)
    all_evidence = [*detail_evidence, *supplements, *directory_status]
    timeline = build_status_timeline(all_evidence)
    write_jsonl(args.output / "三首项目企业产品年度记录.jsonl", records)
    write_jsonl(args.output / "三首企业数字身份证.jsonl", identity_profiles)
    write_jsonl(args.output / "三首项目状态时间轴.jsonl", timeline)
    write_jsonl(args.output / "三首项目图谱节点.jsonl", nodes)
    write_jsonl(args.output / "三首项目图谱关系.jsonl", edges)
    write_jsonl(args.output / "三首目录历年条款差异.jsonl", guidance_diffs)
    write_jsonl(args.output / "三首企业产品目录自动匹配.jsonl", directory_matches)
    identity_rows = list(identities.values())
    write_jsonl(args.output / "三首项目企业身份别名.jsonl", identity_rows)
    product_records = sum(bool(row["product_name"]) for row in records)
    product_signal_keys = {
        (str(row.get("enterprise_key") or ""), str(row.get("project_id") or ""))
        for row in records
        if normalize_product(row.get("product_name") or "")
    }
    history_2025 = [row for row in history if row.get("year") == 2025]
    history_2025_topic_closed = sum(
        (
            str(row.get("enterprise_key") or ""),
            str(row.get("project_id") or ""),
        ) in product_signal_keys
        for row in history_2025
    )
    summary = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "records": len(records),
        "product_level_records": product_records,
        "discovery_only_records": len(records) - product_records,
        "scope_unresolved_records": sum(
            row["product_name_status"] == SCOPE_UNRESOLVED_STATUS for row in records
        ),
        "detail_evidence_records": len(detail_evidence),
        "canonical_detail_records": len(details),
        "supplement_records": len(supplements),
        "directory_status_records": len(directory_status),
        "guidance_directory_entries": len(guidance_directories),
        "guidance_directory_diffs": len(guidance_diffs),
        "directory_matches": len(directory_matches),
        "directory_exact_matches": sum(
            row["match_type"] == "exact_material_name"
            for row in directory_matches
        ),
        "directory_fuzzy_matches": sum(
            row["match_type"] != "exact_material_name"
            for row in directory_matches
        ),
        "timeline_events": len(timeline),
        "timeline_publicity": sum(row["event_type"] == "publicity" for row in timeline),
        "timeline_recognition": sum(row["event_type"] == "recognition" for row in timeline),
        "timeline_reward": sum(row["event_type"] == "reward" for row in timeline),
        "timeline_directory_exit": sum(row["event_type"] == "directory_exit" for row in timeline),
        "enterprises": len(identities),
        "identity_profiles": len(identity_profiles),
        "identity_topic_direction_closed": sum(
            row["product_signal_status"] == "verified_product_signal"
            for row in identity_profiles
        ),
        "identity_topic_direction_pending": sum(
            row["product_signal_status"] == "identity_only_scope_unresolved"
            for row in identity_profiles
        ),
        "history_2025_scope_records": len(history_2025),
        "history_2025_identity_topic_closed": history_2025_topic_closed,
        "history_2025_identity_topic_pending": len(history_2025) - history_2025_topic_closed,
        "nodes": len(nodes),
        "edges": len(edges),
    }
    (args.output / "三首项目跨年对标图谱汇总.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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
            f"- 年度正式名单行缺少产品名称时标记 `{MISSING_PRODUCT_STATUS}`，并提示：{MISSING_PRODUCT_MESSAGE}",
            f"- 平台历史线索无法与同年度正式名单对应时标记 `{SCOPE_UNRESOLVED_STATUS}`；其他年度同企业产品仅进入身份级主题候选，不回填认定年度。",
            "- 状态时间轴仅依据原文分别记录公示、认定、奖励和目录退出；没有明确退出证据时不得推断已退出。",
            "",
            "## 汇总",
            "",
            *[f"- {key}: {value}" for key, value in summary.items()],
            "",
        ]),
        encoding="utf-8",
    )
    import_database(
        args.database,
        records,
        identity_profiles,
        all_evidence,
        timeline,
        guidance_directories,
        guidance_diffs,
        directory_matches,
        nodes,
        edges,
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

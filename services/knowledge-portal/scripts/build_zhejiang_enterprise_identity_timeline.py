#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PORTAL_DIR = Path(__file__).resolve().parents[1]
if str(PORTAL_DIR) not in sys.path:
    sys.path.insert(0, str(PORTAL_DIR))

from app.project_identity_twin import build_project_identity_twins  # noqa: E402


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_POLICY_VERSION_DB = Path(
    "/Users/zsh/JiaotangData/索引/current/policy_versions.sqlite3"
)
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
DEFAULT_LIFECYCLE_RULES = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "enterprise-lifecycle-rules.json"
)
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
    "国家高新技术企业",
    "浙江省隐形冠军企业",
    "浙江省创新型中小企业",
    "创新型中小企业评价",
    "国家制造业单项冠军企业",
    "浙江省制造业单项冠军企业",
    "国家科技型中小企业",
    "科技型中小企业评价",
}
EVENT_TYPE_PRECEDENCE = {
    "recognition_publicity": 10,
    "recognition": 20,
    "review_due": 30,
    "review_publicity": 40,
    "continued_support": 45,
    "annual_evaluation": 50,
    "review_passed": 60,
    "re_recognition": 70,
    "changed": 80,
    "revoked": 90,
}
ZHEJIANG_PREFECTURE_CITIES = (
    "杭州市",
    "宁波市",
    "温州市",
    "湖州市",
    "嘉兴市",
    "绍兴市",
    "金华市",
    "衢州市",
    "舟山市",
    "台州市",
    "丽水市",
)
COVERAGE_MATRIX_JSON = "省级项目年度设区市覆盖矩阵.json"
COVERAGE_MATRIX_CSV = "省级项目年度设区市覆盖矩阵.csv"
COVERAGE_COLLECTION_QUEUE = "省级项目年度设区市增量采集队列.jsonl"
EventKey = tuple[str, str, int | None, str, str, str]
IdentityEventKey = tuple[str, str, int | None, str, str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建浙江省企业身份与认定事件时间轴")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--small-giant-master", type=Path, default=DEFAULT_SMALL_GIANT_MASTER)
    parser.add_argument("--three-first", type=Path, default=DEFAULT_THREE_FIRST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tyc-enrichment", type=Path, default=DEFAULT_TYC_ENRICHMENT)
    parser.add_argument("--lifecycle-rules", type=Path, default=DEFAULT_LIFECYCLE_RULES)
    parser.add_argument(
        "--policy-version-database",
        type=Path,
        default=DEFAULT_POLICY_VERSION_DB,
    )
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


def merge_identity_event_rows(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse list-name aliases that resolve to the same legal entity event."""
    merged: dict[IdentityEventKey, dict[str, Any]] = {}
    collection_fields = (
        "source_paths",
        "source_urls",
        "sequence_numbers",
        "source_kinds",
    )
    for source_row in rows:
        row = dict(source_row)
        key: IdentityEventKey = (
            str(row["identity_key"]),
            str(row["project_name"]),
            row.get("event_year"),
            str(row.get("batch") or ""),
            str(row.get("status") or ""),
            str(row.get("event_type") or ""),
        )
        current = merged.get(key)
        if current is None:
            for field in collection_fields:
                row[field] = sorted(set(row.get(field, [])))
            merged[key] = row
            continue
        for field in collection_fields:
            current[field] = sorted(
                set(current.get(field, [])) | set(row.get(field, []))
            )
        if (
            str(row.get("enterprise_name_at_event") or "")
            < str(current.get("enterprise_name_at_event") or "")
        ):
            current["enterprise_name_at_event"] = row[
                "enterprise_name_at_event"
            ]
            current["normalized_name"] = row["normalized_name"]
    return list(merged.values())


def load_lifecycle_config(
    path: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, str],
    dict[str, Any],
]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rules: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for rule in payload.get("projects", []):
        project_name = str(rule["project_name"])
        rules[project_name] = dict(rule)
        for alias in [project_name, *rule.get("aliases", [])]:
            aliases[normalize_name(str(alias))] = project_name
    return (
        rules,
        list(payload.get("local_event_sources", [])),
        list(payload.get("regional_coverage_rules", [])),
        aliases,
        dict(payload.get("regional_coverage_discovery", {})),
    )


def canonical_lifecycle_project(project_name: str, aliases: dict[str, str]) -> str:
    return aliases.get(normalize_name(project_name), project_name)


def infer_event_type(title: str, status: str, project_name: str = "") -> str:
    text = f"{title} {status}"
    if any(term in text for term in ("撤销", "取消资格", "复核不通过", "未通过复核")):
        return "revoked"
    if "建议继续支持" in text or "继续支持" in text:
        return "continued_support"
    if "重新认定" in text:
        return "re_recognition"
    if "拟复核" in text or "复核拟推荐" in text:
        return "review_publicity"
    if "复核通过" in text:
        return "review_passed"
    if "复核对象" in text or "到期复核" in text or "有效期满" in text:
        return "review_due"
    if any(term in text for term in ("更名", "迁移", "合并", "重组", "变更")):
        return "changed"
    if project_name == "国家科技型中小企业" or "科技型中小企业评价" in text:
        return "annual_evaluation"
    if any(term in text for term in ("拟认定", "公示", "拟推荐", "推荐名单")):
        return "recognition_publicity"
    return "recognition"


def coverage_event_types(title: str, status: str, project_name: str) -> list[str]:
    text = f"{title} {status}"
    inferred: list[str] = []
    if "复核" in text:
        if any(term in text for term in ("拟复核", "复核拟推荐", "公示")):
            inferred.append("review_publicity")
        elif "复核通过" in text:
            inferred.append("review_passed")
        else:
            inferred.append("review_due")
    recognition_text = re.sub(
        r"(拟?复核通过|复核拟推荐|复核对象|到期复核|复核)",
        "",
        text,
    )
    if "认定" in recognition_text or "推荐名单" in recognition_text:
        inferred.append(
            "recognition_publicity"
            if any(term in recognition_text for term in ("拟认定", "公示", "拟推荐"))
            else "recognition"
        )
    if not inferred:
        inferred.append(infer_event_type(title, status, project_name))
    return list(dict.fromkeys(inferred))


def document_prefecture_city(title: str, region: str, source_path: str) -> str:
    text = f"{title}|{region}|{source_path}"
    matches = [
        city
        for city in ZHEJIANG_PREFECTURE_CITIES
        if city in text or city.removesuffix("市") in text
    ]
    return matches[0] if len(matches) == 1 else ""


def normalized_coverage_batch(batch: str, title: str) -> str:
    normalized = str(batch or "").strip()
    if not normalized:
        match = re.search(r"第[一二三四五六七八九十百\d]+批", title or "")
        normalized = match.group(0) if match else "未分批"
    return re.sub(
        "|".join(re.escape(city) for city in ZHEJIANG_PREFECTURE_CITIES),
        "",
        normalized,
    ).strip(" -—_|/、（）()") or "未分批"


def project_from_coverage_document(
    document_project: str,
    title: str,
    lifecycle_rules: dict[str, dict[str, Any]],
    lifecycle_aliases: dict[str, str],
) -> str:
    canonical = canonical_lifecycle_project(document_project, lifecycle_aliases)
    if canonical in lifecycle_rules and canonical.startswith("浙江省"):
        return canonical
    normalized_title = normalize_name(title)
    for alias, project_name in sorted(
        lifecycle_aliases.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if (
            project_name in lifecycle_rules
            and project_name.startswith("浙江省")
            and alias
            and alias in normalized_title
        ):
            return project_name
    return ""


def discover_regional_coverage_sources(
    database: Path,
    lifecycle_rules: dict[str, dict[str, Any]],
    lifecycle_aliases: dict[str, str],
) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    document_columns = {
        str(row["name"]) for row in connection.execute("PRAGMA table_info(documents)")
    }
    table_names = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    def document_column(name: str, default: str = "''") -> str:
        return f"d.{name}" if name in document_columns else default

    mention_count_expression = (
        "(SELECT COUNT(*) FROM enterprise_mentions m WHERE m.document_id=d.id)"
        if "enterprise_mentions" in table_names
        else "0"
    )
    rows = connection.execute(
        f"""
        SELECT d.id,
               {document_column("title")} AS title,
               {document_column("source")} AS source,
               {document_column("cloud_path")} AS cloud_path,
               {document_column("canonical_project_name")} AS document_project,
               {document_column("policy_year", "NULL")} AS policy_year,
               {document_column("batch")} AS batch,
               {document_column("region")} AS region,
               {document_column("document_stage")} AS document_stage,
               {document_column("sha256")} AS sha256,
               {document_column("updated_at")} AS updated_at,
               COUNT(DISTINCT e.id) AS list_entity_count,
               {mention_count_expression} AS mention_count
        FROM documents d
        LEFT JOIN public_list_entities e ON e.document_id=d.id
        WHERE (
            {document_column("document_role")}='50_名单与对标'
            OR (
                {document_column("document_role")}='10_政策与通知'
                AND {document_column("document_stage")}
                    IN ('公示名单','认定名单')
            )
        )
        GROUP BY d.id
        """
    ).fetchall()
    connection.close()

    sources: list[dict[str, Any]] = []
    for row in rows:
        title = str(row["title"] or "")
        source_path = str(row["cloud_path"] or row["source"] or "")
        region = str(row["region"] or "")
        project_name = project_from_coverage_document(
            str(row["document_project"] or ""),
            title,
            lifecycle_rules,
            lifecycle_aliases,
        )
        if not project_name:
            continue
        document_project = str(row["document_project"] or "")
        city = document_prefecture_city(title, region, source_path)
        independent_ningbo_signal = (
            project_name == "浙江省专精特新中小企业"
            and city == "宁波市"
            and "专精特新" in title
            and "中小企业" in title
        )
        provincial_signal = (
            "浙江" in f"{title}|{region}|{source_path}"
            or "省级" in title
            or "省专精特新" in title
            or project_name.startswith("浙江省")
            or independent_ningbo_signal
        )
        if not provincial_signal:
            continue
        if re.search(r"(奖励|补助|兑付|用电成本|财政支持)", title):
            continue
        if not city:
            continue
        event_year = (
            int(row["policy_year"])
            if row["policy_year"] is not None
            else first_year(title)
        )
        if event_year is None:
            continue
        batch = normalized_coverage_batch(str(row["batch"] or ""), title)
        fallback_payload = {
            "document_id": int(row["id"]),
            "title": title,
            "source_path": source_path,
            "updated_at": str(row["updated_at"] or ""),
        }
        source_fingerprint = str(row["sha256"] or "") or hashlib.sha256(
            json.dumps(
                fallback_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for event_type in coverage_event_types(
            title,
            str(row["document_stage"] or ""),
            project_name,
        ):
            sources.append(
                {
                    "source_id": f"document-{int(row['id'])}-{event_type}",
                    "document_id": int(row["id"]),
                    "document_title": title,
                    "project_name": project_name,
                    "event_year": event_year,
                    "event_type": event_type,
                    "batch": batch,
                    "city": city,
                    "source_path": source_path,
                    "official_url": "",
                    "evidence_archive_url": "",
                    "source_fingerprint": source_fingerprint,
                    "entity_count": max(
                        int(row["list_entity_count"] or 0),
                        int(row["mention_count"] or 0),
                    ),
                    "coverage_confirmed_empty": False,
                    "registration_source": "knowledge_index_auto_discovery",
                }
            )
    return sources


def _matrix_source_from_manifest(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(source.get("source_id") or ""),
        "document_id": source.get("document_id"),
        "document_title": str(source.get("document_title") or ""),
        "project_name": str(
            source.get("coverage_project_name")
            or source.get("project_name")
            or ""
        ),
        "event_year": (
            source.get("coverage_event_year")
            if source.get("coverage_event_year") is not None
            else source.get("event_year")
        ),
        "event_type": str(
            source.get("coverage_event_type")
            or source.get("event_type")
            or ""
        ),
        "batch": normalized_coverage_batch(
            str(source.get("coverage_batch") or source.get("batch") or ""),
            str(source.get("document_title") or ""),
        ),
        "city": str(source.get("city") or ""),
        "covered_cities": [
            str(city)
            for city in source.get("covered_cities", [])
            if str(city)
        ],
        "coverage_basis": str(
            source.get("coverage_basis") or "direct_city_attachment"
        ),
        "source_path": str(source.get("source_path") or ""),
        "official_url": str(source.get("official_url") or ""),
        "evidence_archive_url": str(source.get("evidence_archive_url") or ""),
        "source_fingerprint": str(source.get("source_fingerprint") or ""),
        "entity_count": int(
            source.get("actual_count")
            if source.get("actual_count") is not None
            else source.get("entity_count")
            or 0
        ),
        "coverage_confirmed_empty": bool(source.get("coverage_confirmed_empty")),
        "registration_source": str(
            source.get("registration_source") or "configured_manifest"
        ),
    }


def build_regional_coverage_matrix(
    output: Path,
    lifecycle_rules: dict[str, dict[str, Any]],
    coverage_rules: list[dict[str, Any]],
    lifecycle_source_audits: list[dict[str, Any]],
    discovered_sources: list[dict[str, Any]],
    discovery_settings: dict[str, Any],
) -> dict[str, Any]:
    configured_regions = tuple(
        str(city)
        for city in discovery_settings.get(
            "expected_regions",
            ZHEJIANG_PREFECTURE_CITIES,
        )
    )
    if set(configured_regions) != set(ZHEJIANG_PREFECTURE_CITIES):
        raise ValueError("regional coverage discovery must contain all 11 Zhejiang cities")

    previous_rows: dict[tuple[str, str], dict[str, Any]] = {}
    previous_path = output / COVERAGE_MATRIX_JSON
    if previous_path.is_file():
        try:
            previous_payload = json.loads(previous_path.read_text(encoding="utf-8"))
            previous_rows = {
                (str(row["coverage_group_id"]), str(row["city"])): row
                for row in previous_payload.get("rows", [])
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            previous_rows = {}

    configured_groups: dict[str, dict[str, Any]] = {}
    for rule in coverage_rules:
        group_id = str(rule["coverage_group_id"])
        configured_groups[group_id] = {
            "coverage_group_id": group_id,
            "project_name": str(rule.get("project_name") or ""),
            "event_year": rule.get("event_year"),
            "event_type": str(rule.get("event_type") or ""),
            "batch": normalized_coverage_batch(
                str(rule.get("batch") or ""),
                str(rule.get("project_name") or ""),
            ),
            "strict": bool(rule.get("strict", True)),
            "registration_mode": "configured_strict",
            "sources": [],
        }
    for source in lifecycle_source_audits:
        group_id = str(source.get("coverage_group_id") or "")
        if group_id and group_id in configured_groups:
            configured_groups[group_id]["sources"].append(
                _matrix_source_from_manifest(source)
            )

    explicit_keys = {
        (
            str(group["project_name"]),
            group["event_year"],
            str(group["event_type"]),
        )
        for group in configured_groups.values()
    }
    auto_sources = list(discovered_sources)
    auto_sources.extend(
        _matrix_source_from_manifest(source)
        for source in lifecycle_source_audits
        if not source.get("coverage_group_id")
        and (
            str(source.get("city") or "") in configured_regions
            or any(
                str(city) in configured_regions
                for city in source.get("covered_cities", [])
            )
        )
        and str(source.get("project_name") or "").startswith("浙江省")
    )
    auto_groups: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    included_projects = {
        str(project)
        for project in discovery_settings.get("included_projects", [])
        if str(project)
    }
    included_event_years = {
        int(year)
        for year in discovery_settings.get("included_event_years", [])
        if str(year).isdigit()
    }
    included_groups = {
        (
            str(group.get("project_name") or ""),
            int(group["event_year"]),
            normalized_coverage_batch(
                str(group.get("batch") or ""),
                str(group.get("project_name") or ""),
            ),
            str(group.get("event_type") or ""),
        )
        for group in discovery_settings.get("included_groups", [])
        if isinstance(group, dict)
        and str(group.get("event_year") or "").isdigit()
    }
    batch_aliases = {
        str(key): str(value)
        for key, value in discovery_settings.get("batch_aliases", {}).items()
        if str(key) and str(value)
    }
    for source in auto_sources:
        project_name = str(source.get("project_name") or "")
        event_type = str(source.get("event_type") or "")
        event_year_value = source.get("event_year")
        source_regions = [
            str(city)
            for city in (
                source.get("covered_cities", [])
                or [source.get("city")]
            )
            if str(city)
        ]
        if (
            project_name not in lifecycle_rules
            or not project_name.startswith("浙江省")
            or not event_type
            or event_year_value is None
            or not any(city in configured_regions for city in source_regions)
        ):
            continue
        event_year = int(event_year_value)
        if included_projects and project_name not in included_projects:
            continue
        if included_event_years and event_year not in included_event_years:
            continue
        if (project_name, event_year, event_type) in explicit_keys:
            continue
        batch = normalized_coverage_batch(
            str(source.get("batch") or ""),
            str(source.get("document_title") or ""),
        )
        batch = batch_aliases.get(
            f"{event_year}|{event_type}|{batch}",
            batch,
        )
        if (
            included_groups
            and (project_name, event_year, batch, event_type)
            not in included_groups
        ):
            continue
        key = (project_name, event_year, batch, event_type)
        group = auto_groups.setdefault(
            key,
            {
                "project_name": project_name,
                "event_year": event_year,
                "event_type": event_type,
                "batch": batch,
                "strict": False,
                "registration_mode": "auto_discovered",
                "sources": [],
            },
        )
        group["sources"].append(source)

    for key, group in auto_groups.items():
        project_name, event_year, batch, event_type = key
        rule_id = str(lifecycle_rules[project_name].get("rule_id") or "project")
        batch_digest = hashlib.sha256(batch.encode("utf-8")).hexdigest()[:8]
        group["coverage_group_id"] = (
            f"{rule_id}-{event_year}-{event_type}-{batch_digest}-11-cities"
        )

    groups = list(configured_groups.values()) + list(auto_groups.values())
    groups.sort(
        key=lambda row: (
            str(row["project_name"]),
            int(row["event_year"] or 0),
            str(row["batch"]),
            str(row["event_type"]),
        )
    )

    matrix_rows: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []
    collection_queue: list[dict[str, Any]] = []
    for group in groups:
        sources_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for source in group["sources"]:
            fingerprint = str(source.get("source_fingerprint") or "")
            source_regions = [
                str(city)
                for city in (
                    source.get("covered_cities", [])
                    or [source.get("city")]
                )
                if str(city) in configured_regions
            ]
            if not source_regions or not fingerprint:
                continue
            for city in source_regions:
                city_source = {**source, "city": city}
                if any(
                    str(existing.get("source_fingerprint") or "") == fingerprint
                    for existing in sources_by_city[city]
                ):
                    continue
                sources_by_city[city].append(city_source)
        missing_cities: list[str] = []
        group_rows: list[dict[str, Any]] = []
        for city in configured_regions:
            city_sources = sorted(
                sources_by_city.get(city, []),
                key=lambda row: (
                    str(row.get("source_fingerprint") or ""),
                    str(row.get("source_id") or ""),
                ),
            )
            fingerprints = sorted(
                {
                    str(source.get("source_fingerprint") or "")
                    for source in city_sources
                    if source.get("source_fingerprint")
                }
            )
            combined_fingerprint = (
                hashlib.sha256("|".join(fingerprints).encode("utf-8")).hexdigest()
                if fingerprints
                else ""
            )
            previous = previous_rows.get(
                (str(group["coverage_group_id"]), city),
                {},
            )
            previous_fingerprint = str(previous.get("content_fingerprint") or "")
            if not city_sources:
                coverage_state = "missing_source"
                missing_cities.append(city)
            elif previous_fingerprint == combined_fingerprint:
                coverage_state = "hash_reused"
            elif previous_fingerprint:
                coverage_state = "source_changed"
            else:
                coverage_state = "new_source_registered"
            row = {
                "coverage_group_id": str(group["coverage_group_id"]),
                "project_name": str(group["project_name"]),
                "event_year": group["event_year"],
                "batch": str(group["batch"]),
                "event_type": str(group["event_type"]),
                "city": city,
                "coverage_state": coverage_state,
                "content_fingerprint": combined_fingerprint,
                "previous_content_fingerprint": previous_fingerprint,
                "source_count": len(city_sources),
                "entity_count": sum(
                    int(source.get("entity_count") or 0)
                    for source in city_sources
                ),
                "registration_mode": str(group["registration_mode"]),
                "strict": bool(group["strict"]),
                "sources": [
                    {
                        "source_id": str(source.get("source_id") or ""),
                        "document_id": source.get("document_id"),
                        "document_title": str(source.get("document_title") or ""),
                        "source_path": str(source.get("source_path") or ""),
                        "official_url": str(source.get("official_url") or ""),
                        "evidence_archive_url": str(
                            source.get("evidence_archive_url") or ""
                        ),
                        "source_fingerprint": str(
                            source.get("source_fingerprint") or ""
                        ),
                        "registration_source": str(
                            source.get("registration_source") or ""
                        ),
                        "coverage_basis": str(
                            source.get("coverage_basis")
                            or "direct_city_attachment"
                        ),
                    }
                    for source in city_sources
                ],
            }
            group_rows.append(row)
            matrix_rows.append(row)
            if coverage_state in {"missing_source", "source_changed"}:
                collection_queue.append(
                    {
                        "coverage_group_id": row["coverage_group_id"],
                        "project_name": row["project_name"],
                        "event_year": row["event_year"],
                        "batch": row["batch"],
                        "event_type": row["event_type"],
                        "city": city,
                        "action": (
                            "fetch_missing_source"
                            if coverage_state == "missing_source"
                            else "revalidate_changed_source"
                        ),
                        "reason": coverage_state,
                        "lookup_query": (
                            f"{row['event_year']} {city} {row['project_name']} "
                            f"{row['batch']} {row['event_type']} 名单 附件"
                        ),
                        "known_sources": row["sources"],
                    }
                )
        complete = not missing_cities
        group_summaries.append(
            {
                "coverage_group_id": str(group["coverage_group_id"]),
                "project_name": str(group["project_name"]),
                "event_year": group["event_year"],
                "batch": str(group["batch"]),
                "event_type": str(group["event_type"]),
                "registration_mode": str(group["registration_mode"]),
                "strict": bool(group["strict"]),
                "expected_city_count": len(configured_regions),
                "covered_city_count": len(configured_regions) - len(missing_cities),
                "missing_cities": missing_cities,
                "complete": complete,
                "completeness_claim_allowed": complete,
                "hash_reused_city_count": sum(
                    row["coverage_state"] == "hash_reused" for row in group_rows
                ),
                "changed_city_count": sum(
                    row["coverage_state"] == "source_changed" for row in group_rows
                ),
                "new_city_count": sum(
                    row["coverage_state"] == "new_source_registered"
                    for row in group_rows
                ),
            }
        )

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "generated_at": generated_at,
        "schema_version": 1,
        "scope": "浙江省省级项目按年度、批次、事件类型和11个设区市的附件覆盖",
        "expected_regions": list(configured_regions),
        "groups": group_summaries,
        "rows": matrix_rows,
        "incremental_policy": {
            "unchanged": "content hash reused; no fetch",
            "missing": "queued for missing source collection",
            "changed": "queued for changed source revalidation",
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    previous_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    csv_fields = [
        "coverage_group_id",
        "project_name",
        "event_year",
        "batch",
        "event_type",
        "city",
        "coverage_state",
        "content_fingerprint",
        "previous_content_fingerprint",
        "source_count",
        "entity_count",
        "registration_mode",
        "strict",
        "sources",
    ]
    with (output / COVERAGE_MATRIX_CSV).open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for row in matrix_rows:
            writer.writerow(
                {
                    **row,
                    "sources": json.dumps(row["sources"], ensure_ascii=False),
                }
            )
    with (output / COVERAGE_COLLECTION_QUEUE).open("w", encoding="utf-8") as handle:
        for item in collection_queue:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return {
        "generated_at": generated_at,
        "groups": group_summaries,
        "rows": matrix_rows,
        "collection_queue": collection_queue,
    }


def lifecycle_rule_for(
    project_name: str,
    rules: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return rules.get(project_name)


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
    events: dict[EventKey, dict[str, Any]],
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
    event_type: str = "",
    event_scope: str = "",
    evidence_status: str = "",
    cohort_year: int | None = None,
    lifecycle_rule: dict[str, Any] | None = None,
) -> None:
    enterprise_name = enterprise_name.strip()
    if not enterprise_name:
        return
    event_type = event_type or infer_event_type(source_title, status, project_name)
    if not event_scope:
        event_scope = "fiscal_support" if event_type == "continued_support" else "qualification"
    if not evidence_status:
        evidence_status = (
            "official_publicity"
            if event_type in {"recognition_publicity", "review_publicity"}
            else "official_or_archived_list"
        )
    key = (normalize_name(enterprise_name), project_name, year, batch, status, event_type)
    item = events.setdefault(
        key,
        {
            "enterprise_name_at_event": enterprise_name,
            "normalized_name": normalize_name(enterprise_name),
            "project_name": project_name,
            "event_year": year,
            "recognition_year": year,
            "cohort_year": cohort_year,
            "event_type": event_type,
            "event_scope": event_scope,
            "evidence_status": evidence_status,
            "lifecycle_rule_id": str((lifecycle_rule or {}).get("rule_id") or ""),
            "cycle_type": str((lifecycle_rule or {}).get("cycle_type") or ""),
            "validity_years": (lifecycle_rule or {}).get("validity_years"),
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
    if item["cohort_year"] is None and cohort_year is not None:
        item["cohort_year"] = cohort_year
    if not item["recognition_city"] and city:
        item["recognition_city"] = city
    if not item["recognition_county"] and county:
        item["recognition_county"] = county


def lifecycle_section(content: str, start_pattern: str, end_pattern: str) -> str:
    start = 0
    if start_pattern:
        match = re.search(start_pattern, content, re.DOTALL)
        if not match:
            raise ValueError(f"lifecycle start marker not found: {start_pattern}")
        start = match.start()
    end = len(content)
    if end_pattern:
        match = re.search(end_pattern, content[start:], re.DOTALL)
        if not match:
            raise ValueError(f"lifecycle end marker not found: {end_pattern}")
        end = start + match.start()
    return content[start:end]


def numbered_organization_lines(content: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in content.splitlines():
        # Official attachments are commonly extracted as ``1 企业名称`` while
        # normalized evidence archives use Markdown's ``1. 企业名称`` form.
        match = re.match(r"^\s*(\d+)(?:\s*[.．、）)]\s*|\s+)(.+?)\s*$", line)
        if not match:
            continue
        name = match.group(2).strip()
        if not re.search(
            r"(公司|研究院|合作社|厂|中心|事务所|学院)$",
            name,
        ):
            continue
        rows.append((name, match.group(1)))
    return rows


def xlsx_enterprise_column(path: Path) -> list[tuple[str, str]]:
    """Read an enterprise-name column without depending on a workbook runtime."""
    if not path.is_file():
        raise ValueError(f"spreadsheet lifecycle source not found: {path}")
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.itertext()).strip()
                for node in shared_root.findall("a:si", namespace)
            ]
        worksheet_paths = sorted(
            name
            for name in archive.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        for worksheet_path in worksheet_paths:
            root = ET.fromstring(archive.read(worksheet_path))
            parsed_rows: list[dict[int, str]] = []
            for row in root.findall(".//a:sheetData/a:row", namespace):
                parsed: dict[int, str] = {}
                for cell in row.findall("a:c", namespace):
                    reference = str(cell.get("r") or "")
                    column_letters = re.match(r"[A-Z]+", reference)
                    if not column_letters:
                        continue
                    column_index = 0
                    for character in column_letters.group(0):
                        column_index = column_index * 26 + ord(character) - 64
                    cell_type = str(cell.get("t") or "")
                    value_node = cell.find("a:v", namespace)
                    if cell_type == "inlineStr":
                        inline = cell.find("a:is", namespace)
                        value = "".join(inline.itertext()) if inline is not None else ""
                    elif value_node is None:
                        value = ""
                    elif cell_type == "s":
                        shared_index = int(value_node.text or 0)
                        value = (
                            shared_strings[shared_index]
                            if 0 <= shared_index < len(shared_strings)
                            else ""
                        )
                    else:
                        value = str(value_node.text or "")
                    parsed[column_index] = value.strip()
                if parsed:
                    parsed_rows.append(parsed)
            header_position: tuple[int, int] | None = None
            for row_index, parsed in enumerate(parsed_rows):
                for column_index, value in parsed.items():
                    if normalize_name(value) in {"企业名称", "企业名单"}:
                        header_position = (row_index, column_index)
                        break
                if header_position:
                    break
            if not header_position:
                continue
            header_row, enterprise_column = header_position
            names: list[tuple[str, str]] = []
            for sequence, parsed in enumerate(
                parsed_rows[header_row + 1 :],
                start=1,
            ):
                name = str(parsed.get(enterprise_column) or "").strip()
                if not name or not re.search(
                    r"(公司|研究院|合作社|厂|中心|事务所|学院)$",
                    name,
                ):
                    continue
                sequence_no = str(parsed.get(enterprise_column - 1) or sequence)
                names.append((name, sequence_no))
            if names:
                return names
    raise ValueError(f"spreadsheet enterprise-name column not found: {path}")


def load_manifest_lifecycle_events(
    database: Path,
    sources: list[dict[str, Any]],
    rules: dict[str, dict[str, Any]],
    events: dict[EventKey, dict[str, Any]],
) -> tuple[set[tuple[int, str]], list[dict[str, Any]]]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    document_columns = {
        str(row["name"]) for row in connection.execute("PRAGMA table_info(documents)")
    }
    sha256_expression = "d.sha256" if "sha256" in document_columns else "''"
    exclusions: set[tuple[int, str]] = set()
    audits: list[dict[str, Any]] = []
    for source in sources:
        names: list[tuple[str, str]] = []
        document_id: int | None = None
        document_sha256 = ""
        document_content = ""
        source_title = str(source["document_title"])
        source_path = str(source.get("source_path") or "")
        has_inline_entities = "entities" in source
        has_spreadsheet_entities = (
            source.get("entity_extraction") == "spreadsheet_enterprise_column"
        )
        inline_entities = list(source.get("entities") or [])
        if has_inline_entities:
            for index, entity in enumerate(inline_entities, start=1):
                if isinstance(entity, dict):
                    name = str(entity.get("enterprise_name") or "").strip()
                    sequence_no = str(entity.get("sequence_no") or index)
                else:
                    name = str(entity).strip()
                    sequence_no = str(index)
                if name:
                    names.append((name, sequence_no))
        elif has_spreadsheet_entities:
            spreadsheet_path = Path(source_path).expanduser()
            names = xlsx_enterprise_column(spreadsheet_path)
            document_sha256 = hashlib.sha256(
                spreadsheet_path.read_bytes()
            ).hexdigest()
        else:
            documents = connection.execute(
                f"""
                SELECT d.id,d.title,d.content,d.source,d.cloud_path,
                       {sha256_expression} AS sha256,
                       COUNT(m.id) AS mention_count
                FROM documents d
                LEFT JOIN enterprise_mentions m ON m.document_id=d.id
                WHERE d.title=?
                GROUP BY d.id
                ORDER BY mention_count DESC,d.id
                """,
                (source_title,),
            ).fetchall()
            if not documents:
                connection.close()
                raise ValueError(f"lifecycle source document not found: {source_title}")
            document = documents[0]
            document_id = int(document["id"])
            document_sha256 = str(document["sha256"] or "")
            document_content = str(document["content"] or "")
            source_title = str(document["title"])
            source_path = str(document["cloud_path"] or document["source"] or "")
            section = lifecycle_section(
                document_content,
                str(source.get("start_pattern") or ""),
                str(source.get("end_pattern") or ""),
            )
            if source.get("entity_extraction") == "numbered_organization_lines":
                names = numbered_organization_lines(section)
                mentions = []
            else:
                mentions = connection.execute(
                    """
                    SELECT enterprise_name,sequence_no
                    FROM enterprise_mentions
                    WHERE document_id=?
                    ORDER BY id
                    """,
                    (document_id,),
                ).fetchall()
            seen: set[str] = set()
            for mention in mentions:
                name = str(mention["enterprise_name"] or "").strip()
                normalized = normalize_name(name)
                if not name or normalized in seen or name not in section:
                    continue
                seen.add(normalized)
                names.append((name, str(mention["sequence_no"] or "")))
        expected_count_configured = "expected_count" in source
        expected_count = int(source.get("expected_count") or 0)
        count_aligned = not expected_count_configured or expected_count == len(names)
        if not count_aligned:
            connection.close()
            raise ValueError(
                f"lifecycle source count mismatch: {source['source_id']} "
                f"expected={expected_count} actual={len(names)}"
            )
        project_name = str(source["project_name"])
        if has_inline_entities:
            fingerprint_payload = {
                "source_id": source.get("source_id"),
                "document_title": source_title,
                "source_path": source_path,
                "official_url": source.get("official_url"),
                "evidence_archive_url": source.get("evidence_archive_url"),
                "project_name": project_name,
                "event_year": source.get("event_year"),
                "batch": source.get("batch"),
                "event_type": source.get("event_type"),
                "entities": inline_entities,
                "coverage_confirmed_empty": source.get("coverage_confirmed_empty"),
            }
            source_fingerprint = hashlib.sha256(
                json.dumps(
                    fingerprint_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        else:
            source_fingerprint = document_sha256 or hashlib.sha256(
                document_content.encode("utf-8")
            ).hexdigest()
        rule = lifecycle_rule_for(project_name, rules)
        for name, sequence_no in names:
            if document_id is not None:
                exclusions.add((document_id, normalize_name(name)))
            add_event(
                events,
                enterprise_name=name,
                project_name=project_name,
                year=int(source["event_year"]) if source.get("event_year") is not None else None,
                cohort_year=(
                    int(source["cohort_year"])
                    if source.get("cohort_year") is not None
                    else None
                ),
                batch=str(source.get("batch") or ""),
                status=str(source.get("status") or ""),
                province="浙江省",
                city=str(source.get("city") or ""),
                county="",
                source_title=source_title,
                source_path=source_path,
                source_url=str(
                    source.get("official_url")
                    or source.get("evidence_archive_url")
                    or ""
                ),
                sequence_no=sequence_no,
                source_kind="lifecycle_manifest",
                event_type=str(source.get("event_type") or ""),
                event_scope=str(source.get("event_scope") or ""),
                evidence_status=str(source.get("evidence_status") or ""),
                lifecycle_rule=rule,
            )
        audits.append(
            {
                "source_id": str(source["source_id"]),
                "document_id": document_id,
                "document_title": source_title,
                "project_name": project_name,
                "event_type": str(source.get("event_type") or ""),
                "event_year": source.get("event_year"),
                "batch": str(source.get("batch") or ""),
                "coverage_group_id": str(source.get("coverage_group_id") or ""),
                "city": str(source.get("city") or ""),
                "covered_cities": [
                    str(city)
                    for city in source.get("covered_cities", [])
                    if str(city)
                ],
                "coverage_project_name": str(
                    source.get("coverage_project_name") or ""
                ),
                "coverage_event_year": source.get("coverage_event_year"),
                "coverage_event_type": str(
                    source.get("coverage_event_type") or ""
                ),
                "coverage_batch": str(source.get("coverage_batch") or ""),
                "coverage_basis": str(
                    source.get("coverage_basis") or ""
                ),
                "published_at": str(source.get("published_at") or ""),
                "source_path": source_path,
                "official_url": str(source.get("official_url") or ""),
                "evidence_archive_url": str(source.get("evidence_archive_url") or ""),
                "coverage_confirmed_empty": bool(
                    source.get("coverage_confirmed_empty")
                ),
                "expected_count": expected_count,
                "actual_count": len(names),
                "count_aligned": count_aligned,
                "source_fingerprint": source_fingerprint,
                "registration_source": "configured_manifest",
            }
        )
    connection.close()
    return exclusions, audits


def audit_regional_source_coverage(
    coverage_rules: list[dict[str, Any]],
    source_audits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    configured = {
        str(rule["coverage_group_id"]): rule for rule in coverage_rules
    }
    source_groups = {
        str(source["coverage_group_id"])
        for source in source_audits
        if source.get("coverage_group_id")
    }
    unknown_groups = sorted(source_groups - set(configured))
    if unknown_groups:
        raise ValueError(
            "regional coverage group missing rule: " + ",".join(unknown_groups)
        )

    audits: list[dict[str, Any]] = []
    for coverage_group_id, rule in configured.items():
        expected_regions = [str(region) for region in rule.get("expected_regions", [])]
        matching_sources = [
            source
            for source in source_audits
            if source.get("coverage_group_id") == coverage_group_id
        ]
        sources_by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for source in matching_sources:
            sources_by_region[str(source.get("city") or "")].append(source)

        duplicate_regions = sorted(
            region
            for region, items in sources_by_region.items()
            if region and len(items) > 1
        )
        unexpected_regions = sorted(
            region
            for region in sources_by_region
            if region and region not in expected_regions
        )
        missing_regions = [
            region for region in expected_regions if region not in sources_by_region
        ]
        unconfirmed_empty_regions = sorted(
            region
            for region, items in sources_by_region.items()
            if region
            and sum(int(item["actual_count"]) for item in items) == 0
            and not all(bool(item["coverage_confirmed_empty"]) for item in items)
        )
        count_mismatch_regions = sorted(
            region
            for region, items in sources_by_region.items()
            if region and not all(bool(item["count_aligned"]) for item in items)
        )
        complete = not any(
            (
                missing_regions,
                unexpected_regions,
                duplicate_regions,
                unconfirmed_empty_regions,
                count_mismatch_regions,
            )
        )
        audit = {
            "coverage_group_id": coverage_group_id,
            "project_name": str(rule.get("project_name") or ""),
            "event_year": rule.get("event_year"),
            "event_type": str(rule.get("event_type") or ""),
            "scope": str(rule.get("scope") or ""),
            "expected_region_count": len(expected_regions),
            "covered_region_count": len(
                [region for region in expected_regions if region in sources_by_region]
            ),
            "expected_regions": expected_regions,
            "covered_regions": [
                region for region in expected_regions if region in sources_by_region
            ],
            "missing_regions": missing_regions,
            "unexpected_regions": unexpected_regions,
            "duplicate_regions": duplicate_regions,
            "unconfirmed_empty_regions": unconfirmed_empty_regions,
            "count_mismatch_regions": count_mismatch_regions,
            "entity_count": sum(
                int(source["actual_count"]) for source in matching_sources
            ),
            "regions": [
                {
                    "city": region,
                    "source_count": len(sources_by_region.get(region, [])),
                    "entity_count": sum(
                        int(source["actual_count"])
                        for source in sources_by_region.get(region, [])
                    ),
                    "sources": [
                        {
                            "source_id": source["source_id"],
                            "document_title": source["document_title"],
                            "published_at": source["published_at"],
                            "expected_count": source["expected_count"],
                            "actual_count": source["actual_count"],
                            "source_path": source["source_path"],
                            "official_url": source["official_url"],
                            "evidence_archive_url": source["evidence_archive_url"],
                        }
                        for source in sources_by_region.get(region, [])
                    ],
                }
                for region in expected_regions
            ],
            "complete": complete,
            "strict": bool(rule.get("strict", True)),
        }
        audits.append(audit)
        if audit["strict"] and not complete:
            raise ValueError(
                f"regional coverage incomplete: {coverage_group_id} "
                f"missing={missing_regions} unexpected={unexpected_regions} "
                f"duplicate={duplicate_regions} "
                f"unconfirmed_empty={unconfirmed_empty_regions} "
                f"count_mismatch={count_mismatch_regions}"
            )
    return audits


def load_small_giant_events(
    path: Path,
    events: dict[EventKey, dict[str, Any]],
    rules: dict[str, dict[str, Any]],
) -> None:
    project_name = "国家专精特新“小巨人”企业"
    rule = lifecycle_rule_for(project_name, rules)
    for row in read_csv(path):
        if row.get("region") != "浙江省":
            continue
        add_event(
            events,
            enterprise_name=row.get("enterprise_name", ""),
            project_name=project_name,
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
            event_type="recognition",
            event_scope="qualification",
            evidence_status="official_final_list",
            lifecycle_rule=rule,
        )


def load_list_events(
    database: Path,
    events: dict[EventKey, dict[str, Any]],
    rules: dict[str, dict[str, Any]],
    lifecycle_aliases: dict[str, str],
    exclusions: set[tuple[int, str]],
) -> None:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT d.id AS document_id,e.enterprise_name,e.sequence_no,e.canonical_project_name,e.policy_year,
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
        project_name = canonical_lifecycle_project(project_name, lifecycle_aliases)
        if project_name == "国家专精特新“小巨人”企业":
            continue
        if project_name not in TARGET_PROJECTS and project_name not in rules:
            continue
        if (int(row["document_id"]), normalize_name(str(row["enterprise_name"]))) in exclusions:
            continue
        province, city, county = normalize_region(str(row["region"]))
        event_type = infer_event_type(str(row["title"]), str(row["list_status"]), project_name)
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
            event_type=event_type,
            event_scope="qualification",
            lifecycle_rule=lifecycle_rule_for(project_name, rules),
        )


def load_three_first_events(
    path: Path,
    events: dict[EventKey, dict[str, Any]],
    rules: dict[str, dict[str, Any]],
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
            event_type=infer_event_type(
                str(row.get("source_title") or ""),
                str(row.get("list_status") or ""),
                project_name,
            ),
            lifecycle_rule=lifecycle_rule_for(project_name, rules),
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


def write_policy_lifecycle_audit(
    database: Path,
    output: Path,
    lifecycle_rules: dict[str, dict[str, Any]],
    lifecycle_source_audits: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    confirmed: list[dict[str, Any]] = []
    configured_names: set[str] = set()
    configured_normalized_names: set[str] = set()
    for rule in lifecycle_rules.values():
        names = [str(rule["project_name"]), *[str(item) for item in rule.get("aliases", [])]]
        configured_names.update(names)
        configured_normalized_names.update(normalize_name(name) for name in names)
        placeholders = ",".join("?" for _ in names)
        rows = connection.execute(
            f"""
            SELECT id,title,source,document_role,canonical_project_name,policy_year
            FROM documents
            WHERE canonical_project_name IN ({placeholders})
               OR title IN ({placeholders})
            ORDER BY policy_year DESC,id DESC
            """,
            (*names, *names),
        ).fetchall()
        lifecycle_rows = [
            row
            for row in rows
            if any(
                term in str(row["title"])
                for term in ("复核", "重新认定", "有效期", "继续支持", "撤销", "取消")
            )
        ]
        confirmed.append(
            {
                "rule_id": str(rule["rule_id"]),
                "project_name": str(rule["project_name"]),
                "cycle_type": str(rule["cycle_type"]),
                "validity_years": rule.get("validity_years"),
                "current_rule_state": str(rule["current_rule_state"]),
                "policy_document_count": len(rows),
                "title_level_lifecycle_document_count": len(lifecycle_rows),
                "sample_sources": [
                    {
                        "title": str(row["title"]),
                        "source": str(row["source"]),
                        "policy_year": row["policy_year"],
                    }
                    for row in lifecycle_rows[:5]
                ],
            }
        )
    candidate_rows = connection.execute(
        """
        SELECT canonical_project_name,COUNT(*) AS document_count,
               SUM(CASE WHEN title LIKE '%复核%' THEN 1 ELSE 0 END) AS review_title_count,
               SUM(CASE WHEN title LIKE '%重新认定%' THEN 1 ELSE 0 END) AS rerecognition_title_count,
               SUM(CASE WHEN title LIKE '%有效期%' THEN 1 ELSE 0 END) AS validity_title_count
        FROM documents
        WHERE canonical_project_name<>''
          AND document_role IN ('10_政策与通知','20_项目规则与指南','20_申报指南与规则')
          AND (
              title LIKE '%复核%'
              OR title LIKE '%重新认定%'
              OR title LIKE '%有效期%'
              OR title LIKE '%动态管理%'
              OR title LIKE '%撤销%'
          )
        GROUP BY canonical_project_name
        ORDER BY document_count DESC,canonical_project_name
        """
    ).fetchall()
    connection.close()
    candidates = [
        {
            "project_name": str(row["canonical_project_name"]),
            "document_count": int(row["document_count"]),
            "review_title_count": int(row["review_title_count"]),
            "rerecognition_title_count": int(row["rerecognition_title_count"]),
            "validity_title_count": int(row["validity_title_count"]),
            "status": "needs_manual_rule_review",
        }
        for row in candidate_rows
        if (
            str(row["canonical_project_name"]) not in configured_names
            and normalize_name(str(row["canonical_project_name"]))
            not in configured_normalized_names
        )
    ]
    report = {
        "generated_at": generated_at,
        "schema_version": 1,
        "method": "已确认项目规则表与政策库标题级周期关键词交叉审计",
        "confirmed_projects": confirmed,
        "connected_event_sources": lifecycle_source_audits,
        "candidate_projects": candidates,
        "boundary": [
            "每年开展申报不等于单个企业资格具有生命周期。",
            "绩效评价、动态监测和财政支持不自动等同资格复核。",
            "候选项目只有在核对现行管理办法和正式名单后才可进入自动事件构建。",
        ],
    }
    (output / "企业项目生命周期政策库审计报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def write_outputs(
    database: Path,
    output: Path,
    events: dict[EventKey, dict[str, Any]],
    tyc: dict[str, dict[str, Any]],
    lifecycle_rules: dict[str, dict[str, Any]],
    lifecycle_sources: list[dict[str, Any]],
    regional_coverage_rules: list[dict[str, Any]],
    lifecycle_source_audits: list[dict[str, Any]],
    regional_coverage_audits: list[dict[str, Any]],
    regional_coverage_matrix: dict[str, Any],
    policy_version_database: Path | None,
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
                "project_lifecycles": [],
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
    event_rows = merge_identity_event_rows(event_rows)
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
                "project_lifecycles": [],
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
    lifecycle_summaries: dict[tuple[str, str], dict[str, Any]] = {}
    for row in event_rows:
        if not row["lifecycle_rule_id"]:
            continue
        key = (str(row["identity_key"]), str(row["project_name"]))
        summary = lifecycle_summaries.setdefault(
            key,
            {
                "project_name": str(row["project_name"]),
                "lifecycle_rule_id": str(row["lifecycle_rule_id"]),
                "cycle_type": str(row["cycle_type"]),
                "validity_years": row["validity_years"],
                "event_count": 0,
                "latest_known_event_year": None,
                "latest_known_event_type": "",
                "latest_known_status": "",
                "latest_known_cohort_year": None,
            },
        )
        summary["event_count"] += 1
        candidate = (
            int(row["event_year"] or 0),
            EVENT_TYPE_PRECEDENCE.get(str(row["event_type"]), 0),
        )
        current = (
            int(summary["latest_known_event_year"] or 0),
            EVENT_TYPE_PRECEDENCE.get(str(summary["latest_known_event_type"]), 0),
        )
        if candidate >= current:
            summary["latest_known_event_year"] = row["event_year"]
            summary["latest_known_event_type"] = str(row["event_type"])
            summary["latest_known_status"] = str(row["status"])
            summary["latest_known_cohort_year"] = row["cohort_year"]
    for (identity_key, _), summary in lifecycle_summaries.items():
        profiles[identity_key]["project_lifecycles"].append(summary)

    profile_rows: list[dict[str, Any]] = []
    for item in profiles.values():
        profile_rows.append(
            {
                **item,
                "recognition_names": sorted(item["recognition_names"]),
                "recognition_regions": sorted(item["recognition_regions"]),
                "recognition_projects": sorted(item["recognition_projects"]),
                "project_lifecycles": sorted(
                    item["project_lifecycles"],
                    key=lambda row: row["project_name"],
                ),
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
    project_twins, twin_steps = build_project_identity_twins(
        profile_rows,
        event_rows,
        lifecycle_rules,
        regional_coverage_matrix,
        policy_version_database,
    )

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
            "project_lifecycles",
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
                    "project_lifecycles": json.dumps(
                        item["project_lifecycles"],
                        ensure_ascii=False,
                    ),
                }
            )
    for filename, rows in (
        ("浙江省企业认定事件.jsonl", event_rows),
        ("浙江省企业名称历史.jsonl", alias_rows),
        ("浙江省企业身份档案.jsonl", profile_rows),
        ("浙江省企业项目身份数字孪生.jsonl", project_twins),
        ("浙江省企业项目身份回放步骤.jsonl", twin_steps),
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
        DROP TABLE IF EXISTS enterprise_project_identity_twins;
        DROP TABLE IF EXISTS enterprise_project_identity_twin_steps;
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
            recognition_projects_json TEXT NOT NULL,
            project_lifecycles_json TEXT NOT NULL
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
            event_year INTEGER,
            recognition_year INTEGER,
            cohort_year INTEGER,
            event_type TEXT NOT NULL,
            event_scope TEXT NOT NULL,
            evidence_status TEXT NOT NULL,
            lifecycle_rule_id TEXT NOT NULL DEFAULT '',
            cycle_type TEXT NOT NULL DEFAULT '',
            validity_years INTEGER,
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
            UNIQUE(identity_key,project_name,event_year,batch,status,event_type)
        );
        CREATE TABLE enterprise_project_identity_twins(
            twin_id TEXT PRIMARY KEY,
            identity_key TEXT NOT NULL,
            project_name TEXT NOT NULL,
            lifecycle_rule_id TEXT NOT NULL,
            policy_version_id TEXT NOT NULL,
            current_state TEXT NOT NULL,
            current_as_of_year INTEGER,
            trace_hash TEXT NOT NULL,
            identity_match_json TEXT NOT NULL,
            policy_version_json TEXT NOT NULL,
            list_attachment_trace_json TEXT NOT NULL,
            coverage_trace_json TEXT NOT NULL,
            lifecycle_trace_json TEXT NOT NULL,
            replayable_years_json TEXT NOT NULL,
            UNIQUE(identity_key,project_name)
        );
        CREATE TABLE enterprise_project_identity_twin_steps(
            id INTEGER PRIMARY KEY,
            twin_id TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            project_name TEXT NOT NULL,
            step INTEGER NOT NULL,
            event_year INTEGER,
            event_type TEXT NOT NULL,
            previous_state TEXT NOT NULL,
            next_state TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            UNIQUE(twin_id,step)
        );
        CREATE INDEX enterprise_identity_name_lookup_idx
        ON enterprise_identity_names(normalized_alias);
        CREATE INDEX enterprise_recognition_lookup_idx
        ON enterprise_recognition_events(normalized_name,project_name,recognition_year);
        CREATE INDEX enterprise_project_twin_lookup_idx
        ON enterprise_project_identity_twins(identity_key,project_name);
        CREATE INDEX enterprise_project_twin_step_lookup_idx
        ON enterprise_project_identity_twin_steps(twin_id,event_year,event_type);
        """
    )
    connection.executemany(
        """
        INSERT INTO enterprise_identity_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                json.dumps(row["project_lifecycles"], ensure_ascii=False),
            )
            for row in profile_rows
        ],
    )
    connection.executemany(
        """
        INSERT INTO enterprise_project_identity_twins VALUES(
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        """,
        [
            (
                row["twin_id"],
                row["identity_key"],
                row["project_name"],
                row["lifecycle_rule_id"],
                row["policy_version"]["policy_version_id"],
                row["current_replay"]["state"],
                row["current_replay"]["as_of_year"],
                row["trace_hash"],
                json.dumps(row["identity_match"], ensure_ascii=False),
                json.dumps(row["policy_version"], ensure_ascii=False),
                json.dumps(row["list_attachment_trace"], ensure_ascii=False),
                json.dumps(row["coverage_trace"], ensure_ascii=False),
                json.dumps(row["lifecycle_trace"], ensure_ascii=False),
                json.dumps(row["replayable_years"], ensure_ascii=False),
            )
            for row in project_twins
        ],
    )
    connection.executemany(
        """
        INSERT INTO enterprise_project_identity_twin_steps(
            twin_id,identity_key,project_name,step,event_year,event_type,
            previous_state,next_state,reason,evidence_hash,payload_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                row["twin_id"],
                row["identity_key"],
                row["project_name"],
                row["step"],
                row["event_year"],
                row["event_type"],
                row["previous_state"],
                row["next_state"],
                row["reason"],
                row["evidence_hash"],
                json.dumps(row, ensure_ascii=False),
            )
            for row in twin_steps
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
            event_year,recognition_year,cohort_year,event_type,event_scope,evidence_status,
            lifecycle_rule_id,cycle_type,validity_years,batch,status,recognition_province,
            recognition_city,recognition_county,source_title,source_paths_json,
            source_urls_json,sequence_numbers_json,source_kinds_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                row["identity_key"],
                row["enterprise_name_at_event"],
                row["normalized_name"],
                row["project_name"],
                row["event_year"],
                row["recognition_year"],
                row["cohort_year"],
                row["event_type"],
                row["event_scope"],
                row["evidence_status"],
                row["lifecycle_rule_id"],
                row["cycle_type"],
                row["validity_years"],
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
    policy_lifecycle_audit = write_policy_lifecycle_audit(
        database,
        output,
        lifecycle_rules,
        lifecycle_source_audits,
        generated_at,
    )
    report = {
        "generated_at": generated_at,
        "schema_version": 3,
        "scope": "浙江省企业身份、认定项目与资格生命周期",
        "enterprise_profiles": len(profile_rows),
        "recognition_events": len(event_rows),
        "lifecycle_events": sum(bool(row["lifecycle_rule_id"]) for row in event_rows),
        "lifecycle_projects": len(lifecycle_rules),
        "enterprise_project_identity_twins": len(project_twins),
        "enterprise_project_identity_twin_steps": len(twin_steps),
        "policy_version_database": str(policy_version_database or ""),
        "lifecycle_source_audits": lifecycle_source_audits,
        "regional_coverage_audits": regional_coverage_audits,
        "regional_coverage_complete": all(
            bool(item["complete"]) for item in regional_coverage_audits
        ),
        "regional_coverage_matrix_groups": len(
            regional_coverage_matrix["groups"]
        ),
        "regional_coverage_matrix_complete_groups": sum(
            bool(item["complete"])
            for item in regional_coverage_matrix["groups"]
        ),
        "regional_coverage_matrix_incomplete_groups": sum(
            not bool(item["complete"])
            for item in regional_coverage_matrix["groups"]
        ),
        "regional_coverage_matrix_complete": all(
            bool(item["complete"])
            for item in regional_coverage_matrix["groups"]
        ),
        "regional_coverage_hash_reused_cities": sum(
            row["coverage_state"] == "hash_reused"
            for row in regional_coverage_matrix["rows"]
        ),
        "regional_coverage_collection_queue": len(
            regional_coverage_matrix["collection_queue"]
        ),
        "policy_lifecycle_candidate_projects": len(
            policy_lifecycle_audit["candidate_projects"]
        ),
        "name_records": len(alias_rows),
        "tyc_verified_profiles": sum(row["verification_status"] == "tyc_verified" for row in profile_rows),
        "pending_business_identity": sum(
            row["verification_status"] == "pending_business_identity" for row in profile_rows
        ),
        "database_integrity": integrity,
        "rules": [
            "认定时名称、地区、年度、批次和状态来自名单侧，不被当前工商信息覆盖。",
            "当前名称、信用代码、当前地区和地址来自天眼查等企业身份源。",
            "首次认定、复核、重新认定、继续支持、变更和撤销分别建生命周期事件。",
            "高新技术企业到期按重新认定建档，不与监督复核混为一类。",
            "财政继续支持属于支持生命周期，不覆盖原资格认定批次。",
            "省级项目按设区市分别发布名单时，必须通过配置的全区域附件覆盖审计；严格覆盖组缺少任一地区即停止构建。",
            "发现任一省级项目分市附件后，自动登记项目、事件年度、批次、事件类型和11市覆盖矩阵；未闭环组不得形成全省完整结论。",
            "覆盖矩阵按附件内容哈希增量维护；哈希不变直接复用，仅缺失或变化来源进入采集队列。",
            "省级名单未提供城市时保留城市待核验，不通过企业名称猜测城市。",
            "统一社会信用代码缺失时使用规范名称临时键，禁止自动推算信用代码。",
            "同名、迁址、合并和重组冲突必须进入人工核验。",
            "企业项目身份数字孪生保留政策版本、名单附件、主体匹配和生命周期状态迁移，可按年份回放。",
        ],
    }
    (output / "浙江省企业身份时间轴构建报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "企业项目生命周期规则.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "schema_version": 2,
                "projects": sorted(
                    lifecycle_rules.values(),
                    key=lambda row: str(row["project_name"]),
                ),
                "regional_coverage_rules": regional_coverage_rules,
                "local_event_sources": lifecycle_sources,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "省级项目设区市名单覆盖审计.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "schema_version": 1,
                "coverage_groups": regional_coverage_audits,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report


def main() -> None:
    args = parse_args()
    ensure_tyc_template(args.tyc_enrichment)
    (
        lifecycle_rules,
        lifecycle_sources,
        regional_coverage_rules,
        lifecycle_aliases,
        regional_coverage_discovery,
    ) = load_lifecycle_config(args.lifecycle_rules)
    events: dict[EventKey, dict[str, Any]] = {}
    exclusions, lifecycle_source_audits = load_manifest_lifecycle_events(
        args.database,
        lifecycle_sources,
        lifecycle_rules,
        events,
    )
    regional_coverage_audits = audit_regional_source_coverage(
        regional_coverage_rules,
        lifecycle_source_audits,
    )
    discovered_coverage_sources = discover_regional_coverage_sources(
        args.database,
        lifecycle_rules,
        lifecycle_aliases,
    )
    regional_coverage_matrix = build_regional_coverage_matrix(
        args.output,
        lifecycle_rules,
        regional_coverage_rules,
        lifecycle_source_audits,
        discovered_coverage_sources,
        regional_coverage_discovery,
    )
    load_small_giant_events(args.small_giant_master, events, lifecycle_rules)
    load_list_events(
        args.database,
        events,
        lifecycle_rules,
        lifecycle_aliases,
        exclusions,
    )
    load_three_first_events(args.three_first, events, lifecycle_rules)
    report = write_outputs(
        args.database,
        args.output,
        events,
        load_tyc_enrichment(args.tyc_enrichment),
        lifecycle_rules,
        lifecycle_sources,
        regional_coverage_rules,
        lifecycle_source_audits,
        regional_coverage_audits,
        regional_coverage_matrix,
        args.policy_version_database,
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_DB = Path("/Volumes/知识库/_云端迁移索引/cloud_package_index/knowledge_content.sqlite3")
DEFAULT_OUTPUT = Path("/Volumes/知识库/_云端知识库/50_名单与对标/优质中小企业梯度培育/_覆盖矩阵")
PROVINCES = (
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省", "黑龙江省",
    "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省", "河南省",
    "湖北省", "湖南省", "广东省", "广西壮族自治区", "海南省", "重庆市", "四川省", "贵州省",
    "云南省", "西藏自治区", "陕西省", "甘肃省", "青海省", "宁夏回族自治区", "新疆维吾尔自治区",
    "新疆生产建设兵团",
)
REGION_ALIASES = {
    "内蒙古": "内蒙古自治区",
    "广西": "广西壮族自治区",
    "西藏": "西藏自治区",
    "宁夏": "宁夏回族自治区",
    "新疆生产建设兵团": "新疆生产建设兵团",
    "兵团": "新疆生产建设兵团",
    "新疆": "新疆维吾尔自治区",
}
MUNICIPAL_TERMS = (
    "杭州市", "宁波市", "温州市", "嘉兴市", "湖州市", "绍兴市", "金华市", "衢州市", "舟山市", "台州市", "丽水市",
    "南京市", "苏州市", "无锡市", "常州市", "南通市", "扬州市", "镇江市", "泰州市", "盐城市", "淮安市", "宿迁市", "徐州市", "连云港市",
    "长春市", "吉林市", "南宁市", "柳州市", "桂林市", "西安市", "兰州市", "银川市", "乌鲁木齐市",
)
YEARS = tuple(range(2022, datetime.now().year))
BATCH_YEARS = {"第一批": 2019, "第二批": 2020, "第三批": 2021, "第四批": 2022, "第五批": 2023, "第六批": 2024, "第七批": 2025, "第八批": 2026}
EVIDENCE_PRIORITY = {
    "final": 0,
    "final_review": 1,
    "public_or_recommended": 2,
    "application_notice": 3,
    "unknown": 4,
    "revocation_or_failure": 5,
}


@dataclass(frozen=True)
class Evidence:
    document_id: int
    title: str
    source: str
    region: str
    year: int | None
    project_scope: str
    administrative_level: str
    evidence_type: str
    confidence: str
    entity_count: int
    exclusion_reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立32地区省级专精特新与国家小巨人年度覆盖矩阵")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("（", "(").replace("）", ")"))


def normalize_enterprise_name(value: str) -> str:
    return re.sub(r"[\s·•・,，。;；:：()（）【】\\[\\]\"“”'‘’]+", "", value).lower()


def infer_region(title: str, source: str, content: str, stored_region: str) -> tuple[str, str]:
    explicit = f"{title}\n{source}"
    for province in PROVINCES:
        if province in explicit:
            return province, "high"
    for alias, province in REGION_ALIASES.items():
        if alias in explicit:
            return province, "medium"
    for province in PROVINCES:
        if province in stored_region:
            return province, "medium"
    fallback = content[:3000]
    for province in PROVINCES:
        if province in fallback:
            return province, "low"
    for alias, province in REGION_ALIASES.items():
        if alias in fallback:
            return province, "low"
    return "", "low"


def infer_scope(title: str, content: str, canonical: str) -> tuple[str, str]:
    value = normalize_text(f"{title}\n{content[:4000]}\n{canonical}")
    title_value = normalize_text(title)
    if any(term in value for term in ("科技小巨人", "创新小巨人", "成长小巨人", "小巨人培育企业", "小巨人(培育)")):
        return "local_technology_giant", "地方科技或成长型小巨人，不属于国家专精特新小巨人"
    if any(
        term in title_value
        for term in ("产业园", "园区名单", "服务平台名单", "特色产业集群")
    ):
        return "park_or_platform", "园区、平台或集群名单"
    if "重点小巨人" in value or "重点“小巨人”" in value:
        return "supported_key_small_giant", "财政支持的重点小巨人，不是新认定名单"
    if "专精特新中小企业" in title_value and "小巨人" not in title_value:
        return "provincial_specialized_sme", ""
    if "专精特新" in value and "小巨人" in value:
        if (
            any(term in value for term in ("市级专精特新", "省级专精特新小巨人", "自治区级专精特新小巨人", "省级第三批专精特新小巨人", "地方专精特新小巨人"))
            or ("省级" in title_value and "国家级" not in title_value)
            or ("拟认定" in title_value and any(region in title_value for region in PROVINCES))
        ):
            return "legacy_local_small_giant", "地方旧称号，不与国家小巨人混算"
        if re.search(r"第[一二三四五六七八]批", value) or "国家级" in value or "国家专精特新" in value or canonical == "国家专精特新“小巨人”企业":
            return "national_small_giant", ""
    if "专精特新" in value and "中小企业" in value:
        return "provincial_specialized_sme", ""
    return "other", "未识别为目标名单"


def infer_level(title: str, source: str, content: str, scope: str) -> str:
    if scope == "national_small_giant":
        return "国家级"
    value = f"{title}\n{source}\n{content[:2200]}"
    header = normalize_text(f"{title}\n{source}\n{content[:700]}")
    if any(term in header for term in ("省级", "自治区", "全省", "省专精特新")):
        return "省级"
    if any(term in title for term in ("区级", "县级")):
        return "区县级"
    if "市级" in title or any(term in title for term in MUNICIPAL_TERMS):
        return "市级"
    if scope == "provincial_specialized_sme" and any(region in value for region in PROVINCES):
        return "省级"
    return "待确认"


def infer_year(title: str, source: str, content: str, stored_year: int | None, batch: str, scope: str) -> int | None:
    if stored_year:
        return int(stored_year)
    if scope == "national_small_giant" and batch in BATCH_YEARS:
        return BATCH_YEARS[batch]
    for value in (title, source, content[:1000]):
        years = [int(year) for year in re.findall(r"20(?:1[9]|2[0-9])", value)]
        if years:
            return min(years) if "复核" in title and len(set(years)) > 1 else max(years)
    return None


def infer_evidence_type(title: str, content: str, stage: str) -> str:
    title_value = normalize_text(title)
    stage_value = normalize_text(stage)
    value = normalize_text(f"{title}\n{content[:1800]}\n{stage}")
    public_title = any(term in title_value for term in ("拟认定", "拟通过", "推荐名单", "公示名单", "名单公示"))
    explicit_match = re.search(r"证据类型[:：](final_review|historical_final_attachment|final|public|application_notice)", content[:1200], flags=re.I)
    if explicit_match:
        explicit = explicit_match.group(1).lower()
        if explicit == "final_review":
            return "final_review"
        if explicit in {"historical_final_attachment", "final"}:
            return "final"
        if explicit == "public":
            return "public_or_recommended"
        if explicit == "application_notice":
            return "application_notice"
    if "通过复核" in value and any(term in value for term in ("取消认定", "取消", "撤销", "未通过")):
        return "final_review"
    if any(term in value for term in ("取消认定", "撤销", "不予通过", "未通过")):
        return "revocation_or_failure"
    if "复核通过" in title_value:
        return "public_or_recommended" if public_title else "final_review"
    if any(term in title_value for term in ("关于公布", "认定名单", "通过名单", "正式名单")) and not public_title:
        return "final"
    if "认定名单" in stage_value and not public_title:
        return "final"
    if public_title or "公示" in stage_value:
        return "public_or_recommended"
    if "复核通过" in value:
        return "final_review"
    if any(term in value for term in ("拟认定", "拟通过", "推荐名单", "公示名单")):
        return "public_or_recommended"
    if any(term in value for term in ("关于公布", "认定名单", "通过名单", "正式名单")):
        return "final"
    if "申报" in value and "通知" in value:
        return "application_notice"
    return "unknown"


def infer_mixed_year_roles(title: str, content: str) -> dict[int, str]:
    value = normalize_text(f"{title}\n{content}")
    title_value = normalize_text(title)
    recognition_match = re.search(r"(20\d{2})年(?:(?!20\d{2}年).){0,80}(?:新认定|认定)", value)
    review_match = re.search(r"(20\d{2})年(?:(?!20\d{2}年).){0,80}复核", value)
    roles: dict[int, str] = {}
    if recognition_match:
        roles[int(recognition_match.group(1))] = (
            "public_or_recommended" if "拟认定" in title_value else "final"
        )
    if review_match:
        roles[int(review_match.group(1))] = (
            "public_or_recommended" if "拟复核" in title_value else "final_review"
        )
    return roles if len(roles) > 1 else {}


def load_evidence(connection: sqlite3.Connection) -> list[Evidence]:
    rows = connection.execute(
        """
        SELECT d.id,d.title,d.source,d.content,d.sha256,d.canonical_project_name,d.region,
               d.document_stage,d.policy_year,d.batch,COUNT(e.id),
               SUM(CASE WHEN e.context LIKE '%复核%' THEN 1 ELSE 0 END)
        FROM documents d
        LEFT JOIN public_list_entities e ON e.document_id=d.id
        WHERE d.document_role='50_名单与对标'
          AND d.title<>'source_record.json'
          AND d.source NOT LIKE '%/_全国小巨人批次主表/%'
          AND d.source NOT LIKE '%/_覆盖矩阵/%'
          AND (d.title LIKE '%专精特新%' OR d.content LIKE '%专精特新%')
          AND NOT EXISTS (
              SELECT 1 FROM document_duplicates duplicate_filter
              WHERE duplicate_filter.document_id=d.id
                AND duplicate_filter.canonical_document_id<>d.id
                AND NOT (d.title LIKE '%认定%' AND d.title LIKE '%复核%')
                AND d.source NOT LIKE '%正式认定_%'
                AND d.source NOT LIKE '%复核通过_%'
                AND d.source NOT LIKE '%公示过程_%'
                AND d.source NOT LIKE '%企业更名_%'
                AND d.source NOT LIKE '%取消或未通过_%'
          )
        GROUP BY d.id
        """
    ).fetchall()
    evidence: list[Evidence] = []
    entity_fingerprints: dict[int, frozenset[str]] = {}
    document_ids = [int(row[0]) for row in rows]
    for offset in range(0, len(document_ids), 800):
        chunk = document_ids[offset:offset + 800]
        placeholders = ",".join("?" for _ in chunk)
        for document_id, enterprise_name in connection.execute(
            f"""
            SELECT document_id,enterprise_name
            FROM public_list_entities
            WHERE document_id IN ({placeholders})
            """,
            chunk,
        ).fetchall():
            entity_fingerprints.setdefault(int(document_id), set()).add(
                normalize_enterprise_name(str(enterprise_name))
            )
    entity_fingerprints = {
        document_id: frozenset(name for name in names if name)
        for document_id, names in entity_fingerprints.items()
    }
    mixed_sha256 = {
        str(row[4])
        for row in rows
        if infer_mixed_year_roles(str(row[1]), str(row[3]))
    }
    mixed_signatures_seen: set[
        tuple[tuple[tuple[int, str], ...], frozenset[str]]
    ] = set()
    for (
        document_id,
        title,
        source,
        content,
        sha256,
        canonical,
        stored_region,
        stage,
        stored_year,
        batch,
        entity_count,
        review_entity_count,
    ) in rows:
        scope, exclusion = infer_scope(str(title), str(content), str(canonical))
        region, region_confidence = infer_region(str(title), str(source), str(content), str(stored_region))
        level = infer_level(str(title), str(source), str(content), scope)
        confidence = "high" if region_confidence == "high" and level != "待确认" else "medium" if region else "low"
        mixed_year_roles = infer_mixed_year_roles(str(title), str(content))
        if str(sha256) in mixed_sha256 and not mixed_year_roles:
            continue
        if scope == "provincial_specialized_sme" and mixed_year_roles:
            signature = (
                tuple(sorted(mixed_year_roles.items())),
                entity_fingerprints.get(int(document_id), frozenset()),
            )
            if signature in mixed_signatures_seen:
                continue
            mixed_signatures_seen.add(signature)
            review_count = int(review_entity_count or 0)
            total_count = int(entity_count or 0)
            for mixed_year, mixed_evidence_type in mixed_year_roles.items():
                mixed_entity_count = review_count if mixed_evidence_type == "final_review" else max(total_count - review_count, 0)
                evidence.append(
                    Evidence(
                        document_id=int(document_id),
                        title=str(title),
                        source=str(source),
                        region=region,
                        year=mixed_year,
                        project_scope=scope,
                        administrative_level=level,
                        evidence_type=mixed_evidence_type,
                        confidence=confidence,
                        entity_count=mixed_entity_count,
                        exclusion_reason=exclusion,
                    )
                )
            continue
        evidence.append(
            Evidence(
                document_id=int(document_id),
                title=str(title),
                source=str(source),
                region=region,
                year=infer_year(str(title), str(source), str(content), stored_year, str(batch), scope),
                project_scope=scope,
                administrative_level=level,
                evidence_type=infer_evidence_type(str(title), str(content), str(stage)),
                confidence=confidence,
                entity_count=int(entity_count),
                exclusion_reason=exclusion,
            )
        )
    return evidence


def matrix_status(items: list[Evidence], final_entity_rows: int = 0) -> str:
    types = {item.evidence_type for item in items}
    if types & {"final", "final_review"}:
        return "verified_final" if final_entity_rows > 0 else "final_source_needs_extraction"
    if "public_or_recommended" in types:
        return "public_only"
    if "application_notice" in types:
        return "notice_only"
    if items:
        return "source_present_unverified"
    return "missing"


def load_entities(
    connection: sqlite3.Connection,
    evidence: Iterable[Evidence],
) -> dict[tuple[int, int | None], dict[str, str]]:
    evidence_items = list(evidence)
    identifiers = sorted({item.document_id for item in evidence_items})
    if not identifiers:
        return {}
    years_by_document: dict[int, list[Evidence]] = defaultdict(list)
    for item in evidence_items:
        years_by_document[item.document_id].append(item)
    result: dict[tuple[int, int | None], dict[str, str]] = defaultdict(dict)
    document_contents = {
        int(document_id): str(content)
        for document_id, content in connection.execute(
            f"SELECT id,content FROM documents WHERE id IN ({','.join('?' for _ in identifiers)})",
            identifiers,
        ).fetchall()
    }
    passed_review_max_sequence: dict[int, int] = {}
    for document_id, content in document_contents.items():
        passed_headings = list(re.finditer(r"通过复核[^\\n]{0,100}名单", content))
        cancelled_headings = list(re.finditer(r"取消[^\\n]{0,100}(?:称号)?[^\\n]{0,40}名单", content))
        if not passed_headings or not cancelled_headings:
            continue
        cancelled_start = cancelled_headings[-1].start()
        passed_start = next(
            (match.start() for match in reversed(passed_headings) if match.start() < cancelled_start),
            None,
        )
        if passed_start is not None:
            sequences = [
                int(line.strip())
                for line in content[passed_start:cancelled_start].splitlines()
                if line.strip().isdigit()
            ]
            if sequences:
                passed_review_max_sequence[document_id] = max(sequences)
    for offset in range(0, len(identifiers), 800):
        chunk = identifiers[offset:offset + 800]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            f"""
            SELECT id,document_id,enterprise_name,sequence_no,context
            FROM public_list_entities
            WHERE document_id IN ({placeholders})
            ORDER BY id
            """,
            chunk,
        ).fetchall()
        first_review_name_by_sequence: dict[tuple[int, int], str] = {}
        for _, document_id, enterprise_name, sequence_no, _ in rows:
            maximum = passed_review_max_sequence.get(int(document_id))
            if maximum is None or not str(sequence_no).isdigit():
                continue
            sequence = int(sequence_no)
            if 1 <= sequence <= maximum:
                first_review_name_by_sequence.setdefault(
                    (int(document_id), sequence),
                    normalize_enterprise_name(str(enterprise_name)),
                )
        allowed_review_names_by_document: dict[int, set[str]] = defaultdict(set)
        for (document_id, _), normalized_name in first_review_name_by_sequence.items():
            allowed_review_names_by_document[document_id].add(normalized_name)
        for _, document_id, enterprise_name, sequence_no, context in rows:
            normalized = normalize_enterprise_name(str(enterprise_name))
            if not normalized:
                continue
            document_items = years_by_document[int(document_id)]
            document_years = {item.year for item in document_items if item.year is not None}
            target_year: int | None = None
            if len(document_years) > 1:
                context_value = normalize_text(str(context))
                target_type = "final_review" if "复核" in context_value else "final"
                target_year = next(
                    (item.year for item in document_items if item.evidence_type == target_type),
                    None,
                )
            elif document_years:
                target_year = next(iter(document_years))
            target_item = next(
                (item for item in document_items if item.year == target_year),
                document_items[0],
            )
            if (
                int(document_id) in passed_review_max_sequence
                and target_item.evidence_type == "final_review"
                and normalized not in allowed_review_names_by_document[int(document_id)]
            ):
                continue
            result[(int(document_id), target_year)].setdefault(normalized, str(enterprise_name).strip())
    return result


def evidence_entities(
    items: Iterable[Evidence],
    entities: dict[tuple[int, int | None] | int, dict[str, str]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        document_entities = entities.get((item.document_id, item.year), entities.get(item.document_id, {}))
        for normalized, display_name in document_entities.items():
            result.setdefault(normalized, display_name)
    return result


def canonical_evidence(items: list[Evidence]) -> Evidence | None:
    if not items:
        return None
    return sorted(
        items,
        key=lambda item: (
            EVIDENCE_PRIORITY.get(item.evidence_type, 99),
            0 if item.confidence == "high" else 1,
            -item.entity_count,
            item.document_id,
        ),
    )[0]


def build_reconciliation(
    grouped: dict[tuple[str, int, str], list[Evidence]],
    entities: dict[tuple[int, int | None] | int, dict[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (region, year, project_scope), items in grouped.items():
        if project_scope != "provincial_specialized_sme":
            continue
        final_items = [item for item in items if item.evidence_type in {"final", "final_review"}]
        public_items = [item for item in items if item.evidence_type == "public_or_recommended"]
        final_entities = evidence_entities(final_items, entities)
        public_entities = evidence_entities(public_items, entities)
        if not final_entities and not public_entities:
            continue
        final_document_ids = ",".join(str(item.document_id) for item in final_items)
        public_document_ids = ",".join(str(item.document_id) for item in public_items)
        final_sources = "\n".join(dict.fromkeys(item.source for item in final_items if item.source))
        public_sources = "\n".join(dict.fromkeys(item.source for item in public_items if item.source))
        for normalized in sorted(set(final_entities) | set(public_entities)):
            in_final = normalized in final_entities
            in_public = normalized in public_entities
            if in_final and in_public:
                status = "recognized_final"
                resolution_reason = "企业同时出现在公示名单和最终认定名单中，以最终认定为有效依据"
            elif in_final:
                status = "final_only"
                resolution_reason = "企业出现在最终认定或复核通过名单中，以最终认定为有效依据"
            elif final_entities:
                status = "not_in_final_recognition"
                resolution_reason = "企业仅见于公示或拟认定名单，最终认定名单未见，不计入有效认定"
            else:
                status = "public_only_unresolved"
                resolution_reason = "当前仅有公示或拟认定名单，尚缺最终认定名单，暂不判定有效认定"
            rows.append(
                {
                    "region": region,
                    "year": year,
                    "project_scope": project_scope,
                    "enterprise_name": final_entities.get(normalized) or public_entities[normalized],
                    "normalized_enterprise_name": normalized,
                    "result_status": status,
                    "effective_recognition": int(status in {"recognized_final", "final_only"}),
                    "resolution_reason": resolution_reason,
                    "final_document_ids": final_document_ids,
                    "public_document_ids": public_document_ids,
                    "final_sources": final_sources,
                    "public_sources": public_sources,
                    "rule_version": "final-recognition-first-v1",
                }
            )
    return rows


def create_tables(
    connection: sqlite3.Connection,
    evidence: list[Evidence],
    matrix: list[dict[str, object]],
    reconciliation: list[dict[str, object]],
) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS list_entity_reconciliation;
        DROP TABLE IF EXISTS canonical_list_sources;
        DROP TABLE IF EXISTS list_coverage_evidence;
        DROP TABLE IF EXISTS list_coverage_matrix;
        CREATE TABLE list_coverage_evidence(
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            region TEXT NOT NULL,
            year INTEGER,
            project_scope TEXT NOT NULL,
            administrative_level TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            confidence TEXT NOT NULL,
            entity_count INTEGER NOT NULL,
            exclusion_reason TEXT NOT NULL
        );
        CREATE INDEX list_coverage_evidence_lookup_idx ON list_coverage_evidence(project_scope,region,year,evidence_type);
        CREATE TABLE list_coverage_matrix(
            region TEXT NOT NULL,
            year INTEGER NOT NULL,
            project_scope TEXT NOT NULL,
            status TEXT NOT NULL,
            evidence_count INTEGER NOT NULL,
            final_count INTEGER NOT NULL,
            public_count INTEGER NOT NULL,
            entity_rows INTEGER NOT NULL,
            final_entity_rows INTEGER NOT NULL,
            public_entity_rows INTEGER NOT NULL,
            public_not_in_final_rows INTEGER NOT NULL,
            canonical_document_id INTEGER,
            canonical_evidence_type TEXT NOT NULL,
            PRIMARY KEY(region,year,project_scope)
        );
        CREATE TABLE canonical_list_sources(
            region TEXT NOT NULL,
            year INTEGER NOT NULL,
            project_scope TEXT NOT NULL,
            document_id INTEGER NOT NULL,
            evidence_type TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            PRIMARY KEY(region,year,project_scope)
        );
        CREATE TABLE list_entity_reconciliation(
            id INTEGER PRIMARY KEY,
            region TEXT NOT NULL,
            year INTEGER NOT NULL,
            project_scope TEXT NOT NULL,
            enterprise_name TEXT NOT NULL,
            normalized_enterprise_name TEXT NOT NULL,
            result_status TEXT NOT NULL,
            effective_recognition INTEGER NOT NULL,
            resolution_reason TEXT NOT NULL,
            final_document_ids TEXT NOT NULL,
            public_document_ids TEXT NOT NULL,
            final_sources TEXT NOT NULL,
            public_sources TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            UNIQUE(region,year,project_scope,normalized_enterprise_name)
        );
        CREATE INDEX list_entity_reconciliation_lookup_idx
            ON list_entity_reconciliation(project_scope,region,year,result_status);
        """
    )
    connection.executemany(
        """INSERT INTO list_coverage_evidence(document_id,title,source,region,year,project_scope,administrative_level,evidence_type,confidence,entity_count,exclusion_reason)
           VALUES(:document_id,:title,:source,:region,:year,:project_scope,:administrative_level,:evidence_type,:confidence,:entity_count,:exclusion_reason)""",
        [asdict(item) for item in evidence],
    )
    connection.executemany(
        """INSERT INTO list_coverage_matrix(
               region,year,project_scope,status,evidence_count,final_count,public_count,entity_rows,
               final_entity_rows,public_entity_rows,public_not_in_final_rows,canonical_document_id,canonical_evidence_type
           )
           VALUES(
               :region,:year,:project_scope,:status,:evidence_count,:final_count,:public_count,:entity_rows,
               :final_entity_rows,:public_entity_rows,:public_not_in_final_rows,:canonical_document_id,:canonical_evidence_type
           )""",
        matrix,
    )
    connection.executemany(
        """INSERT INTO canonical_list_sources(region,year,project_scope,document_id,evidence_type,title,source,rule_version)
           VALUES(:region,:year,:project_scope,:document_id,:evidence_type,:title,:source,'final-recognition-first-v1')""",
        [
            {
                "region": row["region"],
                "year": row["year"],
                "project_scope": row["project_scope"],
                "document_id": row["canonical_document_id"],
                "evidence_type": row["canonical_evidence_type"],
                "title": row["canonical_title"],
                "source": row["canonical_source"],
            }
            for row in matrix
            if row["canonical_document_id"] is not None
        ],
    )
    connection.executemany(
        """INSERT INTO list_entity_reconciliation(
               region,year,project_scope,enterprise_name,normalized_enterprise_name,result_status,effective_recognition,resolution_reason,
               final_document_ids,public_document_ids,final_sources,public_sources,rule_version
           )
           VALUES(
               :region,:year,:project_scope,:enterprise_name,:normalized_enterprise_name,:result_status,:effective_recognition,:resolution_reason,
               :final_document_ids,:public_document_ids,:final_sources,:public_sources,:rule_version
           )""",
        reconciliation,
    )
    connection.commit()


def write_outputs(output: Path, evidence: list[Evidence], matrix: list[dict[str, object]]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with (output / "32地区年度覆盖矩阵.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(matrix[0]))
        writer.writeheader()
        writer.writerows(matrix)
    with (output / "名单证据明细.jsonl").open("w", encoding="utf-8") as handle:
        for item in evidence:
            handle.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
    summary = defaultdict(int)
    for row in matrix:
        summary[str(row["status"])] += 1
    lines = [
        "# 32地区专精特新与小巨人年度覆盖矩阵",
        "",
        f"更新时间：{datetime.now().astimezone().strftime('%Y年%m月%d日%H:%M:%S')}",
        "",
        "## 口径",
        "",
        "- 省级专精特新中小企业只计省级正式认定、复核、公示或官方无批次说明。",
        "- 国家专精特新小巨人按工信部批次记录，不把地方科技小巨人、市级小巨人、园区或重点支持名单混入。",
        "- 公示和推荐名单只记为过程证据，不冒充正式认定。",
        "- 同一地区、年度和项目同时存在公示与正式认定名单时，以正式认定及复核通过名单组成有效主表。",
        "- 公示有而正式认定无的企业标记为 not_in_final_recognition，视为未进入最终认定名单，不计入有效认定数量。",
        "- 未命中写为 missing，不据此断言该地区当年没有组织认定。",
        "",
        "## 汇总",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(summary.items()))
    lines.extend(["", "## 疑似缺口", ""])
    for row in matrix:
        if row["status"] in {
            "missing",
            "notice_only",
            "source_present_unverified",
            "public_only",
            "final_source_needs_extraction",
        }:
            lines.append(f"- {row['region']} {row['year']} {row['project_scope']}: {row['status']}")
    (output / "32地区年度覆盖矩阵.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(args.database)
    try:
        evidence = load_evidence(connection)
        entities = load_entities(connection, evidence)
        grouped: dict[tuple[str, int, str], list[Evidence]] = defaultdict(list)
        for item in evidence:
            if item.project_scope == "provincial_specialized_sme" and item.administrative_level == "省级" and item.region and item.year in YEARS:
                grouped[(item.region, int(item.year), item.project_scope)].append(item)
            if item.project_scope == "national_small_giant" and item.year and 2019 <= item.year <= 2026:
                for region in PROVINCES:
                    grouped[(region, int(item.year), item.project_scope)].append(item)
        matrix: list[dict[str, object]] = []
        for region in PROVINCES:
            for year in YEARS:
                items = grouped[(region, year, "provincial_specialized_sme")]
                final_entities = evidence_entities(
                    (item for item in items if item.evidence_type in {"final", "final_review"}),
                    entities,
                )
                public_entities = evidence_entities(
                    (item for item in items if item.evidence_type == "public_or_recommended"),
                    entities,
                )
                canonical = canonical_evidence(items)
                matrix.append({
                    "region": region,
                    "year": year,
                    "project_scope": "provincial_specialized_sme",
                    "status": matrix_status(items, len(final_entities)),
                    "evidence_count": len(items),
                    "final_count": sum(item.evidence_type in {"final", "final_review"} for item in items),
                    "public_count": sum(item.evidence_type == "public_or_recommended" for item in items),
                    "entity_rows": len(final_entities) if final_entities else len(public_entities),
                    "final_entity_rows": len(final_entities),
                    "public_entity_rows": len(public_entities),
                    "public_not_in_final_rows": len(set(public_entities) - set(final_entities)) if final_entities else 0,
                    "canonical_document_id": canonical.document_id if canonical else None,
                    "canonical_evidence_type": canonical.evidence_type if canonical else "",
                    "canonical_title": canonical.title if canonical else "",
                    "canonical_source": canonical.source if canonical else "",
                })
            for year in range(2019, 2027):
                items = grouped[(region, year, "national_small_giant")]
                final_entities = evidence_entities(
                    (item for item in items if item.evidence_type in {"final", "final_review"}),
                    entities,
                )
                public_entities = evidence_entities(
                    (item for item in items if item.evidence_type == "public_or_recommended"),
                    entities,
                )
                canonical = canonical_evidence(items)
                matrix.append({
                    "region": region,
                    "year": year,
                    "project_scope": "national_small_giant",
                    "status": matrix_status(items, len(final_entities)),
                    "evidence_count": len(items),
                    "final_count": sum(item.evidence_type in {"final", "final_review"} for item in items),
                    "public_count": sum(item.evidence_type == "public_or_recommended" for item in items),
                    "entity_rows": len(final_entities) if final_entities else len(public_entities),
                    "final_entity_rows": len(final_entities),
                    "public_entity_rows": len(public_entities),
                    "public_not_in_final_rows": len(set(public_entities) - set(final_entities)) if final_entities else 0,
                    "canonical_document_id": canonical.document_id if canonical else None,
                    "canonical_evidence_type": canonical.evidence_type if canonical else "",
                    "canonical_title": canonical.title if canonical else "",
                    "canonical_source": canonical.source if canonical else "",
                })
        reconciliation = build_reconciliation(grouped, entities)
        create_tables(connection, evidence, matrix, reconciliation)
    finally:
        connection.close()
    write_outputs(args.output, evidence, matrix)
    print(
        json.dumps(
            {
                "evidence": len(evidence),
                "matrix_rows": len(matrix),
                "reconciliation_rows": len(reconciliation),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from app.authoritative_list_facts import query_authoritative_list_facts


PROJECT_ALIASES = {
    "小巨人": ("national_small_giant", ""),
    "国家小巨人": ("national_small_giant", ""),
    "国家专精特新小巨人": ("national_small_giant", ""),
    "专精特新小巨人": ("national_small_giant", ""),
    "national_small_giant": ("national_small_giant", ""),
    "专精特新中小企业": ("provincial_specialized_sme", ""),
    "省级专精特新": ("provincial_specialized_sme", ""),
    "省专": ("provincial_specialized_sme", ""),
    "provincial_specialized_sme": ("provincial_specialized_sme", ""),
    "首台套": ("three_first", "浙江省制造业首台（套）装备"),
    "首台（套）装备": ("three_first", "浙江省制造业首台（套）装备"),
    "首版次": ("three_first", "浙江省首版次软件产品"),
    "首版次软件": ("three_first", "浙江省首版次软件产品"),
    "首批次": ("three_first", "浙江省首批次新材料"),
    "重点新材料首批次": ("three_first", "浙江省首批次新材料"),
    "数字化车间": ("unified", "数字化车间"),
    "智能工厂": ("unified", "智能工厂"),
    "未来工厂": ("unified", "未来工厂"),
    "单项冠军": ("unified", "单项冠军"),
    "隐形冠军": ("unified", "隐形冠军"),
    "绿色工厂": ("unified", "绿色工厂"),
    "企业研究院": ("unified", "企业研究院"),
    "技术中心": ("unified", "技术中心"),
    "浙江制造精品": ("unified", "浙江制造精品"),
    "品字标": ("unified", "品字标"),
    "工业新产品": ("unified", "工业新产品"),
}

REGION_ALIASES = {
    "北京": "北京市",
    "天津": "天津市",
    "上海": "上海市",
    "重庆": "重庆市",
    "浙江": "浙江省",
    "江苏": "江苏省",
    "安徽": "安徽省",
    "福建": "福建省",
    "江西": "江西省",
    "山东": "山东省",
    "河南": "河南省",
    "湖北": "湖北省",
    "湖南": "湖南省",
    "广东": "广东省",
    "海南": "海南省",
    "四川": "四川省",
    "贵州": "贵州省",
    "云南": "云南省",
    "陕西": "陕西省",
    "甘肃": "甘肃省",
    "青海": "青海省",
    "河北": "河北省",
    "山西": "山西省",
    "辽宁": "辽宁省",
    "吉林": "吉林省",
    "黑龙江": "黑龙江省",
    "杭州": "杭州市",
    "宁波": "宁波市",
}

SUBJECT_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "recognized-subject-taxonomy.json"
)


def _compact(value: object) -> str:
    return re.sub(r"[\s\"'“”‘’《》〈〉（）()·•]+", "", str(value or ""))


def _unique(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


@lru_cache(maxsize=1)
def load_subject_taxonomy() -> list[dict[str, object]]:
    payload = json.loads(SUBJECT_TAXONOMY_PATH.read_text(encoding="utf-8"))
    subjects = payload.get("subjects", []) if isinstance(payload, dict) else []
    return [dict(item) for item in subjects if isinstance(item, dict)]


def _project_terms_in_query(query: str) -> list[str]:
    ordered: list[tuple[int, str]] = []
    for alias in sorted(PROJECT_ALIASES, key=len, reverse=True):
        position = query.find(alias)
        if position >= 0:
            ordered.append((position, alias))
    selected: list[tuple[int, int, str]] = []
    for position, alias in sorted(ordered, key=lambda item: (item[0], -len(item[1]))):
        end = position + len(alias)
        if any(position >= start and end <= kept_end for start, kept_end, _ in selected):
            continue
        selected.append((position, end, alias))
    return [alias for _, _, alias in sorted(selected)]


def build_recognition_query_plan(
    query: str,
    *,
    projects: Sequence[object] = (),
    subject_terms: Sequence[object] = (),
    regions: Sequence[object] = (),
    years: Sequence[object] = (),
    status: str = "final_recognition",
) -> dict[str, object]:
    normalized_query = re.sub(r"\s+", "", query.strip())
    project_values = _unique(projects) or _project_terms_in_query(normalized_query)
    explicit_regions = _unique(regions)
    if not explicit_regions:
        segments = re.split(r"(?:以及|并且|和|与|及|、|，|,|；|;|/)", normalized_query)
        for segment in segments:
            matches = re.findall(r"[\u4e00-\u9fff]{2,8}(?:省|自治区|市|区|县)", segment)
            for raw_region in matches:
                region = re.sub(
                    r"^(?:请帮我|麻烦帮我|帮我|请|麻烦|查询|查找|查下|查一下|查|检索|搜索|列出|看看)+",
                    "",
                    raw_region,
                )
                if len(region) >= 3:
                    explicit_regions.append(region)
        explicit_regions = _unique(explicit_regions)
    if not explicit_regions:
        explicit_regions = _unique(
            canonical
            for alias, canonical in REGION_ALIASES.items()
            if alias in normalized_query
        )
    explicit_years = [
        int(value)
        for value in _unique(years)
        if str(value).isdigit() and 2000 <= int(value) <= 2100
    ]
    if not explicit_years:
        explicit_years = [
            int(value)
            for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", normalized_query)
        ]

    requested_subjects = _unique(subject_terms)
    taxonomy_matches: list[dict[str, object]] = []
    for subject in load_subject_taxonomy():
        searchable_terms = _unique(
            [
                subject.get("canonical_subject", ""),
                *subject.get("exact_terms", []),
                *subject.get("related_terms", []),
            ]
        )
        if any(
            term in normalized_query or term in requested_subjects
            for term in searchable_terms
        ):
            taxonomy_matches.append(subject)
    if not requested_subjects:
        requested_subjects = [
            str(subject.get("canonical_subject") or "")
            for subject in taxonomy_matches
            if str(subject.get("canonical_subject") or "")
        ]
    exact_terms = _unique(
        [
            *requested_subjects,
            *(
                term
                for subject in taxonomy_matches
                for term in subject.get("exact_terms", [])
            ),
        ]
    )
    related_terms = _unique(
        [
            term
            for subject in taxonomy_matches
            for term in subject.get("related_terms", [])
        ]
    )
    excluded_terms = _unique(
        [
            term
            for subject in taxonomy_matches
            for term in subject.get("excluded_terms", [])
        ]
    )

    condition_intent = any(
        term in normalized_query for term in ("条件", "要求", "门槛", "怎么申报", "如何申报")
    )
    feasibility_intent = any(
        term in normalized_query for term in ("能不能报", "能否申报", "是否符合", "可行性")
    )
    writing_intent = any(
        term in normalized_query
        for term in ("写申报书", "撰写申报书", "生成报告", "形成材料", "正式材料")
    )
    reverse_intent = any(
        term in normalized_query
        for term in ("有哪些", "列出", "查询", "查找", "谁报下来", "报下来", "谁入选", "名单", "企业")
    )
    intent = (
        "application_writing"
        if writing_intent
        else "project_feasibility"
        if feasibility_intent
        else "policy_retrieval"
        if condition_intent and not reverse_intent
        else "recognition_reverse_lookup"
    )
    clarification = ""
    if intent == "recognition_reverse_lookup" and not project_values:
        clarification = "请说明要回查的认定项目，例如小巨人、首台套或首版次。"
    elif intent == "recognition_reverse_lookup" and not exact_terms:
        clarification = "请说明需要反查的产品、行业或技术方向。"
    elif (
        intent == "recognition_reverse_lookup"
        and any(_compact(project) in {"首台套", "首台套装备", "首版次", "首版次软件", "首批次", "重点新材料首批次"} for project in project_values)
        and not explicit_regions
    ):
        clarification = "请说明要查询的省市范围；三首属于地方名单，未确认地区时不能声称完整。"

    return {
        "intent": intent,
        "projects": project_values,
        "subjects": requested_subjects,
        "exact_terms": exact_terms,
        "related_terms": related_terms,
        "excluded_terms": excluded_terms,
        "regions": explicit_regions,
        "years": list(dict.fromkeys(explicit_years)),
        "status": status.strip() or "final_recognition",
        "clarification": clarification,
    }


def resolve_projects(projects: Sequence[object]) -> list[tuple[str, str, str]]:
    resolved: list[tuple[str, str, str]] = []
    for raw_project in projects:
        display_name = str(raw_project).strip()
        compact = _compact(raw_project)
        if compact in {"三首", "三首项目", "three_first"}:
            for alias in ("首台套", "首版次", "首批次"):
                list_type, project_name = PROJECT_ALIASES[alias]
                resolved.append((list_type, project_name, alias))
            continue
        match = PROJECT_ALIASES.get(compact)
        if match is None:
            raise ValueError(f"暂不支持的认定项目：{display_name}")
        resolved.append((match[0], match[1], display_name))
    return list(dict.fromkeys(resolved))


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def _subject_candidates(
    connection: sqlite3.Connection,
    subject_terms: Sequence[str],
    limit: int,
) -> list[dict[str, object]]:
    if not subject_terms:
        return []
    candidates: list[dict[str, object]] = []
    seen: set[tuple[str, int, str]] = set()
    if _table_exists(connection, "enterprise_subject_evidence"):
        conditions: list[str] = []
        parameters: list[object] = []
        for term in subject_terms:
            escaped = term.replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                "(canonical_subject LIKE ? ESCAPE '\\' OR raw_subject LIKE ? ESCAPE '\\' "
                "OR evidence_excerpt LIKE ? ESCAPE '\\')"
            )
            parameters.extend((f"%{escaped}%", f"%{escaped}%", f"%{escaped}%"))
        rows = connection.execute(
            f"""
            SELECT enterprise_name,evidence_excerpt AS context,
                   COALESCE(source_document_id,0) AS document_id,
                   raw_subject AS title,source_url AS source
            FROM enterprise_subject_evidence
            WHERE {' OR '.join(conditions)}
            ORDER BY verification_status DESC,enterprise_name,evidence_id
            LIMIT ?
            """,
            [*parameters, limit],
        ).fetchall()
        for row in rows:
            item = dict(row)
            key = (
                str(item["enterprise_name"]),
                int(item["document_id"]),
                "recognition_subject_index",
            )
            if key in seen:
                continue
            seen.add(key)
            item["evidence_type"] = "recognition_subject_index"
            candidates.append(item)
    if _table_exists(connection, "enterprise_mentions") and _table_exists(connection, "documents"):
        conditions: list[str] = []
        parameters: list[object] = []
        for term in subject_terms:
            escaped = term.replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                "(em.enterprise_name LIKE ? ESCAPE '\\' OR em.context LIKE ? ESCAPE '\\' "
                "OR d.title LIKE ? ESCAPE '\\')"
            )
            parameters.extend((f"%{escaped}%", f"%{escaped}%", f"%{escaped}%"))
        rows = connection.execute(
            f"""
            SELECT em.enterprise_name,em.context,d.id AS document_id,d.title,d.source
            FROM enterprise_mentions em
            JOIN documents d ON d.id=em.document_id
            WHERE {' OR '.join(conditions)}
            ORDER BY d.id DESC,em.enterprise_name
            LIMIT ?
            """,
            [*parameters, limit],
        ).fetchall()
        for row in rows:
            item = dict(row)
            key = (str(item["enterprise_name"]), int(item["document_id"]), "enterprise_mention")
            if key in seen:
                continue
            seen.add(key)
            item["evidence_type"] = "enterprise_mention"
            candidates.append(item)
    if _table_exists(connection, "case_packs"):
        conditions = []
        parameters = []
        for term in subject_terms:
            escaped = term.replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                "(enterprise_name LIKE ? ESCAPE '\\' OR industry LIKE ? ESCAPE '\\' "
                "OR title LIKE ? ESCAPE '\\')"
            )
            parameters.extend((f"%{escaped}%", f"%{escaped}%", f"%{escaped}%"))
        rows = connection.execute(
            f"""
            SELECT enterprise_name,'' AS context,0 AS document_id,title,source_root AS source
            FROM case_packs
            WHERE enterprise_name<>'' AND ({' OR '.join(conditions)})
            ORDER BY year DESC,enterprise_name
            LIMIT ?
            """,
            [*parameters, limit],
        ).fetchall()
        for row in rows:
            item = dict(row)
            key = (str(item["enterprise_name"]), int(item["document_id"]), "case_pack")
            if key in seen:
                continue
            seen.add(key)
            item["evidence_type"] = "case_pack"
            candidates.append(item)
    return candidates[:limit]


def _indexed_recognition_discovery(
    connection: sqlite3.Connection,
    *,
    resolved_projects: Sequence[tuple[str, str, str]],
    subject_terms: Sequence[str],
    regions: Sequence[str],
    year: int | None,
    verified_only: bool,
    limit: int,
) -> dict[str, object]:
    conditions: list[str] = []
    parameters: list[object] = []
    project_conditions: list[str] = []
    for list_type, project_name, display_name in resolved_projects:
        if list_type == "national_small_giant":
            project_conditions.append("rr.project_id='national_small_giant'")
        elif list_type == "three_first":
            project_conditions.append("rr.project_name LIKE ? ESCAPE '\\'")
            parameters.append(f"%{project_name}%")
        else:
            project_conditions.append(
                "(rr.project_name LIKE ? ESCAPE '\\' OR rr.project_id LIKE ? ESCAPE '\\')"
            )
            parameters.extend((f"%{project_name}%", f"%{display_name}%"))
    conditions.append(f"({' OR '.join(project_conditions)})")

    subject_conditions: list[str] = []
    for term in subject_terms:
        escaped = term.replace("%", "\\%").replace("_", "\\_")
        subject_conditions.append(
            "(ese.canonical_subject LIKE ? ESCAPE '\\' OR ese.raw_subject LIKE ? ESCAPE '\\' "
            "OR ese.evidence_excerpt LIKE ? ESCAPE '\\')"
        )
        parameters.extend((f"%{escaped}%", f"%{escaped}%", f"%{escaped}%"))
    conditions.append(f"({' OR '.join(subject_conditions)})")
    if regions:
        region_conditions: list[str] = []
        for region in regions:
            escaped = region.replace("%", "\\%").replace("_", "\\_")
            region_conditions.append(
                "(rr.region LIKE ? ESCAPE '\\' OR rr.province LIKE ? ESCAPE '\\' "
                "OR rr.city LIKE ? ESCAPE '\\' OR rr.county LIKE ? ESCAPE '\\')"
            )
            parameters.extend((f"%{escaped}%",) * 4)
        conditions.append(f"({' OR '.join(region_conditions)})")
    if year is not None:
        conditions.append("rr.year=?")
        parameters.append(year)
    if verified_only:
        conditions.append(
            "rr.recognition_status NOT LIKE '%公示%' "
            "AND rr.recognition_status NOT LIKE '%拟认定%' "
            "AND rr.verification_status NOT LIKE '%pending%' "
            "AND rr.verification_status NOT LIKE '%candidate%' "
            "AND (rr.source_grade LIKE '%official%' "
            "OR rr.verification_status LIKE '%verified%' "
            "OR rr.verification_status LIKE '%official%' "
            "OR rr.recognition_status LIKE '%正式%' "
            "OR rr.source_table='three_first_project_awards')"
        )
    rows = connection.execute(
        f"""
        SELECT rr.*,ese.evidence_id,ese.canonical_subject,ese.raw_subject,
               ese.match_level,ese.evidence_type,ese.evidence_excerpt,
               ese.source_url AS evidence_source_url,
               ese.source_document_id AS evidence_document_id,
               ese.verification_status AS subject_verification_status
        FROM recognition_records rr
        JOIN enterprise_subject_evidence ese ON ese.enterprise_id=rr.enterprise_id
        WHERE {' AND '.join(conditions)}
        ORDER BY rr.year DESC,rr.project_name,rr.enterprise_name_at_recognition,ese.evidence_id
        LIMIT ?
        """,
        [*parameters, limit + 1],
    ).fetchall()
    verified_matches: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_row in rows[:limit]:
        row = dict(raw_row)
        fact_id = str(row["record_id"])
        if fact_id in seen:
            continue
        seen.add(fact_id)
        verified_matches.append(
            {
                "project": row["project_name"],
                "subject_term": row["canonical_subject"],
                "match_scope": "unified_recognition_index",
                "subject_evidence": {
                    "canonical_subject": row["canonical_subject"],
                    "raw_subject": row["raw_subject"],
                    "match_level": row["match_level"],
                    "evidence_type": row["evidence_type"],
                    "evidence_excerpt": row["evidence_excerpt"],
                    "source_url": row["evidence_source_url"],
                    "document_id": row["evidence_document_id"],
                    "verification_status": row["subject_verification_status"],
                },
                "recognition_fact": {
                    "fact_id": fact_id,
                    "list_type": row["project_id"],
                    "enterprise_name": row["enterprise_name_at_recognition"],
                    "project_name": row["project_name"],
                    "product_name": row["product_name"],
                    "product_category": row["product_category"],
                    "recognition_year": row["year"],
                    "batch": row["batch"],
                    "region": row["region"],
                    "status": row["recognition_status"],
                    "recognition_level": row["recognition_level"],
                    "source_title": row["source_title"],
                    "source_url": row["source_url"],
                    "source_tier": row["source_grade"],
                    "verification_status": row["verification_status"],
                },
            }
        )

    subject_candidates = _subject_candidates(connection, subject_terms, min(limit * 10, 500))
    verified_enterprises = {
        _compact(item["recognition_fact"]["enterprise_name"])
        for item in verified_matches
    }
    pending_candidates = [
        {
            "project": "、".join(item[2] for item in resolved_projects),
            "enterprise_name": candidate["enterprise_name"],
            "subject_evidence": candidate,
            "status": "subject_evidence_found_authority_not_confirmed",
        }
        for candidate in subject_candidates
        if _compact(candidate["enterprise_name"]) not in verified_enterprises
    ][:limit]
    return {
        "projects": [item[2] for item in resolved_projects],
        "subject_terms": list(subject_terms),
        "regions": list(regions),
        "year": year,
        "verified_only": verified_only,
        "verified_matches": verified_matches,
        "pending_candidates": pending_candidates,
        "coverage_ledger": {
            "requested": len(resolved_projects) * max(1, len(regions)) * len(subject_terms),
            "processed": [
                {
                    "project": item[2],
                    "regions": list(regions),
                    "subject_terms": list(subject_terms),
                }
                for item in resolved_projects
            ],
            "returned_verified": len(verified_matches),
            "verified_truncated": len(rows) > limit,
            "pending_truncated": len(subject_candidates) > len(pending_candidates),
            "is_complete": False,
            "reason": "统一索引已查询全部指定维度，但主题词和上游证据覆盖不代表全国穷尽。",
        },
        "warnings": [
            "统一索引只合并现有权威名单与主题证据，不提升原始证据等级。",
            "pending_candidates不得当作已认定企业；未命中不等于不存在。",
        ],
    }


def discover_recognized_enterprises(
    connection: sqlite3.Connection,
    *,
    projects: Sequence[object],
    subject_terms: Sequence[object],
    regions: Sequence[object] = (),
    year: int | None = None,
    verified_only: bool = True,
    limit: int = 50,
) -> dict[str, object]:
    resolved_projects = resolve_projects(projects)
    normalized_terms = _unique(subject_terms)
    normalized_regions = _unique(regions)
    if not resolved_projects:
        raise ValueError("至少需要一个认定项目")
    if not normalized_terms:
        raise ValueError("至少需要一个产品、行业或企业主题词")
    bounded_limit = max(1, min(int(limit), 200))
    if _table_exists(connection, "recognition_records") and _table_exists(
        connection, "enterprise_subject_evidence"
    ):
        return _indexed_recognition_discovery(
            connection,
            resolved_projects=resolved_projects,
            subject_terms=normalized_terms,
            regions=normalized_regions,
            year=year,
            verified_only=verified_only,
            limit=bounded_limit,
        )
    region_scopes = normalized_regions or [""]
    verified_matches: list[dict[str, object]] = []
    pending_candidates: list[dict[str, object]] = []
    seen_facts: set[str] = set()
    processed: list[dict[str, object]] = []

    for list_type, project_name, display_name in resolved_projects:
        if list_type == "three_first":
            for region in region_scopes:
                for subject_term in normalized_terms:
                    product_response = query_authoritative_list_facts(
                        connection,
                        list_type=list_type,
                        product_name=subject_term,
                        project_name=project_name,
                        year=year,
                        region=region,
                        verified_only=verified_only,
                        limit=bounded_limit,
                    )
                    industry_response = query_authoritative_list_facts(
                        connection,
                        list_type=list_type,
                        industry=subject_term,
                        project_name=project_name,
                        year=year,
                        region=region,
                        verified_only=verified_only,
                        limit=bounded_limit,
                    )
                    for match_scope, response in (
                        ("product", product_response),
                        ("industry", industry_response),
                    ):
                        for fact in response.get("results", []):
                            fact_id = str(fact.get("fact_id") or "")
                            if not fact_id or fact_id in seen_facts:
                                continue
                            seen_facts.add(fact_id)
                            verified_matches.append(
                                {
                                    "project": display_name,
                                    "subject_term": subject_term,
                                    "match_scope": match_scope,
                                    "subject_evidence": {
                                        "product_name": fact.get("product_name", ""),
                                        "industry": fact.get("industry", ""),
                                        "source_title": fact.get("source_title", ""),
                                        "source_url": fact.get("source_url", ""),
                                    },
                                    "recognition_fact": fact,
                                }
                            )
                    processed.append(
                        {
                            "project": display_name,
                            "region": region,
                            "subject_term": subject_term,
                            "product_total": product_response.get("total", 0),
                            "industry_total": industry_response.get("total", 0),
                        }
                    )
            continue

        subject_candidates = _subject_candidates(
            connection,
            normalized_terms,
            min(500, bounded_limit * 10),
        )
        for candidate in subject_candidates:
            authority_found = False
            for region in region_scopes:
                response = query_authoritative_list_facts(
                    connection,
                    list_type=list_type,
                    enterprise_name=str(candidate["enterprise_name"]),
                    year=year,
                    region=region,
                    verified_only=verified_only,
                    limit=bounded_limit,
                )
                for fact in response.get("results", []):
                    fact_id = str(fact.get("fact_id") or "")
                    if not fact_id or fact_id in seen_facts:
                        continue
                    authority_found = True
                    seen_facts.add(fact_id)
                    verified_matches.append(
                        {
                            "project": display_name,
                            "subject_term": next(
                                (
                                    term
                                    for term in normalized_terms
                                    if term in " ".join(
                                        str(candidate.get(key) or "")
                                        for key in ("enterprise_name", "context", "title")
                                    )
                                ),
                                normalized_terms[0],
                            ),
                            "match_scope": "knowledge_evidence_then_authority",
                            "subject_evidence": candidate,
                            "recognition_fact": fact,
                        }
                    )
            if not authority_found:
                pending_candidates.append(
                    {
                        "project": display_name,
                        "enterprise_name": candidate["enterprise_name"],
                        "subject_evidence": candidate,
                        "status": "subject_evidence_found_authority_not_confirmed",
                    }
                )
        processed.append(
            {
                "project": display_name,
                "regions": normalized_regions,
                "subject_candidates": len(subject_candidates),
            }
        )

    return {
        "projects": [item[2] for item in resolved_projects],
        "subject_terms": normalized_terms,
        "regions": normalized_regions,
        "year": year,
        "verified_only": verified_only,
        "verified_matches": verified_matches[:bounded_limit],
        "pending_candidates": pending_candidates[:bounded_limit],
        "coverage_ledger": {
            "requested": len(resolved_projects) * len(region_scopes) * len(normalized_terms),
            "processed": processed,
            "returned_verified": min(len(verified_matches), bounded_limit),
            "verified_truncated": len(verified_matches) > bounded_limit,
            "pending_truncated": len(pending_candidates) > bounded_limit,
            "is_complete": False,
            "reason": (
                "三首专表支持产品和行业字面反查；小巨人及省级专精特新需先由当前知识证据发现候选再回查权威名单。"
                "当前结果不代表全国所有企业或同义词穷尽。"
            ),
        },
        "warnings": [
            "同义词由调用方显式提供，服务端不把未命中推断为不存在。",
            "verified_matches同时保存产品或行业证据与权威认定事实；pending_candidates不得当作已认定企业。",
        ],
    }


def _recognition_fact_key(item: dict[str, object]) -> str:
    fact = item.get("recognition_fact")
    if not isinstance(fact, dict):
        return ""
    fact_id = str(fact.get("fact_id") or "")
    if fact_id:
        return fact_id
    return "|".join(
        str(fact.get(key) or "")
        for key in (
            "list_type",
            "enterprise_name",
            "project_name",
            "product_name",
            "recognition_year",
            "year",
            "batch",
            "source_url",
        )
    )


def _evidence_text(item: dict[str, object]) -> str:
    evidence = item.get("subject_evidence")
    if not isinstance(evidence, dict):
        return ""
    return " ".join(str(value or "") for value in evidence.values())


def _dedupe_matches(
    matches: Sequence[dict[str, object]],
    *,
    excluded_terms: Sequence[str] = (),
    excluded_keys: set[str] | None = None,
) -> list[dict[str, object]]:
    seen = set(excluded_keys or set())
    result: list[dict[str, object]] = []
    for item in matches:
        if any(term and term in _evidence_text(item) for term in excluded_terms):
            continue
        key = _recognition_fact_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_pending(
    candidates: Sequence[dict[str, object]],
    *,
    excluded_terms: Sequence[str] = (),
) -> list[dict[str, object]]:
    seen: set[str] = set()
    result: list[dict[str, object]] = []
    for item in candidates:
        if any(term and term in _evidence_text(item) for term in excluded_terms):
            continue
        key = "|".join(
            str(item.get(field) or "")
            for field in ("project", "enterprise_name", "status")
        )
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def recognition_search(
    connection: sqlite3.Connection,
    *,
    query: str,
    projects: Sequence[object] = (),
    subject_terms: Sequence[object] = (),
    regions: Sequence[object] = (),
    years: Sequence[object] = (),
    status: str = "final_recognition",
    limit: int = 50,
) -> dict[str, object]:
    """Build one deterministic plan and execute recognition reverse discovery.

    Policy questions, feasibility questions and writing requests are routed away
    instead of being silently treated as list discovery. Exact, related and
    pending evidence are kept separate so a broad industry hit cannot be
    presented as proof of a specific product.
    """

    plan = build_recognition_query_plan(
        query,
        projects=projects,
        subject_terms=subject_terms,
        regions=regions,
        years=years,
        status=status,
    )
    bounded_limit = max(1, min(int(limit), 200))
    route_by_intent = {
        "policy_retrieval": "policy_search",
        "project_feasibility": "enterprise_lifecycle_decision",
        "application_writing": "application-writing",
    }
    if plan["intent"] != "recognition_reverse_lookup":
        return {
            "query_plan": plan,
            "route_to": route_by_intent[str(plan["intent"])],
            "exact_results": [],
            "related_results": [],
            "pending_results": [],
            "coverage": {
                "requested": 0,
                "processed": 0,
                "is_complete": False,
                "reason": "该问题不是认定名单反向发现，未执行名单查询。",
            },
            "pagination": {"limit": bounded_limit, "returned": 0, "is_truncated": False},
            "warnings": ["已返回确定性路由，不把政策答疑或可行性判断误当作名单查询。"],
        }
    if plan["clarification"]:
        return {
            "query_plan": plan,
            "route_to": "clarification",
            "exact_results": [],
            "related_results": [],
            "pending_results": [],
            "coverage": {
                "requested": 0,
                "processed": 0,
                "is_complete": False,
                "reason": str(plan["clarification"]),
            },
            "pagination": {"limit": bounded_limit, "returned": 0, "is_truncated": False},
            "warnings": [str(plan["clarification"])],
        }

    exact_matches: list[dict[str, object]] = []
    related_matches: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []
    processed: list[dict[str, object]] = []
    requested_years = list(plan["years"]) or [None]
    verified_only = str(plan["status"]) == "final_recognition"

    for year in requested_years:
        exact_response = discover_recognized_enterprises(
            connection,
            projects=list(plan["projects"]),
            subject_terms=list(plan["exact_terms"]),
            regions=list(plan["regions"]),
            year=int(year) if year is not None else None,
            verified_only=verified_only,
            limit=bounded_limit,
        )
        exact_matches.extend(exact_response["verified_matches"])
        pending.extend(exact_response["pending_candidates"])
        processed.append(
            {
                "year": year,
                "match_level": "exact",
                "coverage_ledger": exact_response["coverage_ledger"],
            }
        )
        if plan["related_terms"]:
            related_response = discover_recognized_enterprises(
                connection,
                projects=list(plan["projects"]),
                subject_terms=list(plan["related_terms"]),
                regions=list(plan["regions"]),
                year=int(year) if year is not None else None,
                verified_only=verified_only,
                limit=bounded_limit,
            )
            related_matches.extend(related_response["verified_matches"])
            pending.extend(related_response["pending_candidates"])
            processed.append(
                {
                    "year": year,
                    "match_level": "related",
                    "coverage_ledger": related_response["coverage_ledger"],
                }
            )

    exact = _dedupe_matches(
        exact_matches,
        excluded_terms=list(plan["excluded_terms"]),
    )
    exact_keys = {_recognition_fact_key(item) for item in exact}
    related = _dedupe_matches(
        related_matches,
        excluded_terms=list(plan["excluded_terms"]),
        excluded_keys=exact_keys,
    )
    pending_results = _dedupe_pending(
        pending,
        excluded_terms=list(plan["excluded_terms"]),
    )
    combined_count = len(exact) + len(related) + len(pending_results)
    returned = min(combined_count, bounded_limit)
    return {
        "query_plan": plan,
        "route_to": "recognition_reverse_lookup",
        "exact_results": exact[:bounded_limit],
        "related_results": related[:bounded_limit],
        "pending_results": pending_results[:bounded_limit],
        "coverage": {
            "requested": len(plan["projects"])
            * max(1, len(plan["regions"]))
            * max(1, len(requested_years)),
            "processed": processed,
            "is_complete": False,
            "reason": (
                "统一入口已执行全部解析出的项目、地区和年度，但当前知识证据及同义词集合不代表全国穷尽；"
                "未命中只能表述为当前检索层未命中。"
            ),
        },
        "pagination": {
            "limit": bounded_limit,
            "returned": returned,
            "is_truncated": combined_count > bounded_limit,
        },
        "warnings": [
            "exact_results需同时具备明确主题证据与权威认定事实。",
            "related_results只证明相关行业或产品方向，不得改写为明确生产目标产品。",
            "pending_results不得作为正式认定结果；未命中不等于不存在。",
        ],
    }

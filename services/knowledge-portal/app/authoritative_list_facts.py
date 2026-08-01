from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict


AUTHORITATIVE_LIST_TABLES = {
    "national_small_giant": "national_small_giant_master",
    "provincial_specialized_sme": "list_entity_reconciliation",
    "three_first": "three_first_project_awards",
}


class AuthorityTableUnavailable(RuntimeError):
    pass


def infer_authoritative_list_type(project_name: str) -> str | None:
    compact = re.sub(r"[\s\"'“”‘’《》〈〉（）()·•]+", "", project_name or "")
    if not compact:
        return None
    if any(term in compact for term in ("首台套", "首批次", "首版次", "三首")):
        return "three_first"
    if "小巨人" in compact and any(term in compact for term in ("国家", "专精特新")):
        return "national_small_giant"
    if "专精特新中小企业" in compact or compact in {"省专", "省级专精特新"}:
        return "provincial_specialized_sme"
    return None


def authority_table_available(connection: sqlite3.Connection, list_type: str) -> bool:
    table = AUTHORITATIVE_LIST_TABLES.get(list_type)
    if table is None:
        return False
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _require_authority_table(connection: sqlite3.Connection, list_type: str) -> str:
    table = AUTHORITATIVE_LIST_TABLES.get(list_type)
    if table is None:
        raise ValueError(f"不支持的权威名单类型：{list_type}")
    if not authority_table_available(connection, list_type):
        raise AuthorityTableUnavailable(f"权威名单专表尚未构建：{table}")
    return table


def _escaped_like(value: str) -> str:
    return f"%{value.strip().replace('%', '\\%').replace('_', '\\_')}%"


def _append_like(
    column: str,
    value: str,
    conditions: list[str],
    parameters: list[object],
) -> None:
    if value.strip():
        conditions.append(f"{column} LIKE ? ESCAPE '\\'")
        parameters.append(_escaped_like(value))


def _normalized_enterprise_name(value: str) -> str:
    return re.sub(r"[\s·•・,，。;；:：()（）【】\[\]\"“”'‘’]+", "", value or "").lower()


def _json_list(value: object) -> list[object]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _csv_integers(value: object) -> list[int]:
    return [int(item) for item in re.findall(r"\d+", str(value or ""))]


def _pagination(total: int, offset: int, limit: int, returned: int) -> dict[str, object]:
    has_more = offset + returned < total
    return {
        "offset": offset,
        "limit": limit,
        "returned": returned,
        "total": total,
        "has_more": has_more,
        "next_offset": offset + returned if has_more else None,
        "is_truncated": has_more,
    }


def _national_source_tier(verification_status: str) -> str:
    if verification_status == "official_local_fragment_match":
        return "official"
    if verification_status == "central_attachment_name_match_pending":
        return "official_central_attachment_pending"
    if verification_status == "dynamic_candidate_pending_official_fragment":
        return "licensed_platform_pending"
    return "pending_source_review"


def _response(
    *,
    list_type: str,
    table: str,
    rule: str,
    filters: dict[str, object],
    results: list[dict[str, object]],
    total: int,
    official_match_count: int,
    verified_count: int,
    pending_count: int,
    excluded_count: int,
    source_tiers: Counter[str],
    offset: int,
    limit: int,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    return {
        "list_type": list_type,
        "authority": {
            "table": table,
            "rule": rule,
            "generic_entity_override_allowed": False,
        },
        "filters": filters,
        "total": total,
        "summary": {
            "matched_count": total,
            "official_match_count": official_match_count,
            "verified_count": verified_count,
            "pending_verification_count": pending_count,
            "excluded_count": excluded_count,
            "source_tier_counts": dict(sorted(source_tiers.items())),
        },
        "pagination": _pagination(total, offset, limit, len(results)),
        "warnings": warnings or [],
        "results": results,
    }


def _national_small_giant_facts(
    connection: sqlite3.Connection,
    *,
    enterprise_name: str,
    year: int | None,
    batch: str,
    region: str,
    status: str,
    verified_only: bool,
    offset: int,
    limit: int,
) -> dict[str, object]:
    conditions = ["1=1"]
    parameters: list[object] = []
    _append_like("enterprise_name", enterprise_name, conditions, parameters)
    _append_like("batch", batch, conditions, parameters)
    _append_like("status", status, conditions, parameters)
    if year is not None:
        conditions.append("recognition_year=?")
        parameters.append(int(year))
    if region.strip():
        pattern = _escaped_like(region)
        conditions.append(
            "(region LIKE ? ESCAPE '\\' OR city LIKE ? ESCAPE '\\' "
            "OR county LIKE ? ESCAPE '\\')"
        )
        parameters.extend((pattern, pattern, pattern))
    if verified_only:
        conditions.append("verification_status='official_local_fragment_match'")
    where = " AND ".join(conditions)
    grouped = connection.execute(
        f"""
        SELECT verification_status,COUNT(*) AS count
        FROM national_small_giant_master WHERE {where}
        GROUP BY verification_status
        """,
        parameters,
    ).fetchall()
    verification_counts = Counter(
        {str(row["verification_status"]): int(row["count"]) for row in grouped}
    )
    total = sum(verification_counts.values())
    official = verification_counts.get("official_local_fragment_match", 0)
    source_tiers = Counter()
    for verification_status, count in verification_counts.items():
        source_tiers[_national_source_tier(verification_status)] += count
    rows = connection.execute(
        f"""
        SELECT * FROM national_small_giant_master
        WHERE {where}
        ORDER BY recognition_year DESC,region,city,county,enterprise_name,id
        LIMIT ? OFFSET ?
        """,
        [*parameters, limit, offset],
    ).fetchall()
    results: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        source_document_ids = [int(value) for value in _json_list(item["source_documents_json"])]
        source_paths = [str(value) for value in _json_list(item["source_paths_json"])]
        is_official = item["verification_status"] == "official_local_fragment_match"
        source_tier = _national_source_tier(str(item["verification_status"]))
        results.append(
            {
                "fact_id": f"national-small-giant:{item['id']}",
                "document_id": source_document_ids[0] if source_document_ids else 0,
                "list_type": "national_small_giant",
                "canonical_project_name": "国家专精特新“小巨人”企业",
                "enterprise_name": item["enterprise_name"],
                "product_name": "",
                "policy_year": item["recognition_year"],
                "batch": item["batch"],
                "region": "/".join(
                    value for value in (item["region"], item["city"], item["county"]) if value
                ),
                "province": item["region"],
                "city": item["city"],
                "county": item["county"],
                "list_status": item["status"],
                "verification_status": item["verification_status"],
                "official_match": is_official,
                "source_tier": source_tier,
                "source_grade": "official" if is_official else "pending_official_verification",
                "confidence": "high" if is_official else "medium",
                "source_url": item["official_url"],
                "source_url_role": item["official_url_role"],
                "source_document_ids": source_document_ids,
                "source_paths": source_paths,
                "sequence_no": item["sequence_no"],
            }
        )
    return _response(
        list_type="national_small_giant",
        table="national_small_giant_master",
        rule="official-fragment-first-v1",
        filters={
            "enterprise_name": enterprise_name.strip(),
            "year": year,
            "batch": batch.strip(),
            "region": region.strip(),
            "status": status.strip(),
            "verified_only": verified_only,
        },
        results=results,
        total=total,
        official_match_count=official,
        verified_count=official,
        pending_count=total - official,
        excluded_count=0,
        source_tiers=source_tiers,
        offset=offset,
        limit=limit,
    )


def _provincial_source_tier(result_status: str) -> str:
    if result_status in {"recognized_final", "final_only"}:
        return "official_final"
    if result_status == "not_in_final_recognition":
        return "official_final_exclusion"
    if result_status == "public_only_unresolved":
        return "official_publicity"
    return "unverified"


def _provincial_fact_priority(item: dict[str, object]) -> tuple[int, int]:
    status_priority = {
        "recognized_final": 0,
        "final_only": 1,
        "not_in_final_recognition": 2,
        "public_only_unresolved": 3,
    }
    return (
        status_priority.get(str(item["result_status"]), 9),
        int(item["id"]),
    )


def _provincial_specialized_sme_facts(
    connection: sqlite3.Connection,
    *,
    enterprise_name: str,
    year: int | None,
    region: str,
    status: str,
    verified_only: bool,
    offset: int,
    limit: int,
) -> dict[str, object]:
    conditions = ["r.project_scope='provincial_specialized_sme'"]
    parameters: list[object] = []
    _append_like("r.enterprise_name", enterprise_name, conditions, parameters)
    _append_like("r.result_status", status, conditions, parameters)
    if year is not None:
        conditions.append("r.year=?")
        parameters.append(int(year))
    if verified_only:
        conditions.append("r.effective_recognition=1")

    matched_regions: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    matched_documents: dict[tuple[str, int, str], dict[int, dict[str, object]]] = defaultdict(dict)
    city_level_filter = False
    if region.strip():
        direct_parameters = [*parameters, _escaped_like(region)]
        direct_count = connection.execute(
            f"SELECT COUNT(*) FROM list_entity_reconciliation r "
            f"WHERE {' AND '.join(conditions)} AND r.region LIKE ? ESCAPE '\\'",
            direct_parameters,
        ).fetchone()[0]
        if int(direct_count):
            conditions.append("r.region LIKE ? ESCAPE '\\'")
            parameters.append(_escaped_like(region))
        else:
            city_level_filter = True
            geography_conditions = [
                "l.project_scope='provincial_specialized_sme'",
                "l.exclusion_reason=''",
                "e.region LIKE ? ESCAPE '\\'",
            ]
            geography_parameters: list[object] = [_escaped_like(region)]
            if year is not None:
                geography_conditions.append("l.year=?")
                geography_parameters.append(int(year))
            geography_rows = connection.execute(
                f"""
                SELECT l.region AS authority_region,l.year,e.enterprise_name,e.region AS matched_region,
                       l.document_id,l.evidence_type,d.title,d.source
                FROM public_list_entities e
                JOIN list_coverage_evidence l ON l.document_id=e.document_id
                JOIN documents d ON d.id=l.document_id
                WHERE {' AND '.join(geography_conditions)}
                """,
                geography_parameters,
            ).fetchall()
            for geography in geography_rows:
                key = (
                    str(geography["authority_region"]),
                    int(geography["year"]),
                    _normalized_enterprise_name(str(geography["enterprise_name"])),
                )
                matched_regions[key].add(str(geography["matched_region"]))
                matched_documents[key][int(geography["document_id"])] = {
                    "document_id": int(geography["document_id"]),
                    "evidence_type": str(geography["evidence_type"]),
                    "title": str(geography["title"]),
                    "source": str(geography["source"]),
                }
            pairs = sorted({(key[0], key[1]) for key in matched_regions})
            if pairs:
                pair_sql = " OR ".join("(r.region=? AND r.year=?)" for _ in pairs)
                conditions.append(f"({pair_sql})")
                for province, matched_year in pairs:
                    parameters.extend((province, matched_year))
            else:
                conditions.append("0=1")

    rows = connection.execute(
        f"""
        SELECT r.*,c.document_id AS canonical_document_id,
               c.evidence_type AS canonical_evidence_type,
               c.title AS canonical_title,c.source AS canonical_source
        FROM list_entity_reconciliation r
        LEFT JOIN canonical_list_sources c
          ON c.region=r.region AND c.year=r.year AND c.project_scope=r.project_scope
        WHERE {' AND '.join(conditions)}
        ORDER BY r.year DESC,r.region,r.enterprise_name,r.id
        """,
        parameters,
    ).fetchall()
    selected_by_key: dict[
        tuple[str, int, str], tuple[dict[str, object], set[str]]
    ] = {}
    for row in rows:
        item = dict(row)
        key = (
            str(item["region"]),
            int(item["year"]),
            _normalized_enterprise_name(str(item["enterprise_name"])),
        )
        geography = sorted(matched_regions.get(key, set()))
        if city_level_filter and not geography:
            continue
        existing = selected_by_key.get(key)
        if existing is None:
            selected_by_key[key] = (item, set(geography))
            continue
        existing_item, existing_geography = existing
        merged_geography = existing_geography | set(geography)
        selected_by_key[key] = (
            item if _provincial_fact_priority(item) < _provincial_fact_priority(existing_item) else existing_item,
            merged_geography,
        )

    selected = sorted(
        (
            (item, sorted(geography))
            for item, geography in selected_by_key.values()
        ),
        key=lambda pair: (
            -int(pair[0]["year"]),
            str(pair[0]["region"]),
            str(pair[0]["enterprise_name"]),
            int(pair[0]["id"]),
        ),
    )

    total = len(selected)
    source_tiers = Counter(_provincial_source_tier(str(item["result_status"])) for item, _ in selected)
    official = sum(int(item["effective_recognition"]) for item, _ in selected)
    pending = sum(item["result_status"] == "public_only_unresolved" for item, _ in selected)
    excluded = sum(item["result_status"] == "not_in_final_recognition" for item, _ in selected)
    page = selected[offset : offset + limit]
    results: list[dict[str, object]] = []
    for item, geography in page:
        tier = _provincial_source_tier(str(item["result_status"]))
        is_official = bool(item["effective_recognition"])
        group_evidence_ids = sorted(
            set(_csv_integers(item["final_document_ids"]) + _csv_integers(item["public_document_ids"]))
        )
        key = (
            str(item["region"]),
            int(item["year"]),
            _normalized_enterprise_name(str(item["enterprise_name"])),
        )
        exact_documents = sorted(
            matched_documents.get(key, {}).values(),
            key=lambda document: (
                0 if document["evidence_type"] in {"final", "final_review"} else 1,
                int(document["document_id"]),
            ),
        )
        exact_source = exact_documents[0] if exact_documents else None
        canonical_document_id = (
            int(exact_source["document_id"])
            if exact_source
            else int(item["canonical_document_id"] or (group_evidence_ids[0] if group_evidence_ids else 0))
        )
        results.append(
            {
                "fact_id": f"provincial-specialized-sme:{item['id']}",
                "document_id": canonical_document_id,
                "list_type": "provincial_specialized_sme",
                "canonical_project_name": "省级专精特新中小企业",
                "enterprise_name": item["enterprise_name"],
                "product_name": "",
                "policy_year": item["year"],
                "batch": "",
                "region": item["region"],
                "matched_regions": geography,
                "list_status": item["result_status"],
                "verification_status": item["result_status"],
                "effective_recognition": is_official,
                "official_match": is_official,
                "source_tier": tier,
                "source_grade": tier,
                "confidence": "high" if is_official or excluded else "medium",
                "resolution_reason": item["resolution_reason"],
                "canonical_document_id": canonical_document_id,
                "canonical_evidence_type": (
                    exact_source["evidence_type"] if exact_source else item["canonical_evidence_type"] or ""
                ),
                "canonical_title": exact_source["title"] if exact_source else item["canonical_title"] or "",
                "canonical_source": exact_source["source"] if exact_source else item["canonical_source"] or "",
                "source_document_ids": (
                    [int(document["document_id"]) for document in exact_documents]
                    if exact_documents
                    else group_evidence_ids
                ),
                "source_scope": "enterprise_geography_match" if exact_documents else "region_year_canonical",
                "rule_version": item["rule_version"],
            }
        )
    warnings: list[str] = []
    if city_level_filter:
        warnings.append("市区字段来自权威证据文档实体，仅用于地理筛选；认定状态仍以省级名单调和主表为准。")
    return _response(
        list_type="provincial_specialized_sme",
        table="list_entity_reconciliation",
        rule="final-recognition-first-v1",
        filters={
            "enterprise_name": enterprise_name.strip(),
            "year": year,
            "batch": "",
            "region": region.strip(),
            "status": status.strip(),
            "verified_only": verified_only,
        },
        results=results,
        total=total,
        official_match_count=official,
        verified_count=official,
        pending_count=pending,
        excluded_count=excluded,
        source_tiers=source_tiers,
        offset=offset,
        limit=limit,
        warnings=warnings,
    )


def _three_first_facts(
    connection: sqlite3.Connection,
    *,
    enterprise_name: str,
    product_name: str,
    project_name: str,
    year: int | None,
    region: str,
    status: str,
    verified_only: bool,
    offset: int,
    limit: int,
) -> dict[str, object]:
    conditions = ["1=1"]
    parameters: list[object] = []
    _append_like("enterprise_name", enterprise_name, conditions, parameters)
    _append_like("product_name", product_name, conditions, parameters)
    _append_like("project_name", project_name, conditions, parameters)
    _append_like("list_status", status, conditions, parameters)
    if year is not None:
        conditions.append("year=?")
        parameters.append(int(year))
    if region.strip():
        pattern = _escaped_like(region)
        conditions.append(
            "(province LIKE ? ESCAPE '\\' OR city LIKE ? ESCAPE '\\' "
            "OR county LIKE ? ESCAPE '\\')"
        )
        parameters.extend((pattern, pattern, pattern))
    if verified_only:
        conditions.append("confidence<>'discovery_only'")
    where = " AND ".join(conditions)
    grouped = connection.execute(
        f"""
        SELECT source_tier,confidence,COUNT(*) AS count
        FROM three_first_project_awards WHERE {where}
        GROUP BY source_tier,confidence
        """,
        parameters,
    ).fetchall()
    total = sum(int(row["count"]) for row in grouped)
    official = sum(int(row["count"]) for row in grouped if row["source_tier"] == "official")
    verified = sum(int(row["count"]) for row in grouped if row["confidence"] != "discovery_only")
    pending = total - verified
    source_tiers = Counter()
    for row in grouped:
        source_tiers[str(row["source_tier"])] += int(row["count"])
    rows = connection.execute(
        f"""
        SELECT * FROM three_first_project_awards
        WHERE {where}
        ORDER BY year DESC,project_name,enterprise_name,product_name,id
        LIMIT ? OFFSET ?
        """,
        [*parameters, limit, offset],
    ).fetchall()
    results: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        is_official = item["source_tier"] == "official"
        is_pending = item["confidence"] == "discovery_only"
        results.append(
            {
                "fact_id": f"three-first:{item['id']}",
                "document_id": 0,
                "list_type": "three_first",
                "canonical_project_name": item["project_name"],
                "enterprise_name": item["enterprise_name"],
                "product_name": item["product_name"],
                "policy_year": item["year"],
                "batch": "",
                "region": "/".join(
                    value for value in (item["province"], item["city"], item["county"]) if value
                ),
                "province": item["province"],
                "city": item["city"],
                "county": item["county"],
                "list_status": item["list_status"],
                "verification_status": (
                    "official_source_match"
                    if is_official
                    else "discovery_only_pending_official"
                    if is_pending
                    else "structured_source_record"
                ),
                "official_match": is_official,
                "source_tier": item["source_tier"],
                "source_grade": item["source_tier"],
                "confidence": item["confidence"],
                "recognition_tier": item["recognition_tier"],
                "product_category": item["product_category"],
                "product_name_status": item["product_name_status"],
                "source_title": item["source_title"],
                "source_url": item["source_url"],
                "source_policy_id": item["source_policy_id"],
                "source_index_id": item["source_index_id"],
                "evidence_semantics": item["evidence_semantics"],
            }
        )
    return _response(
        list_type="three_first",
        table="three_first_project_awards",
        rule="product-level-source-priority-v1",
        filters={
            "enterprise_name": enterprise_name.strip(),
            "product_name": product_name.strip(),
            "project_name": project_name.strip(),
            "year": year,
            "batch": "",
            "region": region.strip(),
            "status": status.strip(),
            "verified_only": verified_only,
        },
        results=results,
        total=total,
        official_match_count=official,
        verified_count=verified,
        pending_count=pending,
        excluded_count=0,
        source_tiers=source_tiers,
        offset=offset,
        limit=limit,
    )


def query_authoritative_list_facts(
    connection: sqlite3.Connection,
    *,
    list_type: str,
    enterprise_name: str = "",
    product_name: str = "",
    project_name: str = "",
    year: int | None = None,
    batch: str = "",
    region: str = "",
    status: str = "",
    verified_only: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    _require_authority_table(connection, list_type)
    bounded_offset = max(0, min(int(offset), 1_000_000))
    bounded_limit = max(1, min(int(limit), 200))
    if list_type == "national_small_giant":
        return _national_small_giant_facts(
            connection,
            enterprise_name=enterprise_name,
            year=year,
            batch=batch,
            region=region,
            status=status,
            verified_only=verified_only,
            offset=bounded_offset,
            limit=bounded_limit,
        )
    if list_type == "provincial_specialized_sme":
        return _provincial_specialized_sme_facts(
            connection,
            enterprise_name=enterprise_name,
            year=year,
            region=region,
            status=status,
            verified_only=verified_only,
            offset=bounded_offset,
            limit=bounded_limit,
        )
    return _three_first_facts(
        connection,
        enterprise_name=enterprise_name,
        product_name=product_name,
        project_name=project_name,
        year=year,
        region=region,
        status=status,
        verified_only=verified_only,
        offset=bounded_offset,
        limit=bounded_limit,
    )

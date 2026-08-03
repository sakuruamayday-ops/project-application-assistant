from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict


AUTHORITATIVE_LIST_TABLES = {
    "national_small_giant": "national_small_giant_master",
    "provincial_specialized_sme": "enterprise_recognition_events",
    "three_first": "three_first_project_awards",
}

AUTHORITATIVE_LIST_TYPE_ALIASES = {
    "national_small_giant": "national_small_giant",
    "国家小巨人": "national_small_giant",
    "国家专精特新小巨人": "national_small_giant",
    "专精特新小巨人": "national_small_giant",
    "小巨人": "national_small_giant",
    "provincial_specialized_sme": "provincial_specialized_sme",
    "省级专精特新": "provincial_specialized_sme",
    "省专": "provincial_specialized_sme",
    "专精特新中小企业": "provincial_specialized_sme",
    "three_first": "three_first",
    "三首": "three_first",
    "三首项目": "three_first",
    "首台套": "three_first",
    "首台（套）": "three_first",
    "首版次": "three_first",
    "首批次": "three_first",
}

ANNUAL_PUBLICATION_EVENT_TYPES = (
    "recognition",
    "recognition_publicity",
    "review_passed",
    "review_publicity",
)
REVIEW_PUBLICATION_EVENT_TYPES = ("review_passed", "review_publicity")
RECOGNITION_PUBLICATION_EVENT_TYPES = ("recognition", "recognition_publicity")


class AuthorityTableUnavailable(RuntimeError):
    pass


def normalize_authoritative_list_type(list_type: str) -> str:
    compact = re.sub(r"[\s\"'“”‘’《》〈〉（）()·•]+", "", list_type or "")
    normalized = AUTHORITATIVE_LIST_TYPE_ALIASES.get(compact)
    if normalized:
        return normalized
    if compact in AUTHORITATIVE_LIST_TABLES:
        return compact
    raise ValueError(f"不支持的权威名单类型：{list_type}")


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
    escaped = value.strip().replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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
    coverage: dict[str, object] | None = None,
) -> dict[str, object]:
    coverage_payload = coverage or {
        "status": "not_audited",
        "completeness_claim_allowed": False,
        "cells": [],
    }
    response_warnings = list(warnings or [])
    if not coverage_payload.get("completeness_claim_allowed"):
        response_warnings.append("当前来源覆盖未闭环，结果不得表述为该筛选范围的完整名单。")
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
        "coverage": coverage_payload,
        "warnings": list(dict.fromkeys(response_warnings)),
        "results": results,
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _column_exists(
    connection: sqlite3.Connection,
    table: str,
    column: str,
) -> bool:
    """兼容尚未补齐新列的历史权威名单表。"""
    if table not in AUTHORITATIVE_LIST_TABLES.values():
        return False
    return any(
        str(row[1]) == column
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _append_enterprise_subject_filter(
    connection: sqlite3.Connection,
    conditions: list[str],
) -> None:
    if _column_exists(connection, "enterprise_recognition_events", "subject_type"):
        conditions.append("subject_type='enterprise'")


def _national_coverage(
    connection: sqlite3.Connection,
    *,
    year: int | None,
    batch: str,
    region: str,
    official_match_count: int,
    total: int,
) -> dict[str, object]:
    if not _table_exists(connection, "national_small_giant_batch_coverage"):
        return {
            "status": "coverage_table_missing",
            "completeness_claim_allowed": False,
            "cells": [],
        }
    conditions = ["1=1"]
    parameters: list[object] = []
    if year is not None:
        conditions.append("recognition_year=?")
        parameters.append(int(year))
    if batch.strip():
        conditions.append("batch=?")
        parameters.append(batch.strip())
    rows = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM national_small_giant_batch_coverage WHERE "
            f"{' AND '.join(conditions)} ORDER BY recognition_year",
            parameters,
        ).fetchall()
    ]
    cells_complete = bool(rows) and all(
        bool(row["completeness_claim_allowed"]) for row in rows
    )
    regional_evidence_complete = not region.strip() or official_match_count == total
    allowed = cells_complete and regional_evidence_complete
    return {
        "status": "complete" if allowed else "incomplete",
        "completeness_claim_allowed": allowed,
        "scope": "batch_and_extracted_geography" if region.strip() else "national_batch",
        "cells": rows,
    }


def _event_purpose(event_type: str) -> str:
    return "review" if event_type in REVIEW_PUBLICATION_EVENT_TYPES else "recognition"


def _event_priority(row: sqlite3.Row | dict[str, object]) -> tuple[int, int]:
    item = dict(row)
    event_type = str(item.get("event_type") or "")
    evidence_status = str(item.get("evidence_status") or "")
    if evidence_status.startswith("official_final") and event_type in {
        "recognition",
        "review_passed",
    }:
        stage = 0
    elif "publicity" in evidence_status or event_type.endswith("publicity"):
        stage = 1
    else:
        stage = 2
    return stage, int(item.get("id") or 0)


def _dedupe_annual_event_rows(
    rows: list[sqlite3.Row],
) -> list[sqlite3.Row]:
    selected: dict[tuple[str, str, int], sqlite3.Row] = {}
    for row in rows:
        identity = str(row["identity_key"] or row["normalized_name"])
        # Publicity and final documents frequently use different batch labels
        # for the same annual recognition/review cohort.  Annual list queries
        # return each enterprise once per purpose and cohort, preferring the
        # strongest event through _event_priority.
        cohort_year = int(row["cohort_year"] or row["event_year"] or 0)
        key = (identity, _event_purpose(str(row["event_type"])), cohort_year)
        current = selected.get(key)
        if current is None or _event_priority(row) < _event_priority(current):
            selected[key] = row
    return sorted(
        selected.values(),
        key=lambda row: (
            -int(row["event_year"] or 0),
            _event_purpose(str(row["event_type"])),
            str(row["batch"]),
            str(row["recognition_city"]),
            str(row["enterprise_name_at_event"]),
            int(row["id"]),
        ),
    )


def _event_source_coverage(
    connection: sqlite3.Connection,
    *,
    project_name: str,
    year: int | None,
    batch: str,
    region: str,
    event_types: tuple[str, ...],
) -> dict[str, object]:
    if not _table_exists(connection, "enterprise_lifecycle_source_audits"):
        return {
            "status": "coverage_table_missing",
            "completeness_claim_allowed": False,
            "cells": [],
        }
    placeholders = ",".join("?" for _ in event_types)
    conditions = ["project_name=?", f"event_type IN ({placeholders})"]
    parameters: list[object] = [project_name, *event_types]
    if year is not None:
        conditions.append("event_year=?")
        parameters.append(int(year))
    if batch.strip():
        conditions.append("batch=?")
        parameters.append(batch.strip())
    city_level_filter = bool(
        region.strip() and region.strip() not in {"浙江", "浙江省"}
    )
    candidate_rows = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT source_id,document_id,document_title,project_name,event_type,event_year,
                   batch,city,covered_cities_json,expected_count,announced_count,actual_count,count_aligned,
                   completeness_claim_allowed,known_blank_sequences_json,source_path,official_url
            FROM enterprise_lifecycle_source_audits
            WHERE {' AND '.join(conditions)}
            ORDER BY event_year,event_type,batch,source_id
            """,
            parameters,
        ).fetchall()
    ]
    rows = candidate_rows
    if city_level_filter:
        requested_city = region.strip()
        rows = [
            row
            for row in candidate_rows
            if str(row["city"]) == requested_city
            or requested_city in {
                str(value) for value in _json_list(row["covered_cities_json"])
            }
        ]
    unmapped_scope_source_count = 0
    if city_level_filter:
        directly_mapped_keys = {
            (int(row["event_year"]), str(row["event_type"]), str(row["batch"]))
            for row in rows
            if row["event_year"] is not None
            and bool(row["completeness_claim_allowed"])
        }
        unmapped_scope_source_count = sum(
            1
            for row in candidate_rows
            if not str(row["city"])
            and region.strip()
            not in {str(value) for value in _json_list(row["covered_cities_json"])}
            and (
                row["event_year"] is None
                or (
                    int(row["event_year"]),
                    str(row["event_type"]),
                    str(row["batch"]),
                )
                not in directly_mapped_keys
            )
        )
    allowed = bool(rows) and not unmapped_scope_source_count and all(
        bool(row["completeness_claim_allowed"]) for row in rows
    )
    return {
        "status": "complete" if allowed else "incomplete",
        "completeness_claim_allowed": allowed,
        "scope": "configured_publication_events",
        "unmapped_scope_source_count": unmapped_scope_source_count,
        "cells": rows,
    }


def _national_small_giant_publication_facts(
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
    include_recognition: bool,
    recognition_event_types: tuple[str, ...] = RECOGNITION_PUBLICATION_EVENT_TYPES,
    review_event_types: tuple[str, ...],
    response_event_type: str = "",
) -> dict[str, object]:
    recognition_rows: list[sqlite3.Row] = []
    recognition_event_rows: list[sqlite3.Row] = []
    use_direct_recognition_events = False
    recognition_coverage = {
        "status": "not_in_scope",
        "completeness_claim_allowed": True,
        "cells": [],
    }
    if include_recognition:
        direct_coverage = _event_source_coverage(
            connection,
            project_name="国家专精特新“小巨人”企业",
            year=year,
            batch=batch,
            region=region,
            event_types=recognition_event_types,
        )
        if (
            _table_exists(connection, "enterprise_recognition_events")
            and bool(direct_coverage["completeness_claim_allowed"])
        ):
            placeholders = ",".join("?" for _ in recognition_event_types)
            direct_conditions = [
                "project_name='国家专精特新“小巨人”企业'",
                f"event_type IN ({placeholders})",
                "source_kinds_json LIKE '%\"lifecycle_manifest\"%'",
            ]
            _append_enterprise_subject_filter(connection, direct_conditions)
            direct_parameters: list[object] = list(recognition_event_types)
            _append_like(
                "enterprise_name_at_event",
                enterprise_name,
                direct_conditions,
                direct_parameters,
            )
            _append_like("status", status, direct_conditions, direct_parameters)
            if year is not None:
                direct_conditions.append("event_year=?")
                direct_parameters.append(int(year))
            if batch.strip():
                direct_conditions.append("batch=?")
                direct_parameters.append(batch.strip())
            if region.strip():
                pattern = _escaped_like(region)
                direct_conditions.append(
                    "(recognition_province LIKE ? ESCAPE '\\' "
                    "OR recognition_city LIKE ? ESCAPE '\\' "
                    "OR recognition_county LIKE ? ESCAPE '\\')"
                )
                direct_parameters.extend((pattern, pattern, pattern))
            if verified_only:
                direct_conditions.append("evidence_status<>''")
            recognition_event_rows = _dedupe_annual_event_rows(
                connection.execute(
                    "SELECT * FROM enterprise_recognition_events WHERE "
                    + " AND ".join(direct_conditions),
                    direct_parameters,
                ).fetchall()
            )
            # A complete official publication scope remains authoritative even
            # when the filters legitimately match zero rows. Falling back to
            # the cross-source master in that case can re-introduce Qice-only
            # extras into an official batch query.
            use_direct_recognition_events = True
            recognition_coverage = direct_coverage

        if not use_direct_recognition_events:
            conditions = ["1=1"]
            parameters: list[object] = []
            _append_like("enterprise_name", enterprise_name, conditions, parameters)
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
                conditions.append(
                    "verification_status='official_local_fragment_match'"
                )
            recognition_rows = connection.execute(
                f"""
                SELECT * FROM national_small_giant_master
                WHERE {' AND '.join(conditions)}
                ORDER BY recognition_year DESC,region,city,county,enterprise_name,id
                """,
                parameters,
            ).fetchall()
            recognition_official = sum(
                row["verification_status"] == "official_local_fragment_match"
                for row in recognition_rows
            )
            recognition_coverage = _national_coverage(
                connection,
                year=year,
                batch="",
                region=region,
                official_match_count=recognition_official,
                total=len(recognition_rows),
            )

    review_rows: list[sqlite3.Row] = []
    if review_event_types and _table_exists(connection, "enterprise_recognition_events"):
        placeholders = ",".join("?" for _ in review_event_types)
        conditions = [
            "project_name='国家专精特新“小巨人”企业'",
            f"event_type IN ({placeholders})",
        ]
        _append_enterprise_subject_filter(connection, conditions)
        parameters = list(review_event_types)
        _append_like("enterprise_name_at_event", enterprise_name, conditions, parameters)
        _append_like("status", status, conditions, parameters)
        if year is not None:
            conditions.append("event_year=?")
            parameters.append(int(year))
        if batch.strip():
            conditions.append("batch=?")
            parameters.append(batch.strip())
        if region.strip():
            pattern = _escaped_like(region)
            conditions.append(
                "(recognition_province LIKE ? ESCAPE '\\' OR recognition_city LIKE ? ESCAPE '\\' "
                "OR recognition_county LIKE ? ESCAPE '\\')"
            )
            parameters.extend((pattern, pattern, pattern))
        if verified_only:
            conditions.append("evidence_status<>''")
        review_rows = _dedupe_annual_event_rows(
            connection.execute(
                f"SELECT * FROM enterprise_recognition_events WHERE {' AND '.join(conditions)}",
                parameters,
            ).fetchall()
        )

    combined: list[tuple[str, sqlite3.Row]] = [
        *(("recognition_master", row) for row in recognition_rows),
        *(("recognition_event", row) for row in recognition_event_rows),
        *(("review_event", row) for row in review_rows),
    ]
    combined.sort(
        key=lambda pair: (
            0 if pair[0].startswith("recognition") else 1,
            str(
                pair[1]["enterprise_name"]
                if pair[0] == "recognition_master"
                else pair[1]["enterprise_name_at_event"]
            ),
        )
    )
    source_tiers: Counter[str] = Counter()
    official = 0
    verified = 0
    for kind, row in combined:
        if kind == "recognition_master":
            tier = _national_source_tier(str(row["verification_status"]))
            is_official = row["verification_status"] == "official_local_fragment_match"
            is_verified = is_official
        else:
            tier = _provincial_event_source_tier(
                str(row["evidence_status"]), str(row["event_type"])
            )
            is_official = tier == "official_final"
            is_verified = tier != "unverified"
        source_tiers[tier] += 1
        official += int(is_official)
        verified += int(is_verified)

    results: list[dict[str, object]] = []
    for kind, row in combined[offset : offset + limit]:
        if kind == "recognition_master":
            item = dict(row)
            source_document_ids = [int(value) for value in _json_list(item["source_documents_json"])]
            source_paths = [str(value) for value in _json_list(item["source_paths_json"])]
            is_official = item["verification_status"] == "official_local_fragment_match"
            tier = _national_source_tier(str(item["verification_status"]))
            results.append(
                {
                    "fact_id": f"national-small-giant:{item['id']}",
                    "event_uid": "",
                    "document_id": source_document_ids[0] if source_document_ids else 0,
                    "list_type": "national_small_giant",
                    "canonical_project_name": "国家专精特新“小巨人”企业",
                    "enterprise_name": item["enterprise_name"],
                    "product_name": "",
                    "policy_year": item["recognition_year"],
                    "cohort_year": item["recognition_year"],
                    "batch": item["batch"],
                    "region": "/".join(value for value in (item["region"], item["city"], item["county"]) if value),
                    "province": item["region"],
                    "city": item["city"],
                    "county": item["county"],
                    "list_status": item["status"],
                    "event_type": "recognition",
                    "verification_status": item["verification_status"],
                    "official_match": is_official,
                    "source_tier": tier,
                    "source_grade": "official" if is_official else "pending_official_verification",
                    "confidence": "high" if is_official else "medium",
                    "source_url": item["official_url"],
                    "source_document_ids": source_document_ids,
                    "source_paths": source_paths,
                }
            )
        else:
            item = dict(row)
            tier = _provincial_event_source_tier(
                str(item["evidence_status"]), str(item["event_type"])
            )
            results.append(
                {
                    "fact_id": f"national-small-giant:{item['event_uid']}",
                    "event_uid": item["event_uid"],
                    "document_id": 0,
                    "list_type": "national_small_giant",
                    "canonical_project_name": "国家专精特新“小巨人”企业",
                    "enterprise_name": item["enterprise_name_at_event"],
                    "product_name": "",
                    "policy_year": item["event_year"],
                    "cohort_year": item["cohort_year"],
                    "batch": item["batch"],
                    "region": "/".join(value for value in (item["recognition_province"], item["recognition_city"], item["recognition_county"]) if value),
                    "province": item["recognition_province"],
                    "city": item["recognition_city"],
                    "county": item["recognition_county"],
                    "list_status": item["status"],
                    "event_type": item["event_type"],
                    "verification_status": item["evidence_status"],
                    "official_match": tier == "official_final",
                    "source_tier": tier,
                    "source_grade": tier,
                    "confidence": "high" if tier != "unverified" else "medium",
                    "source_title": item["source_title"],
                    "source_paths": _json_list(item["source_paths_json"]),
                    "source_urls": _json_list(item["source_urls_json"]),
                    "identity_key": item["identity_key"],
                }
            )

    review_coverage = (
        _event_source_coverage(
            connection,
            project_name="国家专精特新“小巨人”企业",
            year=year,
            batch=batch,
            region=region,
            event_types=review_event_types,
        )
        if review_event_types
        else {
            "status": "not_in_scope",
            "completeness_claim_allowed": True,
            "cells": [],
        }
    )
    coverage_allowed = bool(recognition_coverage["completeness_claim_allowed"]) and bool(
        review_coverage["completeness_claim_allowed"]
    )
    return _response(
        list_type="national_small_giant",
        table=(
            "national_small_giant_master+enterprise_recognition_events"
            if recognition_event_rows or review_rows
            else "national_small_giant_master"
        ),
        rule="annual-publication-new-recognition-plus-review-v1",
        filters={
            "enterprise_name": enterprise_name.strip(),
            "year": year,
            "batch": batch.strip(),
            "region": region.strip(),
            "status": status.strip(),
            "event_type": response_event_type
            or (
                "annual_published"
                if include_recognition and review_event_types
                else ",".join(
                    (*(recognition_event_types if include_recognition else ()), *review_event_types)
                )
            ),
            "verified_only": verified_only,
        },
        results=results,
        total=len(combined),
        official_match_count=official,
        verified_count=verified,
        pending_count=len(combined) - verified,
        excluded_count=0,
        source_tiers=source_tiers,
        offset=offset,
        limit=limit,
        warnings=[
            "年度名单仅包含当年发布的新认定与复核通过事件；往年仍有效、变更、撤销和财政支持事件已排除。"
        ],
        coverage={
            "status": "complete" if coverage_allowed else "incomplete",
            "completeness_claim_allowed": coverage_allowed,
            "scope": "annual_publication_new_recognition_plus_review",
            "cells": [
                *list(recognition_coverage.get("cells", [])),
                *list(review_coverage.get("cells", [])),
            ],
        },
    )


def _national_small_giant_facts(
    connection: sqlite3.Connection,
    *,
    enterprise_name: str,
    year: int | None,
    batch: str,
    region: str,
    status: str,
    event_type: str,
    verified_only: bool,
    offset: int,
    limit: int,
) -> dict[str, object]:
    requested_event_type = event_type.strip()
    if requested_event_type in REVIEW_PUBLICATION_EVENT_TYPES:
        return _national_small_giant_publication_facts(
            connection,
            enterprise_name=enterprise_name,
            year=year,
            batch=batch,
            region=region,
            status=status,
            verified_only=verified_only,
            offset=offset,
            limit=limit,
            include_recognition=False,
            review_event_types=(requested_event_type,),
            response_event_type=requested_event_type,
        )
    if requested_event_type in RECOGNITION_PUBLICATION_EVENT_TYPES:
        return _national_small_giant_publication_facts(
            connection,
            enterprise_name=enterprise_name,
            year=year,
            batch=batch,
            region=region,
            status=status,
            verified_only=verified_only,
            offset=offset,
            limit=limit,
            include_recognition=True,
            recognition_event_types=(requested_event_type,),
            review_event_types=(),
            response_event_type=requested_event_type,
        )
    if batch.strip() and not requested_event_type:
        return _national_small_giant_publication_facts(
            connection,
            enterprise_name=enterprise_name,
            year=year,
            batch=batch,
            region=region,
            status=status,
            verified_only=verified_only,
            offset=offset,
            limit=limit,
            include_recognition=True,
            review_event_types=(),
            response_event_type="recognition_publication",
        )
    if year is not None and not batch.strip() and not requested_event_type:
        return _national_small_giant_publication_facts(
            connection,
            enterprise_name=enterprise_name,
            year=year,
            batch="",
            region=region,
            status=status,
            verified_only=verified_only,
            offset=offset,
            limit=limit,
            include_recognition=True,
            review_event_types=REVIEW_PUBLICATION_EVENT_TYPES,
        )
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
            "event_type": requested_event_type or "recognition",
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
        coverage=_national_coverage(
            connection,
            year=year,
            batch=batch,
            region=region,
            official_match_count=official,
            total=total,
        ),
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


def _legacy_provincial_specialized_sme_facts(
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


def _provincial_event_source_tier(evidence_status: str, event_type: str) -> str:
    if evidence_status.startswith("official_final"):
        return "official_final"
    if "publicity" in evidence_status or event_type.endswith("publicity"):
        return "official_publicity"
    if evidence_status:
        return "archived_structured_source"
    return "unverified"


def _provincial_coverage(
    connection: sqlite3.Connection,
    *,
    year: int | None,
    batch: str,
    region: str,
    event_type: str,
) -> dict[str, object]:
    province_level = not region.strip() or region.strip() in {"浙江", "浙江省"}
    if province_level and _table_exists(
        connection, "enterprise_regional_coverage_audits"
    ):
        conditions = ["project_name='浙江省专精特新中小企业'", "event_type=?"]
        parameters: list[object] = [event_type]
        if year is not None:
            conditions.append("event_year=?")
            parameters.append(int(year))
        groups = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT coverage_group_id,project_name,event_year,event_type,scope,
                       expected_region_count,covered_region_count,entity_count,
                       complete,strict,expected_regions_json,covered_regions_json,
                       missing_regions_json,count_mismatch_regions_json
                FROM enterprise_regional_coverage_audits
                WHERE {' AND '.join(conditions)}
                ORDER BY event_year,coverage_group_id
                """,
                parameters,
            ).fetchall()
        ]
        if groups:
            allowed = all(bool(group["complete"]) for group in groups)
            return {
                "status": "complete" if allowed else "incomplete",
                "completeness_claim_allowed": allowed,
                "scope": "configured_regional_coverage_group",
                "cells": groups,
            }
    if not _table_exists(connection, "enterprise_lifecycle_source_audits"):
        return {
            "status": "coverage_table_missing",
            "completeness_claim_allowed": False,
            "cells": [],
        }
    conditions = ["project_name='浙江省专精特新中小企业'", "event_type=?"]
    parameters: list[object] = [event_type]
    if year is not None:
        conditions.append("event_year=?")
        parameters.append(int(year))
    if batch.strip():
        conditions.append("batch=?")
        parameters.append(batch.strip())
    if not province_level:
        conditions.append("city=?")
        parameters.append(region.strip())
    else:
        conditions.append("city=''")
    rows = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT source_id,document_id,document_title,event_year,batch,city,
                   expected_count,announced_count,actual_count,count_aligned,
                   completeness_claim_allowed,known_blank_sequences_json,
                   source_path,official_url
            FROM enterprise_lifecycle_source_audits
            WHERE {' AND '.join(conditions)}
            ORDER BY event_year,batch,source_id
            """,
            parameters,
        ).fetchall()
    ]
    allowed = bool(rows) and all(
        bool(row["completeness_claim_allowed"]) for row in rows
    )
    return {
        "status": "complete" if allowed else "incomplete",
        "completeness_claim_allowed": allowed,
        "scope": "configured_lifecycle_source",
        "cells": rows,
    }


def _provincial_specialized_sme_facts(
    connection: sqlite3.Connection,
    *,
    enterprise_name: str,
    year: int | None,
    batch: str,
    region: str,
    status: str,
    event_type: str,
    verified_only: bool,
    offset: int,
    limit: int,
) -> dict[str, object]:
    effective_event_type = event_type.strip() or "annual_published"
    annual_publication = effective_event_type == "annual_published"
    conditions = [
        "project_name IN ('浙江省专精特新中小企业','专精特新中小企业')",
        "source_kinds_json LIKE '%\"lifecycle_manifest\"%'",
    ]
    _append_enterprise_subject_filter(connection, conditions)
    parameters: list[object] = []
    if annual_publication:
        placeholders = ",".join("?" for _ in ANNUAL_PUBLICATION_EVENT_TYPES)
        conditions.append(f"event_type IN ({placeholders})")
        parameters.extend(ANNUAL_PUBLICATION_EVENT_TYPES)
    else:
        conditions.append("event_type=?")
        parameters.append(effective_event_type)
    _append_like("enterprise_name_at_event", enterprise_name, conditions, parameters)
    _append_like("status", status, conditions, parameters)
    if year is not None:
        conditions.append("event_year=?")
        parameters.append(int(year))
    if batch.strip():
        conditions.append("batch=?")
        parameters.append(batch.strip())
    if region.strip():
        pattern = _escaped_like(region)
        conditions.append(
            "(recognition_province LIKE ? ESCAPE '\\' OR recognition_city LIKE ? ESCAPE '\\' "
            "OR recognition_county LIKE ? ESCAPE '\\')"
        )
        parameters.extend((pattern, pattern, pattern))
    if verified_only:
        conditions.append("evidence_status<>''")
    where = " AND ".join(conditions)
    rows = connection.execute(
        f"""
        SELECT * FROM enterprise_recognition_events
        WHERE {where}
        ORDER BY event_year DESC,batch,recognition_city,enterprise_name_at_event,id
        """,
        parameters,
    ).fetchall()
    if annual_publication:
        rows = _dedupe_annual_event_rows(rows)
    total = len(rows)
    tiers = Counter(
        _provincial_event_source_tier(str(row["evidence_status"]), str(row["event_type"]))
        for row in rows
    )
    official = sum(
        _provincial_event_source_tier(str(row["evidence_status"]), str(row["event_type"]))
        == "official_final"
        for row in rows
    )
    results: list[dict[str, object]] = []
    for row in rows[offset : offset + limit]:
        item = dict(row)
        tier = _provincial_event_source_tier(
            str(item["evidence_status"]), str(item["event_type"])
        )
        is_final = tier == "official_final"
        results.append(
            {
                "fact_id": f"provincial-specialized-sme:{item['event_uid']}",
                "event_uid": item["event_uid"],
                "document_id": 0,
                "list_type": "provincial_specialized_sme",
                "canonical_project_name": "浙江省专精特新中小企业",
                "enterprise_name": item["enterprise_name_at_event"],
                "product_name": item["product_name"],
                "policy_year": item["event_year"],
                "cohort_year": item["cohort_year"],
                "batch": item["batch"],
                "region": "/".join(
                    value
                    for value in (
                        item["recognition_province"],
                        item["recognition_city"],
                        item["recognition_county"],
                    )
                    if value
                ),
                "province": item["recognition_province"],
                "city": item["recognition_city"],
                "county": item["recognition_county"],
                "list_status": item["status"],
                "event_type": item["event_type"],
                "event_scope": item["event_scope"],
                "verification_status": item["evidence_status"],
                "effective_recognition": is_final
                and item["event_type"] in {"recognition", "review_passed"},
                "official_match": is_final,
                "source_tier": tier,
                "source_grade": tier,
                "confidence": "high" if tier != "unverified" else "medium",
                "source_title": item["source_title"],
                "source_paths": _json_list(item["source_paths_json"]),
                "source_urls": _json_list(item["source_urls_json"]),
                "sequence_numbers": _json_list(item["sequence_numbers_json"]),
                "identity_key": item["identity_key"],
            }
        )
    if annual_publication:
        coverage = _event_source_coverage(
            connection,
            project_name="浙江省专精特新中小企业",
            year=year,
            batch=batch,
            region=region,
            event_types=ANNUAL_PUBLICATION_EVENT_TYPES,
        )
    else:
        coverage = _provincial_coverage(
            connection,
            year=year,
            batch=batch,
            region=region,
            event_type=effective_event_type,
        )
    return _response(
        list_type="provincial_specialized_sme",
        table="enterprise_recognition_events",
        rule="event-source-manifest-v2",
        filters={
            "enterprise_name": enterprise_name.strip(),
            "year": year,
            "batch": batch.strip(),
            "region": region.strip(),
            "status": status.strip(),
            "event_type": effective_event_type,
            "verified_only": verified_only,
        },
        results=results,
        total=total,
        official_match_count=official,
        verified_count=total - tiers.get("unverified", 0),
        pending_count=tiers.get("unverified", 0),
        excluded_count=0,
        source_tiers=tiers,
        offset=offset,
        limit=limit,
        coverage=coverage,
        warnings=(
            [
                "年度名单仅包含当年发布的新认定与复核或复评通过事件；往年仍有效、变更、撤销和财政支持事件已排除。"
            ]
            if annual_publication
            else []
        ),
    )


def _three_first_facts(
    connection: sqlite3.Connection,
    *,
    enterprise_name: str,
    product_name: str,
    industry: str,
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
    _append_like("industry", industry, conditions, parameters)
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
    scope_conditions = list(conditions)
    scope_parameters = list(parameters)
    if verified_only or status.strip() != "platform_history":
        conditions.append("confidence<>'discovery_only'")
    where = " AND ".join(conditions)
    scope_where = " AND ".join(scope_conditions)
    excluded_discovery = int(
        connection.execute(
            f"""
            SELECT COUNT(*) FROM three_first_project_awards
            WHERE {scope_where} AND confidence='discovery_only'
            """,
            scope_parameters,
        ).fetchone()[0]
    )
    if status.strip() == "platform_history" and not verified_only:
        excluded_discovery = 0
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
                "industry": item["industry"],
                "product_name_status": item["product_name_status"],
                "source_title": item["source_title"],
                "source_url": item["source_url"],
                "source_policy_id": item["source_policy_id"],
                "source_index_id": item["source_index_id"],
                "evidence_semantics": item["evidence_semantics"],
            }
        )
    official_scope_complete = total > 0 and official == total
    completeness_allowed = pending == 0 and (
        excluded_discovery == 0 or official_scope_complete
    )
    warnings: list[str] = []
    if product_name.strip():
        warnings.append(
            "产品名称筛选采用字面包含匹配，不等同于同类产品语义匹配；"
            "同类判断还需核对项目类型、product_category、industry、年度和名单状态。"
        )
    if excluded_discovery:
        warnings.append(
            f"默认结果已排除 {excluded_discovery} 条企策平台历史线索；"
            "这些线索的年份不直接等同于当年正式认定。"
        )
    return _response(
        list_type="three_first",
        table="three_first_project_awards",
        rule="product-level-source-priority-v1",
        filters={
            "enterprise_name": enterprise_name.strip(),
            "product_name": product_name.strip(),
            "industry": industry.strip(),
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
        excluded_count=excluded_discovery,
        source_tiers=source_tiers,
        offset=offset,
        limit=limit,
        warnings=warnings,
        coverage={
            "status": "accepted_source_scope" if completeness_allowed else "incomplete",
            "completeness_claim_allowed": completeness_allowed,
            "scope": "user_approved_three_first_product_sources",
            "cells": [
                {
                    "project_name": project_name.strip(),
                    "year": year,
                    "region": region.strip(),
                    "accepted_product_rows": verified,
                    "discovery_rows_included": pending,
                    "discovery_rows_excluded": excluded_discovery,
                    "official_scope_complete": official_scope_complete,
                    "product_match_semantics": (
                        "literal_substring_only" if product_name.strip() else "not_applicable"
                    ),
                }
            ],
        },
    )


def query_authoritative_list_facts(
    connection: sqlite3.Connection,
    *,
    list_type: str,
    enterprise_name: str = "",
    product_name: str = "",
    industry: str = "",
    project_name: str = "",
    year: int | None = None,
    batch: str = "",
    region: str = "",
    status: str = "",
    event_type: str = "",
    verified_only: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    list_type = normalize_authoritative_list_type(list_type)
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
            event_type=event_type,
            verified_only=verified_only,
            offset=bounded_offset,
            limit=bounded_limit,
        )
    if list_type == "provincial_specialized_sme":
        return _provincial_specialized_sme_facts(
            connection,
            enterprise_name=enterprise_name,
            year=year,
            batch=batch,
            region=region,
            status=status,
            event_type=event_type,
            verified_only=verified_only,
            offset=bounded_offset,
            limit=bounded_limit,
        )
    return _three_first_facts(
        connection,
        enterprise_name=enterprise_name,
        product_name=product_name,
        industry=industry,
        project_name=project_name,
        year=year,
        region=region,
        status=status,
        verified_only=verified_only,
        offset=bounded_offset,
        limit=bounded_limit,
    )

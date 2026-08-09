"""Query the disclosure-safe enterprise identity lineage graph.

The graph is built during the index release.  This module deliberately reads
only the public graph tables and returns the stable source label ``共创研究院知识库``;
provider identifiers or provider names never leave the portal API/MCP layer.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from typing import Any


PUBLIC_SOURCE = "共创研究院知识库"
USCC_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
PEER_PROJECTS = frozenset(
    {
        "浙江省专精特新中小企业",
        "专精特新中小企业",
        "国家专精特新“小巨人”企业",
    }
)


def normalize_identity_name(value: str) -> str:
    return re.sub(
        r"[\s·•・,，。;；:：()（）【】\[\]\\\"“”'‘’\-—_]",
        "",
        str(value or ""),
    ).lower()


def normalize_identity_query(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    code = re.sub(r"\s+", "", raw).upper()
    if USCC_PATTERN.fullmatch(code):
        return "unified_social_credit_code", code
    return "name", normalize_identity_name(raw)


def _table_available(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='enterprise_identity_lineage_nodes'"
        ).fetchone()
        and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='enterprise_identity_lineage_edges'"
        ).fetchone()
    )


def _json_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _unified_profile_table_available(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='enterprise_unified_digital_identities'"
        ).fetchone()
    )


def _public_business_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "identity_key": str(row["identity_key"]),
        "current_name": str(row["current_name"]),
        "unified_social_credit_code": str(row["unified_social_credit_code"] or ""),
        "province": str(row["province"] or ""),
        "city": str(row["city"] or ""),
        "county": str(row["county"] or ""),
        "registration_status": str(row["registration_status"] or ""),
        "founded_date": str(row["founded_date"] or ""),
        "registered_capital": str(row["registered_capital"] or ""),
        "company_type": str(row["company_type"] or ""),
        "industry_levels": [
            value
            for value in (
                str(row["industry_level_1"] or ""),
                str(row["industry_level_2"] or ""),
                str(row["industry_level_3"] or ""),
            )
            if value
        ],
        "company_introduction": str(row["company_introduction"] or ""),
        "business_scope": str(row["business_scope"] or ""),
        "main_product_tags": _json_list(row["main_product_tags_json"]),
        "industry_track_tags": _json_list(row["industry_track_tags_json"]),
        "ip_statistics": _json_object(row["ip_statistics_json"]),
        "honors": _json_list(row["honors_json"]),
        "recognition_projects": _json_list(row["recognition_projects_json"]),
        "three_first_products": [
            item
            for item in json.loads(str(row["three_first_products_json"] or "[]"))
            if isinstance(item, dict)
        ],
        "identity_verification_status": str(row["identity_verification_status"]),
        "business_profile_evidence_status": str(
            row["business_profile_evidence_status"]
        ),
        "recognition_evidence_status": str(row["recognition_evidence_status"]),
        "peer_comparison_ready": bool(row["peer_comparison_ready"]),
        "three_first_product_enriched": bool(row["three_first_product_enriched"]),
        "source": PUBLIC_SOURCE,
    }


def _select_unified_profile(
    connection: sqlite3.Connection,
    master_identity_key: str,
    unified_social_credit_code: str,
    current_name: str,
) -> sqlite3.Row | None:
    if not _unified_profile_table_available(connection):
        return None
    return connection.execute(
        """
        SELECT * FROM enterprise_unified_digital_identities
        WHERE identity_key=?
           OR (?<>'' AND unified_social_credit_code=?)
           OR (?<>'' AND current_name=?)
        ORDER BY CASE
          WHEN identity_key=? THEN 0
          WHEN unified_social_credit_code=? AND ?<>'' THEN 1
          ELSE 2 END,
          peer_comparison_ready DESC, identity_key
        LIMIT 1
        """,
        (
            master_identity_key,
            unified_social_credit_code,
            unified_social_credit_code,
            current_name,
            current_name,
            master_identity_key,
            unified_social_credit_code,
            unified_social_credit_code,
        ),
    ).fetchone()


def _peer_comparison(
    connection: sqlite3.Connection,
    target: sqlite3.Row,
    limit: int = 10,
) -> dict[str, Any]:
    if not bool(target["peer_comparison_ready"]):
        return {
            "ready": False,
            "reason": "当前企业尚无可用于同口径比较的主营产品或行业画像",
            "dimensions": [],
            "peers": [],
            "source": PUBLIC_SOURCE,
        }
    if not connection.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='enterprise_peer_comparison_terms'"
    ).fetchone():
        return {
            "ready": False,
            "reason": "同行对比主题索引尚未发布",
            "dimensions": [],
            "peers": [],
            "source": PUBLIC_SOURCE,
        }
    target_key = str(target["identity_key"])
    target_terms = connection.execute(
        """
        SELECT term_type,term,normalized_term
        FROM enterprise_peer_comparison_terms
        WHERE identity_key=? ORDER BY term_type,normalized_term
        """,
        (target_key,),
    ).fetchall()
    normalized_terms = list(
        dict.fromkeys(str(row["normalized_term"]) for row in target_terms)
    )
    if not normalized_terms:
        return {
            "ready": False,
            "reason": "当前企业没有可比较的主营产品或行业主题词",
            "dimensions": [],
            "peers": [],
            "source": PUBLIC_SOURCE,
        }
    placeholders = ",".join("?" for _ in normalized_terms)
    rows = connection.execute(
        f"""
        SELECT t.identity_key,t.term_type,t.term,t.normalized_term,
               u.current_name,u.unified_social_credit_code,u.province,u.city,
               u.company_introduction,u.business_scope,u.main_product_tags_json,
               u.industry_track_tags_json,u.recognition_projects_json,
               u.business_profile_evidence_status,u.recognition_evidence_status
        FROM enterprise_peer_comparison_terms AS t
        JOIN enterprise_unified_digital_identities AS u
          ON u.identity_key=t.identity_key
        WHERE t.normalized_term IN ({placeholders})
          AND t.identity_key<>? AND u.peer_comparison_ready=1
        ORDER BY t.identity_key,t.term_type,t.normalized_term
        """,
        (*normalized_terms, target_key),
    ).fetchall()
    matches: defaultdict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        projects = set(_json_list(row["recognition_projects_json"])) & PEER_PROJECTS
        if not projects:
            continue
        matches[str(row["identity_key"])].append(row)
    weights = {"main_product": 5, "industry_track": 3, "industry_level": 1}
    peers: list[dict[str, Any]] = []
    for identity_key, matched in matches.items():
        first = matched[0]
        shared = list(
            {
                (str(row["term_type"]), str(row["term"]), str(row["normalized_term"]))
                for row in matched
            }
        )
        score = sum(weights.get(term_type, 1) for term_type, _, _ in shared)
        peers.append(
            {
                "identity_key": identity_key,
                "name": str(first["current_name"]),
                "unified_social_credit_code": str(
                    first["unified_social_credit_code"] or ""
                ),
                "province": str(first["province"] or ""),
                "city": str(first["city"] or ""),
                "company_introduction": str(first["company_introduction"] or ""),
                "business_scope": str(first["business_scope"] or ""),
                "main_product_tags": _json_list(first["main_product_tags_json"]),
                "industry_track_tags": _json_list(first["industry_track_tags_json"]),
                "recognition_projects": _json_list(first["recognition_projects_json"]),
                "business_profile_evidence_status": str(
                    first["business_profile_evidence_status"]
                ),
                "recognition_evidence_status": str(
                    first["recognition_evidence_status"]
                ),
                "shared_dimensions": [
                    {"type": term_type, "term": term}
                    for term_type, term, _ in sorted(shared)
                ],
                "similarity_score": score,
                "source": PUBLIC_SOURCE,
            }
        )
    peers.sort(
        key=lambda item: (
            -int(item["similarity_score"]),
            str(item["name"]),
            str(item["identity_key"]),
        )
    )
    dimensions = sorted(
        {
            str(row["term_type"])
            for row in target_terms
            if str(row["term_type"]) in weights
        }
    )
    return {
        "ready": True,
        "dimensions": dimensions,
        "peers": peers[: max(1, min(int(limit), 20))],
        "candidate_count": len(peers),
        "source": PUBLIC_SOURCE,
        "evidence_note": "企业画像证据等级与名单认定证据分别保留，候选画像不会升级为官方认定",
    }


def _scope_status(connection: sqlite3.Connection) -> dict[str, Any]:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='enterprise_identity_resolution_audit'"
    ).fetchone():
        return {}
    rows = connection.execute(
        """
        SELECT scope_key,scope_label,total_subjects,verified_subjects,pending_subjects,
               with_unified_social_credit_code,without_unified_social_credit_code,
               note,source
        FROM enterprise_identity_resolution_audit
        ORDER BY scope_key
        """
    ).fetchall()
    return {
        str(row["scope_key"]): {
            "scope_label": str(row["scope_label"]),
            "total_subjects": int(row["total_subjects"]),
            "verified_subjects": int(row["verified_subjects"]),
            "pending_subjects": int(row["pending_subjects"]),
            "with_unified_social_credit_code": int(row["with_unified_social_credit_code"]),
            "without_unified_social_credit_code": int(row["without_unified_social_credit_code"]),
            "note": str(row["note"] or ""),
            "source": PUBLIC_SOURCE,
        }
        for row in rows
    }


def _profile_coverage(connection: sqlite3.Connection) -> dict[str, Any]:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='enterprise_unified_identity_coverage'"
    ).fetchone():
        return {}
    rows = connection.execute(
        """
        SELECT scope_key,scope_label,total_subjects,ready_subjects,
               missing_profile_subjects,note
        FROM enterprise_unified_identity_coverage ORDER BY scope_key
        """
    ).fetchall()
    return {
        str(row["scope_key"]): {
            "scope_label": str(row["scope_label"]),
            "total_subjects": int(row["total_subjects"]),
            "ready_subjects": int(row["ready_subjects"]),
            "missing_profile_subjects": int(row["missing_profile_subjects"]),
            "note": str(row["note"]),
            "source": PUBLIC_SOURCE,
        }
        for row in rows
    }


def _conflict_path(
    path_type: str,
    description: str,
    nodes: list[dict[str, str]],
    relations: list[str],
) -> dict[str, Any]:
    return {
        "path_type": path_type,
        "description": description,
        "nodes": nodes,
        "relations": relations,
        "source": PUBLIC_SOURCE,
    }


def lookup_identity_lineage(
    connection: sqlite3.Connection,
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Reverse lookup an enterprise by current/former name or unified code.

    Exact matches are preferred.  A name fallback uses a bounded prefix/contains
    search to support punctuation and wording differences without returning the
    entire identity graph.  Every result includes the path used to reach the
    subject and any ambiguity or missing-code conflict discovered in the graph.
    """

    kind, normalized_query = normalize_identity_query(query)
    if not normalized_query:
        raise ValueError("反查条件不能为空")
    bounded_limit = max(1, min(int(limit), 50))
    if not _table_available(connection):
        raise RuntimeError("企业身份血缘索引尚未发布")

    if kind == "unified_social_credit_code":
        matched_nodes = connection.execute(
            """
            SELECT node_id,master_identity_key,node_type,node_value,normalized_value,
                   verification_status
            FROM enterprise_identity_lineage_nodes
            WHERE node_type='unified_social_credit_code' AND normalized_value=?
            ORDER BY master_identity_key LIMIT ?
            """,
            (normalized_query.lower(), bounded_limit),
        ).fetchall()
        match_mode = "unified_social_credit_code"
    else:
        matched_nodes = connection.execute(
            """
            SELECT node_id,master_identity_key,node_type,node_value,normalized_value,
                   verification_status
            FROM enterprise_identity_lineage_nodes
            WHERE node_type IN ('current_name','former_name')
              AND normalized_value=?
            ORDER BY master_identity_key,node_type,node_value LIMIT ?
            """,
            (normalized_query, bounded_limit),
        ).fetchall()
        if not matched_nodes:
            escaped = normalized_query.replace("%", "\\%").replace("_", "\\_")
            matched_nodes = connection.execute(
                """
                SELECT node_id,master_identity_key,node_type,node_value,normalized_value,
                       verification_status
                FROM enterprise_identity_lineage_nodes
                WHERE node_type IN ('current_name','former_name')
                  AND normalized_value LIKE ? ESCAPE '\\'
                ORDER BY CASE WHEN node_type='current_name' THEN 0 ELSE 1 END,
                         master_identity_key,node_value LIMIT ?
                """,
                (f"%{escaped}%", bounded_limit),
            ).fetchall()
        match_mode = "current_name_or_former_name"

    if not matched_nodes:
        return {
            "query": str(query or "").strip(),
            "query_type": kind,
            "normalized_query": normalized_query,
            "source": PUBLIC_SOURCE,
            "result_count": 0,
            "results": [],
            "conflict_summary": [],
            "coverage": _scope_status(connection),
            "profile_coverage": _profile_coverage(connection),
        }

    master_keys = list(dict.fromkeys(str(row["master_identity_key"]) for row in matched_nodes))
    placeholders = ",".join("?" for _ in master_keys)
    node_rows = connection.execute(
        f"""
        SELECT node_id,master_identity_key,node_type,node_value,normalized_value,verification_status
        FROM enterprise_identity_lineage_nodes
        WHERE master_identity_key IN ({placeholders})
        ORDER BY master_identity_key,node_type,node_value
        """,
        master_keys,
    ).fetchall()
    edge_rows = connection.execute(
        f"""
        SELECT edge_id,master_identity_key,from_node_id,to_node_id,from_node_type,to_node_type,
               from_value,to_value,relation_type,unified_social_credit_code,verification_status
        FROM enterprise_identity_lineage_edges
        WHERE master_identity_key IN ({placeholders})
        ORDER BY master_identity_key,relation_type,to_value
        """,
        master_keys,
    ).fetchall()

    nodes_by_master: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in node_rows:
        nodes_by_master[str(row["master_identity_key"])].append(row)
    edges_by_master: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in edge_rows:
        edges_by_master[str(row["master_identity_key"])].append(row)

    # Name/code collisions are detected across the whole graph, not just the
    # returned slice, so a result never hides an ambiguous subject.
    name_subjects: dict[str, set[str]] = defaultdict(set)
    name_values: dict[str, set[str]] = defaultdict(set)
    code_subjects: dict[str, set[str]] = defaultdict(set)
    for row in connection.execute(
        """
        SELECT master_identity_key,node_type,node_value,normalized_value
        FROM enterprise_identity_lineage_nodes
        WHERE node_type IN ('current_name','former_name','unified_social_credit_code')
        """
    ).fetchall():
        master = str(row["master_identity_key"])
        if row["node_type"] in {"current_name", "former_name"}:
            name_subjects[str(row["normalized_value"])].add(master)
            name_values[str(row["normalized_value"])].add(str(row["node_value"]))
        else:
            code_subjects[str(row["normalized_value"]).lower()].add(master)

    results: list[dict[str, Any]] = []
    all_conflicts: list[dict[str, Any]] = []
    for matched in matched_nodes:
        master = str(matched["master_identity_key"])
        master_nodes = nodes_by_master[master]
        master_edges = edges_by_master[master]
        current_names = [
            str(row["node_value"])
            for row in master_nodes
            if row["node_type"] == "current_name"
        ]
        former_names = [
            str(row["node_value"])
            for row in master_nodes
            if row["node_type"] == "former_name"
        ]
        codes = list(
            dict.fromkeys(
                str(row["node_value"])
                for row in master_nodes
                if row["node_type"] == "unified_social_credit_code"
            )
        )
        merged_keys = [
            str(row["node_value"])
            for row in master_nodes
            if row["node_type"] == "merged_subject"
        ]
        status = str(matched["verification_status"] or "")
        paths: list[dict[str, Any]] = []
        matched_node = {
            "node_id": str(matched["node_id"]),
            "node_type": str(matched["node_type"]),
            "value": str(matched["node_value"]),
        }
        subject_node = {
            "node_id": f"subject:{master}",
            "node_type": "identity_subject",
            "value": master,
        }
        paths.append(
            _conflict_path(
                "matched_identity_path",
                "查询值通过身份主体关联到当前名、曾用名或统一社会信用代码",
                [matched_node, subject_node],
                [str(matched["node_type"])],
            )
        )
        if kind == "name":
            same_name_subjects = sorted(name_subjects.get(normalized_query, set()))
            if len(same_name_subjects) > 1:
                path = _conflict_path(
                    "same_name_multiple_subjects",
                    "同一名称对应多个身份主体，不能仅凭名称合并",
                    [
                        {"node_id": f"subject:{item}", "node_type": "identity_subject", "value": item}
                        for item in same_name_subjects
                    ],
                    ["name_match", "ambiguous_subject"],
                )
                paths.append(path)
                all_conflicts.append(path)
        if kind == "unified_social_credit_code":
            same_code_subjects = sorted(code_subjects.get(normalized_query.lower(), set()))
            if len(same_code_subjects) > 1:
                path = _conflict_path(
                    "code_multiple_subjects",
                    "同一统一社会信用代码连接多个身份主体，需要人工处理合并边界",
                    [
                        {"node_id": f"subject:{item}", "node_type": "identity_subject", "value": item}
                        for item in same_code_subjects
                    ],
                    ["unified_social_credit_code", "ambiguous_subject"],
                )
                paths.append(path)
                all_conflicts.append(path)
        if len(codes) > 1:
            path = _conflict_path(
                "subject_multiple_codes",
                "同一身份主体存在多个统一社会信用代码",
                [subject_node]
                + [
                    {"node_id": f"credit-code:{code}", "node_type": "unified_social_credit_code", "value": code}
                    for code in codes
                ],
                ["unified_social_credit_code", "conflict"],
            )
            paths.append(path)
            all_conflicts.append(path)
        if not codes:
            path = _conflict_path(
                "missing_unified_social_credit_code",
                "当前知识库没有可闭合的统一社会信用代码，不能凭名称猜测代码",
                [subject_node]
                + [
                    {"node_id": f"current-name:{master}", "node_type": "current_name", "value": name}
                    for name in current_names
                ],
                ["current_name", "pending_business_identity"],
            )
            paths.append(path)
            all_conflicts.append(path)
        if merged_keys:
            path = _conflict_path(
                "merged_subject",
                "该主体存在合并主体投影，检索结果保留主身份与合并路径",
                [subject_node]
                + [
                    {"node_id": f"merged-subject:{item}", "node_type": "merged_subject", "value": item}
                    for item in merged_keys
                ],
                ["merged_subject"],
            )
            paths.append(path)

        result_item: dict[str, Any] = {
            "master_identity_key": master,
            "identity_key": master,
            "current_name": current_names[0] if current_names else "",
            "former_names": former_names,
            "unified_social_credit_code": codes[0] if len(codes) == 1 else codes,
            "merged_master_identity_keys": merged_keys,
            "entity_resolution_status": status,
            "matched_by": str(matched["node_type"]),
            "matched_value": str(matched["node_value"]),
            "conflict_paths": paths,
            "source": PUBLIC_SOURCE,
        }
        unified_profile = _select_unified_profile(
            connection,
            master,
            codes[0] if len(codes) == 1 else "",
            current_names[0] if current_names else "",
        )
        if unified_profile is not None:
            result_item["business_profile"] = _public_business_profile(unified_profile)
            result_item["peer_comparison"] = _peer_comparison(
                connection, unified_profile
            )
        results.append(result_item)

    # Deduplicate name aliases that point to the same subject while preserving
    # the strongest (exact current-name before former-name) match.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in results:
        key = (str(row["master_identity_key"]), str(row["matched_by"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    return {
        "query": str(query or "").strip(),
        "query_type": kind,
        "normalized_query": normalized_query,
        "match_mode": match_mode,
        "source": PUBLIC_SOURCE,
        "result_count": len(deduped),
        "results": deduped[:bounded_limit],
        "conflict_summary": list(
            {
                "path_type": item["path_type"],
                "description": item["description"],
                "source": PUBLIC_SOURCE,
            }
            for item in {
                (str(path["path_type"]), str(path["description"])): path
                for path in all_conflicts
            }.values()
        ),
        "coverage": _scope_status(connection),
        "profile_coverage": _profile_coverage(connection),
    }


__all__ = ["lookup_identity_lineage", "normalize_identity_name", "normalize_identity_query"]

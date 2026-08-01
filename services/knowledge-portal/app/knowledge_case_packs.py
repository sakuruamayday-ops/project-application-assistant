from __future__ import annotations

import sqlite3
from typing import Any


CASE_PACK_SCHEMA_VERSION = "2.0"


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def case_pack_capability(connection: sqlite3.Connection) -> dict[str, object]:
    required = {"case_packs", "case_pack_documents", "document_relations"}
    available = {table for table in required if table_exists(connection, table)}
    return {
        "knowledge_schema_version": CASE_PACK_SCHEMA_VERSION if available == required else "1.0",
        "case_pack_capability": available == required,
        "case_pack_count": (
            int(connection.execute("SELECT COUNT(*) FROM case_packs").fetchone()[0])
            if available == required
            else 0
        ),
    }


def query_case_packs(
    connection: sqlite3.Connection,
    *,
    project_id: str = "",
    query: str = "",
    year: int | None = None,
    industry: str = "",
    enterprise_scale: str = "",
    section: str = "",
    limit: int = 5,
) -> dict[str, object]:
    capability = case_pack_capability(connection)
    if not capability["case_pack_capability"]:
        return {
            **capability,
            "status": "unavailable",
            "reason": "当前索引尚未构建案例包关系表，请先发布 V1.4.4 索引。",
            "results": [],
        }
    conditions = ["1=1"]
    parameters: list[Any] = []
    for field, value in (
        ("p.project_id", project_id),
        ("p.industry", industry),
        ("p.enterprise_scale", enterprise_scale),
    ):
        normalized = value.strip()
        if normalized:
            conditions.append(f"{field} = ?")
            parameters.append(normalized)
    if year is not None:
        conditions.append("p.year = ?")
        parameters.append(year)
    normalized_query = query.strip()
    if normalized_query:
        conditions.append("(p.title LIKE ? OR p.enterprise_name LIKE ? OR p.project_name LIKE ?)")
        like = f"%{normalized_query}%"
        parameters.extend((like, like, like))
    rows = connection.execute(
        f"""
        SELECT p.* FROM case_packs p
        WHERE {' AND '.join(conditions)}
        ORDER BY p.verification_status='confirmed' DESC,
                 COALESCE(p.year,0) DESC,p.document_count DESC,p.case_pack_id
        LIMIT ?
        """,
        (*parameters, max(1, min(limit, 10))),
    ).fetchall()
    results: list[dict[str, object]] = []
    for row in rows:
        pack = dict(row)
        document_conditions = ["cpd.case_pack_id = ?"]
        document_parameters: list[Any] = [pack["case_pack_id"]]
        if section.strip():
            document_conditions.append("(cpd.document_type = ? OR cpd.evidence_type = ?)")
            document_parameters.extend((section.strip(), section.strip()))
        documents = [
            dict(item)
            for item in connection.execute(
                f"""
                SELECT d.id AS document_id,d.title,d.source,d.document_role,
                       d.validity_status,d.verification_status,
                       cpd.document_type,cpd.evidence_type,cpd.sequence
                FROM case_pack_documents cpd
                JOIN documents d ON d.id=cpd.document_id
                WHERE {' AND '.join(document_conditions)}
                ORDER BY CASE cpd.document_type
                    WHEN 'application' THEN 1 WHEN 'construction_plan' THEN 2
                    WHEN 'technical_plan' THEN 3 ELSE 9 END,cpd.sequence,d.id
                """,
                document_parameters,
            ).fetchall()
        ]
        pack["documents"] = documents
        pack["reference_boundary"] = (
            "案例仅用于结构、指标组织和证据类型参考；不得把案例企业事实复制给当前客户。"
        )
        results.append(pack)
    return {
        **capability,
        "status": "ok",
        "filters": {
            "project_id": project_id,
            "query": query,
            "year": year,
            "industry": industry,
            "enterprise_scale": enterprise_scale,
            "section": section,
        },
        "result_count": len(results),
        "results": results,
    }

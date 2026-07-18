from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


DEFAULT_DATABASE = Path(
    os.environ.get(
        "JIAOTANG_CONTENT_DATABASE",
        Path.cwd() / "cloud_package_index/knowledge_content.sqlite3",
    )
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询项目申报助手知识库索引")
    parser.add_argument("query")
    parser.add_argument(
        "--mode", choices=("passage", "enterprise"), default="passage"
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--layers", help="逗号分隔的一级目录，例如 10_政策与目录,20_申报指南与规则")
    parser.add_argument("--limit", type=int, default=8)
    return parser.parse_args()


def fts_expression(query: str, operator: str) -> str:
    terms = [term.strip('"') for term in query.split() if term.strip('"')]
    return f" {operator} ".join(f'"{term}"' for term in terms)


def layer_sql(layers: list[str]) -> tuple[str, list[str]]:
    if not layers:
        return "", []
    clauses = ["source LIKE ?" for _ in layers]
    return " AND (" + " OR ".join(clauses) + ")", [f"{layer}/%" for layer in layers]


def search_passages(
    connection: sqlite3.Connection,
    query: str,
    layers: list[str],
    limit: int,
) -> list[dict[str, object]]:
    filter_sql, filter_params = layer_sql(layers)
    sql = f"""
        SELECT document_id, chunk_number, title,
               snippet(document_chunks_fts, 3, '<mark>', '</mark>', '…', 48) AS excerpt,
               source, bm25(document_chunks_fts) AS score
        FROM document_chunks_fts
        WHERE document_chunks_fts MATCH ?{filter_sql}
        ORDER BY score
        LIMIT ?
    """
    for operator in ("AND", "OR"):
        expression = fts_expression(query, operator)
        if not expression:
            return []
        rows = connection.execute(
            sql, [expression, *filter_params, max(1, min(limit, 50))]
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]
    return []


def search_enterprises(
    connection: sqlite3.Connection,
    query: str,
    layers: list[str],
    limit: int,
) -> list[dict[str, object]]:
    params: list[object] = [query, f"%{query}%"]
    filter_sql = ""
    if layers:
        filter_sql = " AND (" + " OR ".join("d.source LIKE ?" for _ in layers) + ")"
        params.extend(f"{layer}/%" for layer in layers)
    params.append(max(1, min(limit, 100)))
    rows = connection.execute(
        f"""
        SELECT e.enterprise_name, e.sequence_no, e.context,
               d.id AS document_id, d.title, d.source, d.updated_at
        FROM enterprise_mentions e
        JOIN documents d ON d.id = e.document_id
        WHERE (e.enterprise_name = ? OR e.enterprise_name LIKE ?){filter_sql}
        ORDER BY CASE WHEN e.enterprise_name = ? THEN 0 ELSE 1 END,
                 d.updated_at DESC
        LIMIT ?
        """,
        [*params[:-1], query, params[-1]],
    ).fetchall()
    return [dict(row) for row in rows]


def main() -> None:
    args = parse_args()
    database = args.database.expanduser().resolve()
    layers = [layer.strip() for layer in (args.layers or "").split(",") if layer.strip()]
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        if args.mode == "enterprise":
            results = search_enterprises(connection, args.query.strip(), layers, args.limit)
        else:
            results = search_passages(connection, args.query.strip(), layers, args.limit)
    finally:
        connection.close()
    print(
        json.dumps(
            {"query": args.query, "mode": args.mode, "layers": layers, "results": results},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

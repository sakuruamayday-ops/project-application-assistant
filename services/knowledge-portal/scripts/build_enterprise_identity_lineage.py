#!/usr/bin/env python3
"""Build the public enterprise identity lineage projection.

The timeline builder already stores the identity profile and alias tables.  This
step turns those two tables into an explicit, queryable graph while keeping the
public source label stable.  Internal alias provenance remains in
``enterprise_identity_names.source`` for audit; the JSONL projection and graph
tables deliberately expose only ``焦糖知识库`` as their source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


PUBLIC_SOURCE = "焦糖知识库"
SCHEMA_VERSION = "jiaotang-enterprise-identity-lineage-v1"
USCC_PATTERN = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建企业身份血缘图及公开投影")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--knowledge-identities",
        type=Path,
        default=None,
        help="焦糖知识库企业基础数字身份证 JSONL 文件或目录",
    )
    return parser.parse_args()


def normalize_name(value: str) -> str:
    return re.sub(r"[\s·•・,，。;；:：()（）【】\[\]\\\"“”'‘’\-—_]", "", value or "").lower()


def stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join((prefix, *[str(part) for part in parts]))
    return f"{prefix}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
    return rows


def snapshot_paths(path: Path | None) -> list[Path]:
    if path is None or not path.exists():
        return []
    if path.is_dir():
        return sorted(path.glob("*.jsonl"))
    return [path]


def load_identity_snapshot(path: Path | None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Index the disclosure-safe identity snapshot by code and normalized name."""
    by_code: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    paths = snapshot_paths(path)
    if len(paths) > 1:
        raise RuntimeError(f"焦糖知识库身份快照数量必须为 1，实际为 {len(paths)}：{path}")
    for row in read_jsonl(paths[0]) if paths else []:
        code = str(row.get("unified_social_credit_code") or "").strip().upper()
        if not USCC_PATTERN.fullmatch(code):
            code = ""
        if code:
            by_code[code] = row
        names = [
            str(row.get("current_name") or ""),
            *[str(item) for item in row.get("recognition_names", []) if str(item)],
            *[str(item) for item in row.get("former_names", []) if str(item)],
        ]
        for name in names:
            normalized = normalize_name(name)
            if normalized:
                by_name[normalized] = row
    return by_code, by_name


def _json_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def select_snapshot(
    profile: sqlite3.Row,
    by_code: dict[str, dict[str, Any]],
    by_name: dict[str, dict[str, Any]],
    aliases: list[sqlite3.Row],
) -> dict[str, Any] | None:
    code = str(profile["unified_social_credit_code"] or "").upper()
    if code and code in by_code:
        return by_code[code]
    names = [str(profile["current_name"] or "")]
    names.extend(str(row["alias_name"] or "") for row in aliases)
    for name in names:
        candidate = by_name.get(normalize_name(name))
        if candidate is not None:
            return candidate
    return None


def _node(
    *,
    node_id: str,
    node_type: str,
    value: str,
    master_identity_key: str,
    verification_status: str,
) -> dict[str, str]:
    return {
        "node_id": node_id,
        "node_type": node_type,
        "value": value,
        "normalized_value": normalize_name(value),
        "master_identity_key": master_identity_key,
        "verification_status": verification_status,
        "source": PUBLIC_SOURCE,
    }


def build_lineage_rows(database: Path, knowledge_identities: Path | None) -> list[dict[str, Any]]:
    by_code, by_name = load_identity_snapshot(knowledge_identities)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    profiles = connection.execute(
        "SELECT * FROM enterprise_identity_profiles ORDER BY identity_key"
    ).fetchall()
    alias_rows = connection.execute(
        """
        SELECT identity_key,alias_name,alias_type,valid_from,valid_to
        FROM enterprise_identity_names
        ORDER BY identity_key,alias_type,alias_name
        """
    ).fetchall()
    connection.close()
    aliases_by_identity: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in alias_rows:
        aliases_by_identity[str(row["identity_key"])].append(row)

    output: list[dict[str, Any]] = []
    for profile in profiles:
        identity_key = str(profile["identity_key"] or "")
        aliases = aliases_by_identity.get(identity_key, [])
        snapshot = select_snapshot(profile, by_code, by_name, aliases)
        master_key = str((snapshot or {}).get("master_identity_key") or identity_key)
        merged_keys = _json_list((snapshot or {}).get("merged_master_identity_keys"))
        if not merged_keys:
            merged_keys = [master_key]
        merged_keys = list(dict.fromkeys(item for item in merged_keys if item))
        if master_key not in merged_keys:
            merged_keys.insert(0, master_key)

        current_name = str(profile["current_name"] or "")
        code = str(profile["unified_social_credit_code"] or "").strip().upper()
        if not USCC_PATTERN.fullmatch(code):
            code = ""
        former_names = [
            str(row["alias_name"] or "")
            for row in aliases
            if str(row["alias_type"] or "") == "former_name"
        ]
        former_names.extend(
            str(item)
            for item in (snapshot or {}).get("former_names", [])
            if str(item)
        )
        former_names = list(
            dict.fromkeys(
                name for name in former_names if name and name != current_name
            )
        )
        # A punctuation-only duplicate must not create two edges to one node.
        normalized_former_names: dict[str, str] = {}
        for name in former_names:
            normalized_former_names.setdefault(normalize_name(name), name)
        former_names = [
            name for normalized, name in normalized_former_names.items() if normalized
        ]
        verification_status = str(profile["verification_status"] or "")
        source_layers = {
            "knowledge_base": {
                "source_type": PUBLIC_SOURCE,
                "enterprise_identity_status": (
                    "verified"
                    if verification_status == "knowledge_verified"
                    else "pending"
                ),
            }
        }

        nodes: list[dict[str, str]] = []
        seen_nodes: set[str] = set()

        def add_node(node: dict[str, str]) -> str:
            if node["node_id"] not in seen_nodes:
                nodes.append(node)
                seen_nodes.add(node["node_id"])
            return node["node_id"]

        subject_id = add_node(
            _node(
                node_id=f"subject:{master_key}",
                node_type="identity_subject",
                value=master_key,
                master_identity_key=master_key,
                verification_status=verification_status,
            )
        )
        current_id = add_node(
            _node(
                node_id=stable_id("current-name", master_key, current_name),
                node_type="current_name",
                value=current_name,
                master_identity_key=master_key,
                verification_status=verification_status,
            )
        )
        edges: list[dict[str, str]] = []

        def add_edge(to_id: str, to_node: dict[str, str], relation: str) -> None:
            edges.append(
                {
                    "from_node_id": subject_id,
                    "to_node_id": to_id,
                    "from_node_type": "identity_subject",
                    "to_node_type": to_node["node_type"],
                    "from_value": master_key,
                    "to_value": to_node["value"],
                    "relation_type": relation,
                    "master_identity_key": master_key,
                    "unified_social_credit_code": code,
                    "verification_status": verification_status,
                    "source": PUBLIC_SOURCE,
                }
            )

        current_node = next(item for item in nodes if item["node_id"] == current_id)
        add_edge(current_id, current_node, "current_name")
        for name in former_names:
            node = _node(
                node_id=stable_id("former-name", master_key, normalize_name(name)),
                node_type="former_name",
                value=name,
                master_identity_key=master_key,
                verification_status=verification_status,
            )
            add_edge(add_node(node), node, "former_name")
        if code:
            node = _node(
                node_id=f"credit-code:{code}",
                node_type="unified_social_credit_code",
                value=code,
                master_identity_key=master_key,
                verification_status=verification_status,
            )
            add_edge(add_node(node), node, "unified_social_credit_code")
        for merged_key in merged_keys:
            if merged_key == master_key:
                continue
            node = _node(
                node_id=f"merged-subject:{merged_key}",
                node_type="merged_subject",
                value=merged_key,
                master_identity_key=master_key,
                verification_status=verification_status,
            )
            add_edge(add_node(node), node, "merged_subject")

        output.append(
            {
                "schema_version": SCHEMA_VERSION,
                "master_identity_key": master_key,
                "identity_key": identity_key,
                "current_name": current_name,
                "former_names": former_names,
                "unified_social_credit_code": code,
                "merged_master_identity_keys": merged_keys,
                "entity_resolution_status": verification_status,
                "source_layers": source_layers,
                "source": PUBLIC_SOURCE,
                "nodes": nodes,
                "edges": edges,
            }
        )
    return output


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def public_projection_rows(graph_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten graph edges for efficient JSONL/FTS retrieval.

    The SQLite node/edge tables keep the complete graph.  The public file is
    intentionally one small record per edge instead of one giant JSON object
    per subject, so a name lookup does not force the indexer to parse a 40 MB
    line or return an entire subject graph as one search excerpt.
    """
    rows: list[dict[str, Any]] = []
    for graph in graph_rows:
        for edge in graph["edges"]:
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "master_identity_key": graph["master_identity_key"],
                    "identity_key": graph["identity_key"],
                    "current_name": graph["current_name"],
                    "former_names": graph["former_names"],
                    "unified_social_credit_code": graph[
                        "unified_social_credit_code"
                    ],
                    "merged_master_identity_keys": graph[
                        "merged_master_identity_keys"
                    ],
                    "entity_resolution_status": graph[
                        "entity_resolution_status"
                    ],
                    "relation_type": edge["relation_type"],
                    "from_node_id": edge["from_node_id"],
                    "to_node_id": edge["to_node_id"],
                    "from_node_type": edge["from_node_type"],
                    "to_node_type": edge["to_node_type"],
                    "from_value": edge["from_value"],
                    "to_value": edge["to_value"],
                    "source_layers": graph["source_layers"],
                    "source": PUBLIC_SOURCE,
                }
            )
    return rows


def sanitize_public_alias_projection(output: Path) -> int:
    path = output / "浙江省企业名称历史.jsonl"
    if not path.exists():
        return 0
    rows = list(read_jsonl(path))
    for row in rows:
        row["source"] = PUBLIC_SOURCE
    _write_jsonl(path, rows)
    return len(rows)


def sanitize_public_profile_projection(output: Path) -> int:
    """Remove provider-specific identifiers from the canonical profile export."""
    path = output / "浙江省企业身份档案.jsonl"
    if not path.exists():
        return 0
    rows = list(read_jsonl(path))
    for row in rows:
        row.pop("tyc_company_id", None)
        row["identity_source"] = PUBLIC_SOURCE
    _write_jsonl(path, rows)
    return len(rows)


def write_database_graph(database: Path, rows: list[dict[str, Any]]) -> tuple[int, int]:
    nodes: dict[str, dict[str, str]] = {}
    edges: dict[str, dict[str, str]] = {}
    for graph in rows:
        for node in graph["nodes"]:
            nodes.setdefault(str(node["node_id"]), node)
        for edge in graph["edges"]:
            edge_id = stable_id(
                "edge",
                str(edge["master_identity_key"]),
                str(edge["relation_type"]),
                str(edge["to_node_id"]),
            )
            edges.setdefault(edge_id, {"edge_id": edge_id, **edge})

    connection = sqlite3.connect(database)
    connection.executescript(
        """
        DROP TABLE IF EXISTS enterprise_identity_lineage_edges;
        DROP TABLE IF EXISTS enterprise_identity_lineage_nodes;
        CREATE TABLE enterprise_identity_lineage_nodes(
            node_id TEXT PRIMARY KEY,
            master_identity_key TEXT NOT NULL,
            node_type TEXT NOT NULL,
            node_value TEXT NOT NULL,
            normalized_value TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL
        );
        CREATE TABLE enterprise_identity_lineage_edges(
            edge_id TEXT PRIMARY KEY,
            master_identity_key TEXT NOT NULL,
            from_node_id TEXT NOT NULL,
            to_node_id TEXT NOT NULL,
            from_node_type TEXT NOT NULL,
            to_node_type TEXT NOT NULL,
            from_value TEXT NOT NULL,
            to_value TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL
        );
        CREATE INDEX enterprise_identity_lineage_node_lookup_idx
            ON enterprise_identity_lineage_nodes(node_type,normalized_value);
        CREATE INDEX enterprise_identity_lineage_edge_master_idx
            ON enterprise_identity_lineage_edges(master_identity_key,relation_type);
        CREATE INDEX enterprise_identity_lineage_edge_code_idx
            ON enterprise_identity_lineage_edges(unified_social_credit_code);
        """
    )
    connection.executemany(
        """
        INSERT INTO enterprise_identity_lineage_nodes(
            node_id,master_identity_key,node_type,node_value,normalized_value,
            verification_status,source
        ) VALUES(?,?,?,?,?,?,?)
        """,
        [
            (
                node["node_id"],
                node["master_identity_key"],
                node["node_type"],
                node["value"],
                node["normalized_value"],
                node["verification_status"],
                PUBLIC_SOURCE,
            )
            for node in nodes.values()
        ],
    )
    connection.executemany(
        """
        INSERT INTO enterprise_identity_lineage_edges(
            edge_id,master_identity_key,from_node_id,to_node_id,from_node_type,
            to_node_type,from_value,to_value,relation_type,
            unified_social_credit_code,verification_status,source
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                edge["edge_id"],
                edge["master_identity_key"],
                edge["from_node_id"],
                edge["to_node_id"],
                edge["from_node_type"],
                edge["to_node_type"],
                edge["from_value"],
                edge["to_value"],
                edge["relation_type"],
                edge["unified_social_credit_code"],
                edge["verification_status"],
                PUBLIC_SOURCE,
            )
            for edge in edges.values()
        ],
    )
    connection.commit()
    connection.close()
    return len(nodes), len(edges)


def main() -> None:
    args = parse_args()
    args.database = args.database.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    graph_rows = build_lineage_rows(args.database, args.knowledge_identities)
    public_rows = public_projection_rows(graph_rows)
    _write_jsonl(args.output / "浙江省企业身份血缘图.jsonl", public_rows)
    aliases_rewritten = sanitize_public_alias_projection(args.output)
    profiles_sanitized = sanitize_public_profile_projection(args.output)
    node_count, edge_count = write_database_graph(args.database, graph_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "source": PUBLIC_SOURCE,
        "identity_subjects": len(graph_rows),
        "lineage_nodes": node_count,
        "lineage_edges": edge_count,
        "public_graph_edges": len(public_rows),
        "public_alias_rows_rewritten": aliases_rewritten,
        "public_profile_rows_sanitized": profiles_sanitized,
        "verified_subjects": sum(
            row["source_layers"]["knowledge_base"]["enterprise_identity_status"]
            == "verified"
            for row in graph_rows
        ),
        "pending_subjects": sum(
            row["source_layers"]["knowledge_base"]["enterprise_identity_status"]
            != "verified"
            for row in graph_rows
        ),
        "public_source_values": [PUBLIC_SOURCE],
        "output": "浙江省企业身份血缘图.jsonl",
    }
    (args.output / "浙江省企业身份血缘图构建报告.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

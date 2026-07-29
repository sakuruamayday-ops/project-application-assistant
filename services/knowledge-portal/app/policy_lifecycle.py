from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


DEFAULT_POLICY_WINDOW_YEARS = 5
EXECUTION_EXCEPTION_FLAGS = (
    "still_effective",
    "cited_by_current_notice",
    "current_upstream_basis",
)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def policy_content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def rolling_policy_window(
    as_of_year: int,
    *,
    window_years: int = DEFAULT_POLICY_WINDOW_YEARS,
    inception_year: int | None = None,
) -> dict[str, int]:
    start_year = as_of_year - max(1, int(window_years)) + 1
    if inception_year:
        start_year = max(start_year, int(inception_year))
    return {
        "start_year": start_year,
        "end_year": as_of_year,
        "window_years": max(1, int(window_years)),
    }


def policy_document_in_execution_window(
    document: Mapping[str, object],
    *,
    as_of_year: int,
    window_years: int = DEFAULT_POLICY_WINDOW_YEARS,
    inception_year: int | None = None,
) -> tuple[bool, str]:
    window = rolling_policy_window(
        as_of_year,
        window_years=window_years,
        inception_year=inception_year,
    )
    issued_year = int(document.get("issued_year") or 0)
    status = str(document.get("status") or "")
    if status in {"superseded", "repealed", "expired"}:
        return False, "superseded-or-expired"
    if issued_year and window["start_year"] <= issued_year <= window["end_year"]:
        return True, "rolling-five-year-window"
    for flag in EXECUTION_EXCEPTION_FLAGS:
        if bool(document.get(flag)):
            return True, flag.replace("_", "-")
    return False, "cold-archive"


def select_policy_documents(
    documents: Sequence[Mapping[str, object]],
    *,
    as_of_year: int,
    window_years: int = DEFAULT_POLICY_WINDOW_YEARS,
    inception_year: int | None = None,
) -> dict[str, list[dict[str, object]]]:
    selected: list[dict[str, object]] = []
    archived: list[dict[str, object]] = []
    for raw_document in documents:
        document = dict(raw_document)
        included, reason = policy_document_in_execution_window(
            document,
            as_of_year=as_of_year,
            window_years=window_years,
            inception_year=inception_year,
        )
        document["selection_reason"] = reason
        document["content_hash"] = policy_content_hash(raw_document)
        (selected if included else archived).append(document)
    return {
        "execution": selected,
        "cold_archive": archived,
    }


def build_policy_dependency_graph(
    packs: Sequence[Mapping[str, object]],
    *,
    as_of_year: int,
    window_years: int = DEFAULT_POLICY_WINDOW_YEARS,
) -> dict[str, object]:
    nodes: dict[str, dict[str, object]] = {}
    edges: list[dict[str, str]] = []
    execution_document_ids: set[str] = set()
    cold_archive_document_ids: set[str] = set()
    for pack in packs:
        project_id = str(pack.get("project_id") or "")
        if not project_id:
            continue
        project_node_id = f"project:{project_id}"
        nodes[project_node_id] = {
            "node_id": project_node_id,
            "node_type": "project",
            "project_id": project_id,
            "title": str(pack.get("project_name") or project_id),
        }
        baseline = pack.get("policy_baseline", {})
        if not isinstance(baseline, Mapping):
            continue
        selection = select_policy_documents(
            [
                document
                for document in baseline.get("policy_documents", [])
                if isinstance(document, Mapping)
            ],
            as_of_year=as_of_year,
            window_years=window_years,
            inception_year=(
                int(baseline["inception_year"])
                if baseline.get("inception_year")
                else None
            ),
        )
        for bucket, documents in selection.items():
            for document in documents:
                document_id = str(document.get("document_id") or "")
                if not document_id:
                    continue
                policy_node_id = f"policy:{document_id}"
                nodes[policy_node_id] = {
                    "node_id": policy_node_id,
                    "node_type": "policy",
                    **document,
                }
                edges.append(
                    {
                        "from": project_node_id,
                        "to": policy_node_id,
                        "relation": str(
                            document.get("relation") or "governed-by"
                        ),
                    }
                )
                (
                    execution_document_ids
                    if bucket == "execution"
                    else cold_archive_document_ids
                ).add(document_id)
        for dependency in baseline.get("dependencies", []):
            if not isinstance(dependency, Mapping):
                continue
            source_id = str(dependency.get("from_document_id") or "")
            target_id = str(dependency.get("to_document_id") or "")
            if not source_id or not target_id:
                continue
            edges.append(
                {
                    "from": f"policy:{source_id}",
                    "to": f"policy:{target_id}",
                    "relation": str(dependency.get("relation") or "cites"),
                }
            )
    graph_basis = {
        "as_of_year": as_of_year,
        "window_years": window_years,
        "nodes": sorted(nodes.values(), key=lambda item: str(item["node_id"])),
        "edges": sorted(
            edges,
            key=lambda item: (item["from"], item["to"], item["relation"]),
        ),
    }
    return {
        "schema_version": 1,
        "graph_type": "project-policy-dependency-graph",
        "as_of_year": as_of_year,
        "window": rolling_policy_window(
            as_of_year,
            window_years=window_years,
        ),
        "nodes": graph_basis["nodes"],
        "edges": graph_basis["edges"],
        "execution_document_ids": sorted(execution_document_ids),
        "cold_archive_document_ids": sorted(cold_archive_document_ids),
        "content_hash": policy_content_hash(graph_basis),
    }

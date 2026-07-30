from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Mapping, Sequence

from app.rule_ir import content_digest


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _rule_index(project: Mapping[str, object]) -> dict[str, dict[str, object]]:
    rules: dict[str, dict[str, object]] = {}
    layers = project.get("rule_layers", [])
    if isinstance(layers, Sequence) and not isinstance(layers, (str, bytes)):
        for layer in layers:
            if not isinstance(layer, Mapping):
                continue
            layer_id = str(layer.get("layer_id") or "")
            for rule in layer.get("rules", []):
                if not isinstance(rule, Mapping):
                    continue
                rule_id = str(rule.get("rule_id") or "")
                if rule_id:
                    rules[rule_id] = {
                        **dict(rule),
                        "_layer_id": layer_id,
                    }
    if not rules:
        for rule in project.get("rule_cards", []):
            if isinstance(rule, Mapping) and str(rule.get("rule_id") or ""):
                rules[str(rule["rule_id"])] = dict(rule)
    return rules


def _requirement_leaf_fields(requirement: Mapping[str, object]) -> set[str]:
    children = requirement.get("children")
    if isinstance(children, Sequence) and not isinstance(children, (str, bytes)):
        return {
            field
            for child in children
            if isinstance(child, Mapping)
            for field in _requirement_leaf_fields(child)
        }
    field = str(requirement.get("field") or "").strip()
    return {field} if field else set()


def _policy_time_index(
    project: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    return {
        str(layer.get("layer_id") or ""): {
            "layer_type": layer.get("layer_type"),
            "policy_time_type": layer.get("policy_time_type"),
            "effective_from": layer.get("effective_from"),
            "effective_to": layer.get("effective_to"),
            "applicability": layer.get("applicability", {}),
        }
        for layer in project.get("rule_layers", [])
        if isinstance(layer, Mapping) and str(layer.get("layer_id") or "")
    }


def _policy_time_delta(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    before_layers = _policy_time_index(before)
    after_layers = _policy_time_index(after)
    changed = sorted(
        layer_id
        for layer_id in set(before_layers) & set(after_layers)
        if content_digest(before_layers[layer_id])
        != content_digest(after_layers[layer_id])
    )
    return {
        "added_layer_ids": sorted(set(after_layers) - set(before_layers)),
        "removed_layer_ids": sorted(set(before_layers) - set(after_layers)),
        "changed_layer_ids": changed,
    }


def _rule_delta(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    before_rules = _rule_index(before)
    after_rules = _rule_index(after)
    common_ids = set(before_rules) & set(after_rules)
    changed = sorted(
        rule_id
        for rule_id in common_ids
        if content_digest(before_rules[rule_id])
        != content_digest(after_rules[rule_id])
    )
    changed_fields = sorted(
        {
            field
            for rule_id in (
                set(after_rules) - set(before_rules)
            ) | set(changed)
            for rule in [after_rules[rule_id]]
            for field in _requirement_leaf_fields(rule)
        }
        | {
            field
            for rule_id in set(before_rules) - set(after_rules)
            for rule in [before_rules[rule_id]]
            for field in _requirement_leaf_fields(rule)
        }
    )
    return {
        "added_rule_ids": sorted(set(after_rules) - set(before_rules)),
        "removed_rule_ids": sorted(set(before_rules) - set(after_rules)),
        "changed_rule_ids": changed,
        "changed_fact_fields": changed_fields,
    }


def _policy_nodes(payload: Mapping[str, object]) -> dict[str, dict[str, object]]:
    graph = _mapping(payload.get("policy_dependency_graph"))
    return {
        str(node.get("node_id") or ""): dict(node)
        for node in graph.get("nodes", [])
        if isinstance(node, Mapping)
        and str(node.get("node_type") or "") == "policy"
        and str(node.get("node_id") or "")
    }


def _changed_policy_node_ids(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> tuple[list[str], list[str], list[str]]:
    before_nodes = _policy_nodes(before)
    after_nodes = _policy_nodes(after)
    changed = sorted(
        node_id
        for node_id in set(before_nodes) & set(after_nodes)
        if before_nodes[node_id].get("content_hash")
        != after_nodes[node_id].get("content_hash")
    )
    return (
        changed,
        sorted(set(after_nodes) - set(before_nodes)),
        sorted(set(before_nodes) - set(after_nodes)),
    )


def _affected_projects_from_graph(
    payload: Mapping[str, object],
    changed_policy_node_ids: set[str],
) -> set[str]:
    graph = _mapping(payload.get("policy_dependency_graph"))
    reverse_edges: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges", []):
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source and target:
            reverse_edges[target].add(source)
    affected: set[str] = set()
    queue = deque(changed_policy_node_ids)
    visited = set(changed_policy_node_ids)
    while queue:
        node_id = queue.popleft()
        for upstream_id in reverse_edges.get(node_id, set()):
            if upstream_id.startswith("project:"):
                affected.add(upstream_id.removeprefix("project:"))
            if upstream_id not in visited:
                visited.add(upstream_id)
                queue.append(upstream_id)
    return affected


def _database_counts(
    database_path: Path | None,
    project_names: Sequence[str],
) -> dict[str, dict[str, int]]:
    counts = {
        project_name: {
            "identity_events": 0,
            "identity_twins": 0,
        }
        for project_name in project_names
    }
    if not database_path or not database_path.is_file() or not counts:
        return counts
    with sqlite3.connect(database_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        placeholders = ",".join("?" for _ in project_names)
        for table_name, key in (
            ("enterprise_recognition_events", "identity_events"),
            ("enterprise_project_identity_twins", "identity_twins"),
        ):
            if table_name not in tables:
                continue
            for project_name, total in connection.execute(
                f"""
                SELECT project_name,COUNT(*)
                FROM {table_name}
                WHERE project_name IN ({placeholders})
                GROUP BY project_name
                """,
                tuple(project_names),
            ):
                counts[str(project_name)][key] = int(total or 0)
    return counts


def simulate_policy_change_impact(
    before: Mapping[str, object] | None,
    after: Mapping[str, object],
    *,
    database_path: Path | None = None,
) -> dict[str, object]:
    """Explain what a policy/rule bundle change invalidates without rewriting facts."""
    before_payload = dict(before or {})
    after_payload = dict(after)
    before_projects = _mapping(before_payload.get("projects"))
    after_projects = _mapping(after_payload.get("projects"))
    changed_nodes, added_nodes, removed_nodes = _changed_policy_node_ids(
        before_payload,
        after_payload,
    )
    graph_affected = _affected_projects_from_graph(
        after_payload,
        set(changed_nodes) | set(added_nodes),
    )
    graph_affected |= _affected_projects_from_graph(
        before_payload,
        set(changed_nodes) | set(removed_nodes),
    )
    changed_project_ids = {
        project_id
        for project_id in set(before_projects) & set(after_projects)
        if _mapping(before_projects[project_id]).get("compile_input_hash")
        != _mapping(after_projects[project_id]).get("compile_input_hash")
    }
    added_project_ids = set(after_projects) - set(before_projects)
    removed_project_ids = set(before_projects) - set(after_projects)
    affected_project_ids = sorted(
        graph_affected
        | changed_project_ids
        | added_project_ids
        | removed_project_ids
    )
    project_names = [
        str(
            _mapping(after_projects.get(project_id)).get("project_name")
            or _mapping(before_projects.get(project_id)).get("project_name")
            or project_id
        )
        for project_id in affected_project_ids
    ]
    database_counts = _database_counts(database_path, project_names)
    impacts: list[dict[str, object]] = []
    for project_id, project_name in zip(affected_project_ids, project_names):
        before_project = _mapping(before_projects.get(project_id))
        after_project = _mapping(after_projects.get(project_id))
        delta = _rule_delta(before_project, after_project)
        policy_time_delta = _policy_time_delta(before_project, after_project)
        lifecycle_changed = content_digest(
            _mapping(before_project.get("lifecycle_rule"))
        ) != content_digest(_mapping(after_project.get("lifecycle_rule")))
        has_rule_delta = any(delta[key] for key in delta)
        has_policy_time_delta = any(
            policy_time_delta[key] for key in policy_time_delta
        )
        changed_fact_fields = list(delta["changed_fact_fields"])
        preflight_requirements = [
            {
                "key": field,
                "label": field,
                "dimension": "source_data",
                "impact": "high",
                "resolution": "discover",
                "reason": "政策变化新增、删除或修改了该企业事实对应的判断门槛",
            }
            for field in changed_fact_fields
        ]
        impacts.append(
            {
                "project_id": project_id,
                "project_name": project_name,
                "change_type": (
                    "added"
                    if project_id in added_project_ids
                    else "removed"
                    if project_id in removed_project_ids
                    else "modified"
                ),
                "rule_delta": delta,
                "policy_time_delta": policy_time_delta,
                "lifecycle_rule_changed": lifecycle_changed,
                "identity_impact": {
                    "official_list_facts_mutated": False,
                    "derived_lifecycle_requires_replay": lifecycle_changed
                    or has_rule_delta,
                    "policy_trace_requires_relink": has_policy_time_delta,
                    **database_counts[project_name],
                },
                "prediction_impact": {
                    "requires_recompute": True,
                    "time_window_changed": has_policy_time_delta,
                    "invalidation_key": (
                        _mapping(after_project).get("policy_version_id")
                        or _mapping(before_project).get("policy_version_id")
                    ),
                },
                "historical_backtest_impact": {
                    "requires_recompute": (
                        has_rule_delta
                        or lifecycle_changed
                        or has_policy_time_delta
                    ),
                    "historical_facts_mutated": False,
                    "historical_fact_guard_changed": has_policy_time_delta,
                },
                "preflight_impact": {
                    "requires_reassessment": has_rule_delta
                    or lifecycle_changed
                    or has_policy_time_delta,
                    "policy_version_id": (
                        _mapping(after_project).get("policy_version_id")
                        or _mapping(before_project).get("policy_version_id")
                    ),
                    "new_high_impact_requirements": preflight_requirements,
                    "ask_user_only_after_discovery": True,
                    "single_question_template": (
                        "政策变化影响了以下企业事实，请主人一次确认现有材料是否"
                        "可覆盖："
                        + "、".join(changed_fact_fields)
                        + "。"
                        if changed_fact_fields
                        else None
                    ),
                },
            }
        )
    return {
        "schema_version": 1,
        "report_type": "policy-change-impact-simulation",
        "before_source_digest": before_payload.get("source_digest"),
        "after_source_digest": after_payload.get("source_digest"),
        "changed_policy_node_ids": changed_nodes,
        "added_policy_node_ids": added_nodes,
        "removed_policy_node_ids": removed_nodes,
        "affected_project_ids": affected_project_ids,
        "affected_projects": impacts,
        "summary": {
            "affected_projects": len(affected_project_ids),
            "identity_events_replayed": sum(
                int(item["identity_impact"]["identity_events"])
                for item in impacts
                if item["identity_impact"]["derived_lifecycle_requires_replay"]
            ),
            "identity_twins_replayed": sum(
                int(item["identity_impact"]["identity_twins"])
                for item in impacts
                if item["identity_impact"]["derived_lifecycle_requires_replay"]
            ),
            "prediction_project_invalidations": len(affected_project_ids),
            "historical_backtest_project_invalidations": sum(
                bool(item["historical_backtest_impact"]["requires_recompute"])
                for item in impacts
            ),
            "preflight_project_reassessments": sum(
                bool(item["preflight_impact"]["requires_reassessment"])
                for item in impacts
            ),
        },
        "invariants": [
            "官方名单形成的认定、复核、撤销等历史事实不因政策变化被改写",
            "仅重算政策解释、生命周期派生状态、预测结果和历史回测",
            "所有影响均可回指变更政策节点、项目规则差异和版本哈希",
            "政策生效窗口变化只重连政策时间语义，不把新规则冒充历史事实",
        ],
    }

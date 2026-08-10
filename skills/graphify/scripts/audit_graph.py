#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import tempfile


VALID_CONFIDENCE = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
BUSINESS_RELATIONS = {
    "requires",
    "supports",
    "evidences",
    "derived_from",
    "applies_to",
    "issued_by",
    "supersedes",
    "interprets",
    "conflicts_with",
    "consistent_with",
    "owns",
    "owned_by",
    "controls",
    "protects",
    "used_by",
    "uses",
    "contributes_to",
    "measured_by",
    "corresponds_to",
    "lacks_evidence_for",
    "transferred_from",
    "supplies_to",
}


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a Graphify graph for Gongchuang Research Institute evidence-chain requirements.")
    parser.add_argument("graph", type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    graph_path = args.graph.expanduser().resolve()
    profile_path = args.profile.expanduser().resolve()
    output = args.output.expanduser().resolve()
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", graph.get("links", []))
    node_ids = {str(n.get("id")) for n in nodes if isinstance(n, dict) and n.get("id")}
    warnings: list[str] = []

    missing_source_nodes = [
        str(n.get("id", "?")) for n in nodes
        if isinstance(n, dict) and not n.get("source_file")
    ]
    dangling = [
        f"{e.get('source', '?')} -> {e.get('target', '?')}"
        for e in edges if isinstance(e, dict)
        and (str(e.get("source")) not in node_ids or str(e.get("target")) not in node_ids)
    ]
    invalid_conf = [
        f"{e.get('source', '?')} -> {e.get('target', '?')}"
        for e in edges if isinstance(e, dict)
        and e.get("confidence") not in VALID_CONFIDENCE
    ]
    bad_extracted_score = [
        f"{e.get('source', '?')} -> {e.get('target', '?')}"
        for e in edges if isinstance(e, dict)
        and e.get("confidence") == "EXTRACTED"
        and float(e.get("confidence_score", 0)) != 1.0
    ]

    if missing_source_nodes:
        warnings.append(f"{len(missing_source_nodes)} 个节点缺少 source_file")
    if dangling:
        warnings.append(f"{len(dangling)} 条关系存在断点")
    if invalid_conf:
        warnings.append(f"{len(invalid_conf)} 条关系的 confidence 非法")
    if bad_extracted_score:
        warnings.append(f"{len(bad_extracted_score)} 条 EXTRACTED 关系的 confidence_score 不是 1.0")

    kinds = Counter(
        str(n.get("entity_kind")) for n in nodes
        if isinstance(n, dict) and n.get("entity_kind")
    )
    relations = Counter(
        str(e.get("relation")) for e in edges
        if isinstance(e, dict) and e.get("relation")
    )
    business_count = sum(relations[r] for r in BUSINESS_RELATIONS)

    if profile.get("profile") == "policy-corpus" and kinds["policy"] and not kinds["version"]:
        warnings.append("存在政策节点，但未提取版本节点")
    if profile.get("profile") == "ip-evidence" and kinds["patent"]:
        patents_without_status = sum(
            1 for n in nodes if isinstance(n, dict)
            and n.get("entity_kind") == "patent" and not n.get("legal_status")
        )
        if patents_without_status:
            warnings.append(f"{patents_without_status} 个专利节点缺少 legal_status")
    if profile.get("profile") == "application-evidence":
        pending = sum(
            1 for n in nodes if isinstance(n, dict)
            and n.get("entity_kind") == "judgment"
            and n.get("review_status") == "pending"
        )
        if pending:
            warnings.append(f"{pending} 个申报判断仍为 pending")

    lines = [
        "# Evidence Graph Audit",
        "",
        f"- Profile: `{profile.get('profile', '')}`",
        f"- Project: `{profile.get('project_name', '')}`",
        f"- Client: `{profile.get('client_name', '')}`",
        f"- Privacy: `{profile.get('privacy', '')}`",
        f"- Nodes: {len(nodes)}",
        f"- Edges: {len(edges)}",
        f"- Business relations: {business_count}",
        "",
        "## Warnings",
        "",
    ]
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- 未发现结构性告警。此结论不代表政策、企业、专利或财务事实已经完成外部核验。")
    lines.extend(["", "## Entity kinds", ""])
    if kinds:
        lines.extend(f"- `{key}`: {value}" for key, value in kinds.most_common())
    else:
        lines.append("- 未提取业务实体类型")
    lines.extend(["", "## Relations", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in relations.most_common())
    lines.extend(["", "## Samples requiring review", ""])
    for label, values in (
        ("Missing source nodes", missing_source_nodes),
        ("Dangling edges", dangling),
        ("Invalid confidence", invalid_conf),
        ("Bad extracted score", bad_extracted_score),
    ):
        lines.append(f"### {label}")
        lines.append("")
        if values:
            lines.extend(f"- `{value}`" for value in values[:20])
        else:
            lines.append("- None")
        lines.append("")

    write_atomic(output, "\n".join(lines).rstrip() + "\n")
    print(output)
    return 1 if invalid_conf or bad_extracted_score else 0


if __name__ == "__main__":
    raise SystemExit(main())

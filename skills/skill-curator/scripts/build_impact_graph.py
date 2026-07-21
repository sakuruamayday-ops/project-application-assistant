#!/usr/bin/env python3
"""Build and query a deterministic skill-change impact graph."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path


TEXT_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json", ".jsonl", ".py", ".sh", ".toml", ".html", ".css", ".js", ".ts"}
SCANNED_ROOTS = ("skills", "config", "docs", "scripts", "src", "tests")
IGNORED_PARTS = {".git", ".venv", "__pycache__", "dist", "build", "cache", "logs", "node_modules"}
PATH_PATTERN = re.compile(r"(?:skills|config|docs|scripts|src|tests)/[\w./()\-\u4e00-\u9fff]+")
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]+)?\)")
BACKTICK_PATTERN = re.compile(r"`([^`\r\n]{1,240})`")


def relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def classify(path: Path, root: Path) -> str:
    rel = relative(path, root)
    parts = Path(rel).parts
    lowered = rel.lower()
    name = path.name.lower()
    if len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md":
        return "skill"
    if "templates" in parts or "assets" in parts or "template" in name:
        return "template"
    if any(token in lowered for token in ("delivery_gate", "self_review", "validate", "quality_gate", "consistency-check")):
        return "gate"
    if "scripts" in parts or path.suffix.lower() in {".py", ".sh", ".js", ".ts"}:
        return "script"
    if "references" in parts:
        return "reference"
    if parts[0] == "config" or path.suffix.lower() in {".yaml", ".yml", ".toml"}:
        return "rule"
    return "document"


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for base_name in SCANNED_ROOTS:
        base = root / base_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
                continue
            if path.suffix.lower() in TEXT_SUFFIXES or path.name == "SKILL.md":
                files.append(path)
    return sorted(set(files))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def resolve_reference(raw: str, source: Path, root: Path) -> Path | None:
    cleaned = raw.strip().strip(".,;:，。；：'")
    if not cleaned or len(cleaned) > 240 or "\n" in cleaned or "\r" in cleaned:
        return None
    if cleaned.startswith(("http://", "https://", "#", "${")):
        return None
    candidates = [root / cleaned, source.parent / cleaned]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        try:
            if resolved.is_file():
                return resolved
        except OSError:
            continue
    return None


def build_graph(root: Path) -> dict[str, object]:
    files = iter_files(root)
    node_by_path: dict[str, dict[str, object]] = {}
    skill_nodes: dict[str, str] = {}
    for path in files:
        rel = relative(path, root)
        node = {"id": rel, "path": rel, "kind": classify(path, root), "label": path.name}
        if node["kind"] == "skill":
            skill_name = Path(rel).parts[1]
            node["label"] = skill_name
            node["skill"] = skill_name
            skill_nodes[skill_name] = rel
        elif len(Path(rel).parts) >= 2 and Path(rel).parts[0] == "skills":
            node["skill"] = Path(rel).parts[1]
        node_by_path[rel] = node

    edges: set[tuple[str, str, str]] = set()
    for rel, node in node_by_path.items():
        path = root / rel
        parts = Path(rel).parts
        if len(parts) >= 3 and parts[0] == "skills" and rel != skill_nodes.get(parts[1]):
            owner = skill_nodes.get(parts[1])
            if owner:
                edges.add((rel, owner, "owned-by-skill"))

        text = read_text(path)
        raw_refs = PATH_PATTERN.findall(text)
        raw_refs.extend(MARKDOWN_LINK_PATTERN.findall(text))
        raw_refs.extend(BACKTICK_PATTERN.findall(text))
        for raw in raw_refs:
            target = resolve_reference(raw, path, root)
            if not target:
                continue
            target_rel = relative(target, root)
            if target_rel in node_by_path and target_rel != rel:
                edges.add((target_rel, rel, "referenced-by"))

        for skill_name, skill_rel in skill_nodes.items():
            if skill_rel == rel:
                continue
            if re.search(rf"(?<![\w-])\$?{re.escape(skill_name)}(?![\w-])", text):
                edges.add((skill_rel, rel, "invoked-by"))

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root.resolve()),
        "nodes": sorted(node_by_path.values(), key=lambda item: str(item["id"])),
        "edges": [
            {"source": source, "target": target, "type": edge_type}
            for source, target, edge_type in sorted(edges)
        ],
    }


def select_seeds(graph: dict[str, object], root: Path, changed: list[str], query: str | None) -> set[str]:
    nodes = {str(node["id"]): node for node in graph["nodes"]}  # type: ignore[index]
    seeds: set[str] = set()
    for raw in changed:
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else root / candidate
        try:
            rel = relative(candidate, root)
        except (OSError, ValueError):
            continue
        if candidate.is_dir():
            seeds.update(node_id for node_id in nodes if node_id.startswith(rel.rstrip("/") + "/"))
        elif rel in nodes:
            seeds.add(rel)
    if query:
        needle = query.casefold()
        for node_id in nodes:
            if needle in node_id.casefold() or needle in read_text(root / node_id).casefold():
                seeds.add(node_id)
    return seeds


def trace_impacts(graph: dict[str, object], seeds: set[str], max_depth: int) -> tuple[dict[str, int], list[dict[str, object]]]:
    outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in graph["edges"]:  # type: ignore[index]
        outgoing[str(edge["source"])].append((str(edge["target"]), str(edge["type"])))
    distance = {seed: 0 for seed in seeds}
    queue = deque(seeds)
    evidence: list[dict[str, object]] = []
    while queue:
        current = queue.popleft()
        if distance[current] >= max_depth:
            continue
        for target, edge_type in outgoing.get(current, []):
            if target not in distance:
                distance[target] = distance[current] + 1
                evidence.append({"source": current, "target": target, "type": edge_type, "depth": distance[current] + 1})
                queue.append(target)
    return distance, evidence


def impact_report(graph: dict[str, object], seeds: set[str], distance: dict[str, int], evidence: list[dict[str, object]]) -> str:
    nodes = {str(node["id"]): node for node in graph["nodes"]}  # type: ignore[index]
    lines = ["# 技能变更影响图报告", "", f"生成时间：{graph['generated_at']}", ""]
    if not seeds:
        counts: dict[str, int] = defaultdict(int)
        for node in nodes.values():
            counts[str(node["kind"])] += 1
        lines.extend(["## 图谱概况", "", f"节点：{len(nodes)}；关系：{len(graph['edges'])}。", ""])
        for kind, count in sorted(counts.items()):
            lines.append(f"- {kind}: {count}")
        lines.extend(["", "未指定变更文件或规则关键词，因此本报告只展示全图统计。"])
        return "\n".join(lines) + "\n"

    impacted = [node_id for node_id in distance if node_id not in seeds]
    lines.extend(["## 变更源", ""])
    lines.extend(f"- `{node_id}`" for node_id in sorted(seeds))
    lines.extend(["", "## 受影响对象", ""])
    grouped: dict[str, list[str]] = defaultdict(list)
    for node_id in impacted:
        grouped[str(nodes[node_id]["kind"])].append(node_id)
    if not grouped:
        lines.append("当前图谱未发现下游依赖。")
    for kind in ("skill", "template", "script", "gate", "reference", "rule", "document"):
        values = sorted(grouped.get(kind, []), key=lambda item: (distance[item], item))
        if not values:
            continue
        lines.extend([f"### {kind}", ""])
        lines.extend(f"- 深度 {distance[value]}：`{value}`" for value in values)
        lines.append("")
    lines.extend(["## 关系证据", ""])
    for edge in sorted(evidence, key=lambda item: (int(item["depth"]), str(item["source"]), str(item["target"]))):
        if str(edge["source"]) in distance and str(edge["target"]) in distance:
            lines.append(f"- `{edge['source']}` --{edge['type']}--> `{edge['target']}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="构建并查询技能变更影响图")
    default_root = Path(__file__).resolve().parents[3]
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--changed", action="append", default=[], help="变更文件或目录，可重复")
    parser.add_argument("--query", help="按规则关键词定位变更源")
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    output_dir = args.output_dir or root / ".project-assistant" / "evolution"
    output_dir.mkdir(parents=True, exist_ok=True)
    graph = build_graph(root)
    seeds = select_seeds(graph, root, args.changed, args.query)
    distance, evidence = trace_impacts(graph, seeds, max(1, args.max_depth))
    graph["analysis"] = {
        "changed": args.changed,
        "query": args.query,
        "seeds": sorted(seeds),
        "impacted": [
            {"id": node_id, "depth": depth}
            for node_id, depth in sorted(distance.items(), key=lambda item: (item[1], item[0]))
            if node_id not in seeds
        ],
        "evidence": evidence,
    }
    graph_path = output_dir / "skill-impact-graph.json"
    report_path = output_dir / "skill-impact-report.md"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(impact_report(graph, seeds, distance, evidence), encoding="utf-8")
    print(json.dumps({"graph": str(graph_path), "report": str(report_path), "seeds": len(seeds), "impacted": max(0, len(distance) - len(seeds))}, ensure_ascii=False))


if __name__ == "__main__":
    main()

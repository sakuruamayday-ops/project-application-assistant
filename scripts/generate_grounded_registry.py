#!/usr/bin/env python3
"""Generate the grounded-citation registry and its call-graph relations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "grounded-citations.json"
MANIFEST = ROOT / "skills" / "suite-manifest.json"
REGISTRY = ROOT / "skills" / "report-skill-registry.json"
CALL_GRAPH = ROOT / "skills" / "skill-call-graph.json"
MANAGED_REASON = "统一来源登记、编号和校验由 evidence-ledger 提供；交付页面结构服从文档配置。"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_registry(config: dict, manifest: dict) -> dict:
    profiles = config["profiles"]
    overrides = config.get("skill_profiles", {})
    default_profile = config["default_profile"]
    unknown = sorted(set(overrides) - set(manifest["skills"]))
    if unknown:
        raise ValueError("配置引用未知技能:" + ",".join(unknown))
    skills = []
    for skill in manifest["skills"]:
        profile = overrides.get(skill, default_profile)
        if profile not in profiles:
            raise ValueError(f"{skill}引用未知文档配置:{profile}")
        skills.append(
            {
                "skill": skill,
                "profile": profile,
                "uses_grounded_engine": profile != "chat" or skill == "evidence-ledger",
            }
        )
    return {
        "schema_version": 1,
        "product": manifest["product_name"],
        "release": manifest["release"],
        "engine": config["engine"],
        "profiles": profiles,
        "artifact_profile_overrides": config.get("artifact_profile_overrides", {}),
        "artifact_validation": config.get("artifact_validation", {}),
        "host_adapters": config["host_adapters"],
        "skills": skills,
    }


def update_call_graph(graph: dict, registry: dict) -> dict:
    relations = [
        relation
        for relation in graph["relations"]
        if relation.get("reason") != MANAGED_REASON
    ]
    existing_pairs = {(item["from"], item["to"]) for item in relations}
    for item in registry["skills"]:
        skill = item["skill"]
        if not item["uses_grounded_engine"] or skill == "evidence-ledger":
            continue
        pair = (skill, "evidence-ledger")
        if pair in existing_pairs:
            continue
        relations.append(
            {
                "from": skill,
                "to": "evidence-ledger",
                "type": "requires",
                "reason": MANAGED_REASON,
            }
        )
        existing_pairs.add(pair)
    graph["relations"] = relations
    return graph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    config = load(CONFIG)
    manifest = load(MANIFEST)
    registry = build_registry(config, manifest)
    graph = update_call_graph(load(CALL_GRAPH), registry)
    expected_registry = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    expected_graph = json.dumps(graph, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        failures = []
        if not REGISTRY.exists() or REGISTRY.read_text(encoding="utf-8") != expected_registry:
            failures.append(str(REGISTRY.relative_to(ROOT)))
        if CALL_GRAPH.read_text(encoding="utf-8") != expected_graph:
            failures.append(str(CALL_GRAPH.relative_to(ROOT)))
        print(json.dumps({"status": "pass" if not failures else "fail", "stale": failures}, ensure_ascii=False))
        return 0 if not failures else 2
    write(REGISTRY, registry)
    write(CALL_GRAPH, graph)
    print(
        json.dumps(
            {
                "status": "pass",
                "registry": str(REGISTRY),
                "registered_skills": len(registry["skills"]),
                "grounded_skills": sum(1 for item in registry["skills"] if item["uses_grounded_engine"]),
                "call_graph": str(CALL_GRAPH),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

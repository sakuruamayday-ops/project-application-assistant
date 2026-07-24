import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
GRAPH_PATH = SKILLS_ROOT / "skill-call-graph.json"


def load_graph() -> dict:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def test_call_graph_covers_all_skills_once():
    graph = load_graph()
    manifest = json.loads(
        (SKILLS_ROOT / "suite-manifest.json").read_text(encoding="utf-8")
    )
    actual = {
        path.parent.name
        for path in SKILLS_ROOT.glob("*/SKILL.md")
    }
    grouped = [
        skill
        for skills in graph["groups"].values()
        for skill in skills
    ]
    assert len(grouped) == len(set(grouped)) == len(manifest["skills"])
    assert set(grouped) == actual
    assert sorted(grouped) == manifest["skills"]


def test_call_graph_relations_use_known_skills_and_types():
    graph = load_graph()
    skills = {
        skill
        for values in graph["groups"].values()
        for skill in values
    }
    relation_types = set(graph["relation_types"])
    seen = set()
    for relation in graph["relations"]:
        edge = (relation["from"], relation["to"], relation["type"])
        assert relation["from"] in skills
        assert relation["to"] in skills
        assert relation["from"] != relation["to"]
        assert relation["type"] in relation_types
        assert relation["reason"].strip()
        assert edge not in seen
        seen.add(edge)


def test_required_dependency_graph_is_acyclic():
    graph = load_graph()
    adjacency = {}
    for relation in graph["relations"]:
        if relation["type"] != "requires":
            continue
        adjacency.setdefault(relation["from"], set()).add(relation["to"])

    visiting = set()
    visited = set()

    def visit(skill: str):
        assert skill not in visiting, f"required dependency cycle detected at {skill}"
        if skill in visited:
            return
        visiting.add(skill)
        for dependency in adjacency.get(skill, ()):
            visit(dependency)
        visiting.remove(skill)
        visited.add(skill)

    for skill in {
        skill
        for values in graph["groups"].values()
        for skill in values
    }:
        visit(skill)

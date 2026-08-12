import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
MANIFEST_PATH = SKILLS_ROOT / "suite-manifest.json"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")
RELEASE_TAG = re.compile(
    r"^V(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?$"
)


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def actual_skill_names() -> list[str]:
    return sorted(
        path.parent.name
        for path in SKILLS_ROOT.glob("*/SKILL.md")
        if path.is_file()
    )


def test_suite_manifest_is_the_only_skill_count_source() -> None:
    manifest = load_manifest()
    declared = manifest["skills"]

    assert "expected_skill_count" not in manifest
    assert declared == sorted(declared)
    assert len(declared) == len(set(declared))
    assert declared == actual_skill_names()


def test_suite_release_tag_and_semver_are_consistent() -> None:
    release = load_manifest()["release"]
    tag_match = RELEASE_TAG.fullmatch(release["tag"])
    version_match = SEMVER.fullmatch(release["version"])

    assert tag_match is not None
    assert version_match is not None
    assert (
        tag_match.group(1),
        tag_match.group(2),
        tag_match.group(3) or "0",
        tag_match.group(4),
    ) == version_match.groups()


def test_delivery_contract_rule_version_matches_suite_release() -> None:
    manifest = load_manifest()
    contract = json.loads(
        (SKILLS_ROOT / "delivery-contracts.json").read_text(encoding="utf-8")
    )

    assert contract["rule_version"] == manifest["release"]["version"]


def test_call_graph_covers_manifest_skill_set() -> None:
    manifest = load_manifest()
    graph_path = SKILLS_ROOT / manifest["skill_call_graph"]
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_skills = sorted(
        skill
        for skills in graph["groups"].values()
        for skill in skills
    )

    assert graph_skills == sorted(manifest["skills"])


def test_active_runtime_surfaces_do_not_hardcode_skill_count() -> None:
    count_literal = re.compile(r"(?<!\d)(?:49|50)\s*项\s*(?:正式\s*)?Skills")
    active_paths = [
        ROOT / "services/knowledge-portal/app/main.py",
        ROOT / "services/knowledge-portal/app/assistant_runtime.py",
        ROOT / "services/knowledge-portal/scripts/release_gate.sh",
        ROOT / "tests/codex-client-skill-matrix.json",
        *sorted((ROOT / "services/knowledge-portal/templates").glob("*.html")),
    ]
    findings = []
    for path in active_paths:
        text = path.read_text(encoding="utf-8")
        if count_literal.search(text):
            findings.append(str(path.relative_to(ROOT)))

    assert findings == []

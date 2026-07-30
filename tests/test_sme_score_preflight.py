from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "sme-score-preassessment"
PREFLIGHT = SKILL_DIR / "scripts" / "preflight.py"
BASELINE = (
    SKILL_DIR / "references" / "current-policy-baseline-2026.json"
)
RULE_SOURCES = (
    ROOT
    / "services"
    / "knowledge-portal"
    / "references"
    / "project-algorithm-rule-sources"
)


def run_preflight(*arguments: str) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(PREFLIGHT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, json.loads(completed.stdout)


def quality_threshold(source_name: str, rule_id: str) -> object:
    payload = json.loads(
        (RULE_SOURCES / source_name).read_text(encoding="utf-8")
    )
    return next(
        rule["expected"]
        for rule in payload["rules"]
        if rule["rule_id"] == rule_id
    )


def test_full_score_blocks_once_on_high_impact_omissions():
    returncode, result = run_preflight("--task-type", "full-score")

    assert returncode == 2
    assert result["status"] == "needs-user-input"
    assert result["can_issue_full_score"] is False
    assert [gap["key"] for gap in result["high_impact_gaps"]] == [
        "project_level",
        "application_type",
        "standard_input",
    ]
    assert result["blocking_question"].count("请主人一次确认") == 1


def test_automatic_policy_injection_requires_task_specific_rerun():
    returncode, result = run_preflight(
        "--task-type",
        "explanation",
    )

    assert returncode == 0
    assert result["requires_task_specific_rerun"] is True
    assert result["can_issue_full_score"] is False
    assert "prohibited_for_current_recognition" in result["method_boundary"]


def test_current_recognition_thresholds_are_selected_deterministically():
    provincial_code, provincial = run_preflight(
        "--task-type",
        "full-score",
        "--project-level",
        "省级专精特新",
        "--application-type",
        "新申报",
        "--has-standard-input",
    )
    giant_code, giant = run_preflight(
        "--task-type",
        "full-score",
        "--project-level",
        "小巨人",
        "--application-type",
        "recognition",
        "--has-standard-input",
    )

    assert provincial_code == giant_code == 0
    assert provincial["selected_policy"]["quality_score_threshold"] == 50
    assert giant["selected_policy"]["quality_score_threshold"] == 60


def test_little_giant_review_does_not_reuse_recognition_threshold():
    returncode, result = run_preflight(
        "--task-type",
        "non-financial-preview",
        "--project-level",
        "专精特新小巨人",
        "--application-type",
        "复核",
    )

    assert returncode == 0
    assert result["selected_policy"]["rule_branch"] == (
        "2022-transition-for-2026-review"
    )
    assert result["selected_policy"]["quality_score_threshold"] is None


def test_skill_baseline_matches_confirmed_project_rule_sources():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    provincial = baseline["project_levels"]["省级专精特新中小企业"][
        "application_types"
    ]["recognition"]["quality_score_threshold"]
    giant = baseline["project_levels"]["专精特新“小巨人”"][
        "application_types"
    ]["recognition"]["quality_score_threshold"]

    assert provincial == quality_threshold(
        "zhejiang-specialized-sme.json",
        "specialized-sme-quality-score",
    )
    assert giant == quality_threshold(
        "little-giant.json",
        "little-giant-quality-score",
    )


def test_skill_contract_requires_preflight_and_current_baseline():
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "scripts/preflight.py" in skill_text
    assert (
        'scripts/preflight.py" --task-type explanation`'
        in skill_text
    )
    assert "current-policy-baseline-2026.md" in skill_text
    assert "省级专精特新中小企业质量得分不低于50分" in skill_text
    assert "禁止把2022年四个二十五分维度" in skill_text

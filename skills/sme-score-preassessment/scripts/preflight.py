#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from check_company_evidence import assess_company


SKILL_DIR = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    SKILL_DIR / "references" / "current-policy-baseline-2026.json"
)
TASK_TYPES = ("quality-preassessment", "gate-only", "explanation")
APPLICATION_TYPE_ALIASES = {
    "recognition": "recognition",
    "new-recognition": "recognition",
    "新申报": "recognition",
    "认定": "recognition",
    "review": "review",
    "复核": "review",
}


def load_baseline() -> dict[str, object]:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("2026政策基线顶层必须为对象")
    return payload


def normalize_project_level(
    raw_value: str,
    baseline: dict[str, object],
) -> str:
    value = raw_value.strip()
    for canonical, raw_config in baseline["project_levels"].items():
        config = dict(raw_config)
        if value == canonical or value in config.get("aliases", []):
            return str(canonical)
    return ""


def normalize_application_type(raw_value: str) -> str:
    return APPLICATION_TYPE_ALIASES.get(raw_value.strip(), "")


def run_preflight(
    *,
    task_type: str,
    project_level: str,
    application_type: str,
    has_standard_input: bool,
    evidence_input: dict[str, object] | None = None,
) -> dict[str, object]:
    baseline = load_baseline()
    high_impact_gaps: list[dict[str, object]] = []

    if task_type not in TASK_TYPES:
        high_impact_gaps.append(
            {
                "key": "task_type",
                "label": "任务类型",
                "allowed_values": list(TASK_TYPES),
                "impact": "决定是否执行2026门槛预评估；旧版测分任务已停用",
            }
        )

    canonical_level = normalize_project_level(project_level, baseline)
    canonical_application_type = normalize_application_type(application_type)
    requires_scoring_context = task_type in {"quality-preassessment", "gate-only"}
    if requires_scoring_context and not canonical_level:
        high_impact_gaps.append(
            {
                "key": "project_level",
                "label": "项目层级",
                "allowed_values": list(baseline["project_levels"]),
                "impact": "决定50分或60分平台质量门槛及适用管理条款",
            }
        )
    if requires_scoring_context and not canonical_application_type:
        high_impact_gaps.append(
            {
                "key": "application_type",
                "label": "申请类型",
                "allowed_values": ["新申报", "复核"],
                "impact": "2026年新申报与复核可能适用不同规则",
            }
        )
    selected_policy = None
    if canonical_level and canonical_application_type:
        level_config = baseline["project_levels"][canonical_level]
        selected_policy = {
            "project_level": canonical_level,
            "project_id": level_config["project_id"],
            "application_type": canonical_application_type,
            **level_config["application_types"][canonical_application_type],
        }

    blocking_question = None
    if high_impact_gaps:
        prompts = []
        for gap in high_impact_gaps:
            allowed = "、".join(gap["allowed_values"])
            prompts.append(
                f"{gap['label']}{f'，可选：{allowed}' if allowed else ''}"
            )
        blocking_question = (
            "开始2026门槛预评估前，请主人一次确认或补充：" + "；".join(prompts) + "。"
        )

    low_impact_assumptions = []
    if task_type in {"quality-preassessment", "gate-only"}:
        low_impact_assumptions.append(
            {
                "key": "output_format",
                "assumed_value": "结构化预评估表",
                "reason": "技能不再生成内部评分工作簿",
            }
        )

    assessment = None
    if selected_policy and requires_scoring_context and not high_impact_gaps and evidence_input is not None:
        assessment = assess_company(evidence_input, selected_policy)

    return {
        "schema_version": 1,
        "status": "needs-user-input" if high_impact_gaps else "ready",
        "can_start_substantive_work": not high_impact_gaps,
        "can_issue_full_score": False,
        "quality_score_mode": "platform-only",
        "requires_task_specific_rerun": task_type == "explanation",
        "policy_version": baseline["policy_version"],
        "policy_as_of": baseline["as_of"],
        "selected_policy": selected_policy,
        "input_status": "received" if evidence_input is not None else ("declared" if has_standard_input else "not-supplied"),
        "assessment": assessment,
        "high_impact_gaps": high_impact_gaps,
        "low_impact_assumptions": low_impact_assumptions,
        "blocking_question": blocking_question,
        "method_boundary": baseline["method_boundary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="2026年专精特新门槛预评估前置遗漏扫描"
    )
    parser.add_argument("--task-type", default="")
    parser.add_argument("--project-level", default="")
    parser.add_argument("--application-type", default="")
    parser.add_argument("--has-standard-input", action="store_true")
    parser.add_argument("--input", type=Path, help="含企业事实、评估年度与平台正式回执的 JSON")
    arguments = parser.parse_args()
    evidence_input = None
    if arguments.input:
        try:
            evidence_input = json.loads(arguments.input.read_text(encoding="utf-8"))
            if not isinstance(evidence_input, dict):
                raise ValueError("企业事实须为 JSON 对象")
        except (OSError, ValueError) as error:
            print(json.dumps({"status": "invalid-input", "items": [
                {"item": "企业事实", "gap": str(error), "action": "核对文件路径和 JSON 对象格式", "priority": "高"}
            ]}, ensure_ascii=False, indent=2))
            return 2
    result = run_preflight(
        task_type=arguments.task_type,
        project_level=arguments.project_level,
        application_type=arguments.application_type,
        has_standard_input=arguments.has_standard_input,
        evidence_input=evidence_input,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["can_start_substantive_work"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

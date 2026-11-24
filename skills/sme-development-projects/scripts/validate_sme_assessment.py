#!/usr/bin/env python3
"""校验优质中小企业诊断的版本、政策和四项判断。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


DECISIONS = {"retain", "replace", "retain-after-evidence"}
EVIDENCE_STATES = {"verified", "computed", "claimed", "missing", "conflicting"}
JUDGMENTS = {"leading_product", "bottleneck", "gap_filling", "import_substitution"}
QUALITY_SCORE_STATES = {"verified-platform-score", "pending-platform-evaluation"}
LEGACY_SCORE_KEYS = {
    "estimated_score",
    "total_score",
    "score_range",
    "conservative_score",
    "baseline_score",
    "conditional_score",
    "legacy_score",
}


def validate(document: dict) -> list[str]:
    errors: list[str] = []
    context = document.get("application_context", {})
    for field in ("project_level", "region", "year", "application_type", "form_version"):
        if not context.get(field):
            errors.append(f"application_context缺少{field}")
    if context.get("version_status") != "confirmed":
        errors.append("申请书版本未确认")
    if context.get("policy_status") != "current":
        errors.append("政策状态不是current")
    if document.get("overall_conclusion") not in {
        "eligible",
        "conditional",
        "ineligible",
        "undetermined",
    }:
        errors.append("overall_conclusion无效")
    judgments = document.get("four_judgments")
    if not isinstance(judgments, dict):
        errors.append("four_judgments必须为对象")
        judgments = {}
    if set(judgments) != JUDGMENTS:
        errors.append(f"四项判断不完整:{sorted(JUDGMENTS - set(judgments))}")
    for name, item in judgments.items():
        if name not in JUDGMENTS:
            errors.append(f"未知判断项:{name}")
            continue
        if item.get("decision") not in DECISIONS:
            errors.append(f"{name}.decision无效")
        if item.get("evidence_state") not in EVIDENCE_STATES:
            errors.append(f"{name}.evidence_state无效")
        for field in ("object", "reason", "actions"):
            if not item.get(field):
                errors.append(f"{name}缺少{field}")
        if name == "import_substitution" and item.get("external_proof_required") is True:
            errors.append("进口替代不得把国外型号、客户证明或第三方检测设为成立前提")
    for field in ("hard_gates", "evaluation", "evidence_gaps", "risks", "actions"):
        if field not in document:
            errors.append(f"缺少{field}")
    evaluation = document.get("evaluation")
    if not isinstance(evaluation, dict):
        errors.append("evaluation必须为对象")
        evaluation = {}
    legacy_fields = sorted(LEGACY_SCORE_KEYS & set(evaluation))
    if legacy_fields:
        errors.append("evaluation包含已停用的估分字段:" + ",".join(legacy_fields))
    if any(key in evaluation for key in ("professionalization", "refinement", "specialization", "innovation_ability")):
        errors.append("evaluation不得使用历史四维评分体系")
    quality_score = evaluation.get("quality_score")
    if not isinstance(quality_score, dict):
        errors.append("evaluation缺少quality_score对象")
    else:
        score_status = quality_score.get("status")
        score_value = quality_score.get("value")
        if score_status not in QUALITY_SCORE_STATES:
            errors.append("quality_score.status无效")
        if score_status == "verified-platform-score":
            if (
                isinstance(score_value, bool)
                or not isinstance(score_value, (int, float))
                or not 0 <= float(score_value) <= 100
                or not quality_score.get("source")
            ):
                errors.append("平台质量分必须为0至100且含可验证来源")
        elif score_value is not None:
            errors.append("平台质量分待评价时value必须为null")
    if (
        document.get("overall_conclusion") == "eligible"
        and isinstance(quality_score, dict)
        and quality_score.get("status") != "verified-platform-score"
    ):
        errors.append("平台质量分未核验时总体结论不得为eligible")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: validate_sme_assessment.py <结果.json>", file=sys.stderr)
        return 2
    try:
        document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False))
        return 2
    errors = validate(document)
    print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

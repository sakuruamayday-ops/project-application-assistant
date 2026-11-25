#!/usr/bin/env python3
"""校验优质中小企业诊断的版本、政策、四项判断与 v1.2 撰写元数据（ai_meta）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DECISIONS = {"retain", "replace", "retain-after-evidence"}
EVIDENCE_STATES = {"verified", "computed", "claimed", "missing", "conflicting"}
JUDGMENTS = {"leading_product", "bottleneck", "gap_filling", "import_substitution"}
QUALITY_SCORE_STATES = {"verified-platform-score", "pending-platform-evaluation"}
BUSINESS_TYPES = {"equipment_or_mold_maker", "product_or_material_maker", "ambiguous"}
METRIC_ORIGINS = {"enterprise_source", "ai_design_target", "public_registry", "mcp_verified"}
LEGACY_SCORE_KEYS = {
    "estimated_score",
    "total_score",
    "score_range",
    "conservative_score",
    "baseline_score",
    "conditional_score",
    "legacy_score",
}


def validate(document: dict, *, strict: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
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

    # Optional v1.2 ai_meta validation (dual-field product lock, 3-tier patent triage, estimated metrics lineage).
    ai_meta = document.get("ai_meta") or document.get("__aiMeta")
    if ai_meta is not None:
        if not isinstance(ai_meta, dict):
            errors.append("ai_meta必须为对象")
        else:
            locked = ai_meta.get("lockedProduct")
            if isinstance(locked, dict):
                if not locked.get("rawAnchor"):
                    (errors if strict else warnings).append("ai_meta.lockedProduct缺少rawAnchor商业实体锚点")
                btype = locked.get("businessType", "ambiguous")
                if btype not in BUSINESS_TYPES:
                    errors.append(f"ai_meta.lockedProduct.businessType无效:{btype}")
                unpatented = locked.get("unpatentedProcessTags", [])
                if not isinstance(unpatented, list):
                    errors.append("ai_meta.lockedProduct.unpatentedProcessTags必须为数组")
            tiers = ai_meta.get("patentTierReport")
            if isinstance(tiers, dict):
                for key in ("direct_support", "production_support", "weak_or_unrelated"):
                    if key in tiers and not isinstance(tiers[key], list):
                        errors.append(f"ai_meta.patentTierReport.{key}必须为数组")
                if not tiers.get("direct_support"):
                    warnings.append("direct_support有效核心专利为空，已触发兜底策略并须在Q2列出发明专利补强建议")
            estimates = ai_meta.get("estimatedMetrics", [])
            if not isinstance(estimates, list):
                errors.append("ai_meta.estimatedMetrics必须为数组")
            else:
                for idx, item in enumerate(estimates):
                    if not isinstance(item, dict):
                        errors.append(f"ai_meta.estimatedMetrics[{idx}]必须为对象")
                        continue
                    origin = item.get("origin", "ai_design_target")
                    if origin not in METRIC_ORIGINS:
                        errors.append(f"ai_meta.estimatedMetrics[{idx}].origin无效:{origin}")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="校验优质中小企业培育/撰写诊断结果 JSON（支持 --strict 真严格门禁、v1.2 ai_meta 及可选正文密度核验）"
    )
    parser.add_argument("assessment", type=Path, help="诊断结果 JSON 文件路径")
    parser.add_argument("--strict", action="store_true", help="严格模式：存在任何错误或未闭合告警时返回退出码 2")
    parser.add_argument("--text-file", type=Path, default=None, help="可选：校验六大问题/方向卡交付正文质量与防串户")
    parser.add_argument("--company", default="", help="配合 --text-file 使用的期望企业全称")
    parser.add_argument("--min-chars", type=int, default=200, help="配合 --text-file 使用的正文最低饱满度字数")
    args = parser.parse_args()
    try:
        document = json.loads(args.assessment.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)], "warnings": []}, ensure_ascii=False))
        return 2
    errors, warnings = validate(document, strict=args.strict)

    text_audit = None
    if args.text_file:
        script_dir = Path(__file__).resolve().parent
        for cand in (script_dir.parent.parent / "_core", script_dir / "_core"):
            if cand.is_dir() and str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
        import quality_gate  # type: ignore

        text_audit = quality_gate.audit_formal_text(
            args.text_file.read_text(encoding="utf-8"),
            expected_company=args.company,
            min_chars=args.min_chars,
        )
        if not text_audit["ok"]:
            errors.extend(e["issue"] for e in text_audit["errors"])

    failed = bool(errors) or (args.strict and bool(warnings))
    status = "fail" if failed else "pass"
    out = {"status": status, "errors": errors, "warnings": warnings}
    if text_audit is not None:
        out["text_audit"] = text_audit
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

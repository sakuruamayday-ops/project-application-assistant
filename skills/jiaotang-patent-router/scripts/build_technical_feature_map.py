#!/usr/bin/env python3
"""从结构化技术底稿生成可追溯的技术特征证据图。

本工具只校验来源、特征、效果和 AI 充分公开要素的完整性，
不自动生成技术事实，不作出新颖性、创造性或可授权结论。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "technical-feature-input/v1"
OUTPUT_SCHEMA = "technical-feature-map/v1"
ALLOWED_FEATURE_ROLES = {"core", "supporting", "context", "alternative"}
AI_DOMAINS = {"ai", "artificial_intelligence", "artificial-intelligence", "人工智能"}
SOFTWARE_COPYRIGHT_PURPOSES = {
    "software_copyright",
    "software-copyright",
    "copyright_registration",
    "软著",
    "软件著作权",
}
SENSITIVE_KEYS = {
    "id_card",
    "identity_number",
    "national_id",
    "phone",
    "mobile",
    "email",
    "home_address",
    "身份证号",
    "手机号",
    "联系电话",
    "邮箱",
    "家庭地址",
}


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON根节点必须是对象")
    return value


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def unique(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            rows.append(cleaned)
            seen.add(key)
    return rows


def issue(code: str, message: str, path: str, severity: str = "blocker") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "path": path,
        "message": message,
    }


def sensitive_key_paths(value: Any, prefix: str = "$") -> list[str]:
    rows: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            if str(key).casefold() in SENSITIVE_KEYS:
                rows.append(child_path)
            rows.extend(sensitive_key_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(sensitive_key_paths(child, f"{prefix}[{index}]"))
    return rows


def normalize_sources(payload: dict[str, Any], blockers: list[dict[str, str]]) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(payload.get("sources") or []):
        path = f"$.sources[{index}]"
        if not isinstance(item, dict):
            blockers.append(issue("SOURCE_NOT_OBJECT", "来源记录必须是对象。", path))
            continue
        source_id = text(item.get("source_id"))
        if not source_id:
            blockers.append(issue("SOURCE_ID_MISSING", "来源缺少source_id。", path))
            continue
        if source_id in identifiers:
            blockers.append(issue("SOURCE_ID_DUPLICATED", f"来源编号重复：{source_id}。", path))
            continue
        identifiers.add(source_id)
        rows.append(
            {
                "source_id": source_id,
                "kind": text(item.get("kind")) or "unspecified",
                "title": text(item.get("title")) or source_id,
                "sha256": text(item.get("sha256")) or None,
                "confidentiality": text(item.get("confidentiality")) or "继承案件任务头",
            }
        )
    if not rows:
        blockers.append(issue("NO_TECHNICAL_SOURCES", "至少需要一份可识别的技术来源。", "$.sources"))
    return rows, identifiers


def normalize_evidence(
    values: Any,
    *,
    source_ids: set[str],
    path: str,
    blockers: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, item in enumerate(values or []):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            blockers.append(issue("EVIDENCE_NOT_OBJECT", "证据定位必须是对象。", item_path))
            continue
        source_id = text(item.get("source_id"))
        locator = text(item.get("locator"))
        if not source_id or source_id not in source_ids:
            blockers.append(issue("UNKNOWN_EVIDENCE_SOURCE", "证据引用了未登记的来源。", item_path))
            continue
        if not locator:
            blockers.append(issue("EVIDENCE_LOCATOR_MISSING", "证据必须有页码、章节、行号或其他可复核定位。", item_path))
            continue
        row = {"source_id": source_id, "locator": locator}
        excerpt = text(item.get("excerpt"))
        if excerpt:
            row["excerpt"] = excerpt
        rows.append(row)
    return rows


def normalize_problem(
    payload: dict[str, Any],
    *,
    source_ids: set[str],
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
    raw = payload.get("technical_problem")
    if not isinstance(raw, dict) or not text(raw.get("text")):
        blockers.append(issue("TECHNICAL_PROBLEM_MISSING", "缺少与具体场景和约束绑定的技术问题。", "$.technical_problem"))
        return {"text": "", "evidence": []}
    evidence = normalize_evidence(
        raw.get("evidence"),
        source_ids=source_ids,
        path="$.technical_problem.evidence",
        blockers=blockers,
    )
    if not evidence:
        blockers.append(issue("TECHNICAL_PROBLEM_UNSUPPORTED", "技术问题没有来源定位。", "$.technical_problem.evidence"))
    return {
        "text": text(raw.get("text")),
        "constraints": unique(list(raw.get("constraints") or [])),
        "evidence": evidence,
    }


def normalize_features(
    payload: dict[str, Any],
    *,
    source_ids: set[str],
    blockers: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(payload.get("features") or []):
        path = f"$.features[{index}]"
        if not isinstance(item, dict):
            blockers.append(issue("FEATURE_NOT_OBJECT", "技术特征必须是对象。", path))
            continue
        feature_id = text(item.get("feature_id"))
        feature_text = text(item.get("text"))
        role = text(item.get("role")) or "supporting"
        if not feature_id or feature_id in identifiers:
            blockers.append(issue("FEATURE_ID_INVALID", "技术特征编号缺失或重复。", path))
            continue
        identifiers.add(feature_id)
        if not feature_text:
            blockers.append(issue("FEATURE_TEXT_MISSING", "技术特征缺少客观表述。", path))
        if role not in ALLOWED_FEATURE_ROLES:
            blockers.append(issue("FEATURE_ROLE_INVALID", f"不支持的特征角色：{role}。", f"{path}.role"))
        evidence = normalize_evidence(
            item.get("evidence"),
            source_ids=source_ids,
            path=f"{path}.evidence",
            blockers=blockers,
        )
        if role == "core" and not evidence:
            blockers.append(issue("CORE_FEATURE_UNSUPPORTED", f"核心特征{feature_id}没有可复核出处。", f"{path}.evidence"))
        elif not evidence:
            warnings.append(issue("FEATURE_EVIDENCE_PENDING", f"特征{feature_id}暂无出处，只能作为待确认候选。", f"{path}.evidence", "warning"))
        search_terms = unique(
            [feature_text]
            + list(item.get("search_terms") or [])
            + list(item.get("aliases") or [])
            + list(item.get("translations") or [])
        )
        rows.append(
            {
                "feature_id": feature_id,
                "role": role,
                "text": feature_text,
                "relationship": text(item.get("relationship")) or None,
                "search_terms": search_terms,
                "ipc_candidates": unique(list(item.get("ipc_candidates") or [])),
                "cpc_candidates": unique(list(item.get("cpc_candidates") or [])),
                "evidence": evidence,
                "alternatives": [
                    text(value)
                    for value in item.get("alternatives") or []
                    if text(value)
                ],
                "support_status": "documented" if evidence else "pending_confirmation",
            }
        )
    if not any(item["role"] == "core" for item in rows):
        blockers.append(issue("NO_CORE_FEATURE", "至少需要一项有出处的核心必要技术特征。", "$.features"))
    return rows


def normalize_effects(
    payload: dict[str, Any],
    *,
    source_ids: set[str],
    feature_ids: set[str],
    blockers: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(payload.get("technical_effects") or []):
        path = f"$.technical_effects[{index}]"
        if not isinstance(item, dict):
            blockers.append(issue("EFFECT_NOT_OBJECT", "技术效果必须是对象。", path))
            continue
        effect_id = text(item.get("effect_id"))
        effect_text = text(item.get("text"))
        kind = text(item.get("kind")) or "expected"
        if not effect_id or effect_id in identifiers:
            blockers.append(issue("EFFECT_ID_INVALID", "技术效果编号缺失或重复。", path))
            continue
        identifiers.add(effect_id)
        if not effect_text:
            blockers.append(issue("EFFECT_TEXT_MISSING", "技术效果缺少表述。", path))
        related = unique(list(item.get("related_features") or []))
        unknown = [value for value in related if value not in feature_ids]
        if unknown:
            blockers.append(issue("EFFECT_FEATURE_UNKNOWN", f"效果关联了未登记特征：{', '.join(unknown)}。", f"{path}.related_features"))
        evidence = normalize_evidence(
            item.get("evidence"),
            source_ids=source_ids,
            path=f"{path}.evidence",
            blockers=blockers,
        )
        metric = item.get("metric") if isinstance(item.get("metric"), dict) else None
        if kind == "measured" and (not evidence or not metric):
            blockers.append(issue("MEASURED_EFFECT_UNSUPPORTED", f"声称已测量的效果{effect_id}缺少指标或证据。", path))
        if kind == "expected":
            warnings.append(issue("EXPECTED_EFFECT_NOT_FACT", f"效果{effect_id}是待验证预期，不得改写为已实现数据。", path, "warning"))
        rows.append(
            {
                "effect_id": effect_id,
                "text": effect_text,
                "kind": kind,
                "related_features": related,
                "metric": metric,
                "evidence": evidence,
                "support_status": "documented" if evidence else "unverified_expectation",
            }
        )
    if not rows:
        blockers.append(issue("NO_TECHNICAL_EFFECT", "缺少与技术手段建立因果关系的技术效果。", "$.technical_effects"))
    return rows


def ai_disclosure_audit(
    payload: dict[str, Any],
    *,
    source_ids: set[str],
    blockers: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    domain = text(payload.get("technology_domain")).casefold()
    if domain not in AI_DOMAINS:
        return {"applicable": False, "status": "not_applicable", "checks": []}

    raw = payload.get("ai_disclosure")
    if not isinstance(raw, dict):
        blockers.append(issue("AI_DISCLOSURE_MISSING", "AI方案缺少充分公开底稿。", "$.ai_disclosure"))
        return {"applicable": True, "status": "blocked", "checks": []}

    mode = text(raw.get("mode"))
    checks: list[dict[str, Any]] = []

    def check(code: str, label: str, present: bool, path: str) -> None:
        checks.append({"code": code, "label": label, "status": "pass" if present else "missing", "path": path})
        if not present:
            blockers.append(issue(code, f"AI充分公开缺少：{label}。", path))

    check(
        "AI_DISCLOSURE_MODE_INVALID",
        "模型构建训练、场景应用或二者混合的方案类型",
        mode in {"model_building_training", "model_application", "hybrid"},
        "$.ai_disclosure.mode",
    )

    disclosure_evidence = normalize_evidence(
        raw.get("evidence"),
        source_ids=source_ids,
        path="$.ai_disclosure.evidence",
        blockers=blockers,
    )
    check(
        "AI_DISCLOSURE_EVIDENCE_MISSING",
        "AI模块、数据流或输入输出关系的来源定位",
        bool(disclosure_evidence),
        "$.ai_disclosure.evidence",
    )

    if mode in {"model_building_training", "hybrid"}:
        check("AI_MODULES_MISSING", "必要模块或层级", bool(raw.get("modules")), "$.ai_disclosure.modules")
        check("AI_CONNECTIONS_MISSING", "模块连接或数据流", bool(raw.get("connections")), "$.ai_disclosure.connections")
        check("AI_TRAINING_STEPS_MISSING", "训练必需步骤", bool(raw.get("training_steps")), "$.ai_disclosure.training_steps")
        check("AI_TRAINING_PARAMETERS_MISSING", "训练必需参数", bool(raw.get("training_parameters")), "$.ai_disclosure.training_parameters")

    if mode in {"model_application", "hybrid"}:
        binding = raw.get("application_binding") if isinstance(raw.get("application_binding"), dict) else {}
        for key, label, code in (
            ("scenario", "模型与具体技术场景的绑定", "AI_SCENARIO_BINDING_MISSING"),
            ("input_definition", "输入数据的技术含义", "AI_INPUT_DEFINITION_MISSING"),
            ("output_definition", "输出数据的技术含义", "AI_OUTPUT_DEFINITION_MISSING"),
            ("input_output_relationship", "输入、模型处理与输出的内在关系", "AI_INPUT_OUTPUT_RELATION_MISSING"),
        ):
            check(code, label, bool(text(binding.get(key))), f"$.ai_disclosure.application_binding.{key}")

    governance = raw.get("data_governance") if isinstance(raw.get("data_governance"), dict) else {}
    if governance.get("personal_data_involved") is True:
        check("AI_LAWFUL_BASIS_MISSING", "涉及个人信息时的合法性基础", bool(text(governance.get("lawful_basis"))), "$.ai_disclosure.data_governance.lawful_basis")
        evidence = normalize_evidence(
            governance.get("evidence"),
            source_ids=source_ids,
            path="$.ai_disclosure.data_governance.evidence",
            blockers=blockers,
        )
        check("AI_GOVERNANCE_EVIDENCE_MISSING", "数据合规措施的来源定位", bool(evidence), "$.ai_disclosure.data_governance.evidence")

    contributors = raw.get("human_inventive_contributions") or []
    check("HUMAN_CONTRIBUTION_MISSING", "自然人在方案形成中的创造性贡献线索", bool(contributors), "$.ai_disclosure.human_inventive_contributions")
    for index, contributor in enumerate(contributors):
        contribution_evidence = normalize_evidence(
            contributor.get("evidence") if isinstance(contributor, dict) else None,
            source_ids=source_ids,
            path=f"$.ai_disclosure.human_inventive_contributions[{index}].evidence",
            blockers=blockers,
        )
        check(
            "HUMAN_CONTRIBUTION_EVIDENCE_MISSING",
            "自然人创造性贡献的材料或访谈定位",
            bool(contribution_evidence),
            f"$.ai_disclosure.human_inventive_contributions[{index}].evidence",
        )
    for index, candidate in enumerate(raw.get("inventor_candidates") or []):
        if isinstance(candidate, dict) and text(candidate.get("entity_type")) != "natural_person":
            blockers.append(issue("NON_HUMAN_INVENTOR", "发明人候选必须是自然人，AI、机构或其他非自然人不得列为发明人。", f"$.ai_disclosure.inventor_candidates[{index}]"))

    if not governance:
        warnings.append(issue("AI_DATA_GOVERNANCE_UNSTATED", "未说明数据是否涉及个人信息或其他合规约束，需由项目负责人确认。", "$.ai_disclosure.data_governance", "warning"))

    status = "pass" if all(item["status"] == "pass" for item in checks) else "blocked"
    return {
        "applicable": True,
        "mode": mode,
        "status": status,
        "checks": checks,
        "legal_boundary": "这是对用户底稿的完整性检查，不替代对申请文件充分公开的审查判断。",
    }


def build(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if payload.get("schema_version") != INPUT_SCHEMA:
        blockers.append(issue("INPUT_SCHEMA_INVALID", f"输入必须使用{INPUT_SCHEMA}。", "$.schema_version"))
    purpose = text(payload.get("purpose")).casefold()
    if purpose in SOFTWARE_COPYRIGHT_PURPOSES:
        blockers.append(issue("OUT_OF_SCOPE_SOFTWARE_COPYRIGHT", "本能力只处理专利，软件著作权材料必须转路由其他能力处理。", "$.purpose"))
    for path in sensitive_key_paths(payload):
        blockers.append(issue("SENSITIVE_PERSONAL_FIELD", "技术特征底稿不得收集身份证号、私人联系方式或家庭住址。", path))

    sources, source_ids = normalize_sources(payload, blockers)
    problem = normalize_problem(payload, source_ids=source_ids, blockers=blockers)
    features = normalize_features(
        payload,
        source_ids=source_ids,
        blockers=blockers,
        warnings=warnings,
    )
    effects = normalize_effects(
        payload,
        source_ids=source_ids,
        feature_ids={item["feature_id"] for item in features},
        blockers=blockers,
        warnings=warnings,
    )
    ai_audit = ai_disclosure_audit(
        payload,
        source_ids=source_ids,
        blockers=blockers,
        warnings=warnings,
    )

    blocking_codes = {item["code"] for item in blockers}
    search_blocking = {
        "INPUT_SCHEMA_INVALID",
        "OUT_OF_SCOPE_SOFTWARE_COPYRIGHT",
        "SENSITIVE_PERSONAL_FIELD",
        "NO_TECHNICAL_SOURCES",
        "TECHNICAL_PROBLEM_MISSING",
        "TECHNICAL_PROBLEM_UNSUPPORTED",
        "NO_CORE_FEATURE",
        "CORE_FEATURE_UNSUPPORTED",
    }
    search_status = "BLOCKED" if blocking_codes & search_blocking else "READY"
    drafting_status = "BLOCKED" if blockers else ("CONDITIONAL" if warnings else "READY")

    return {
        "schema_version": OUTPUT_SCHEMA,
        "case_id": text(payload.get("case_id")) or None,
        "case_revision": payload.get("case_revision"),
        "purpose": purpose or "patent",
        "technology_domain": text(payload.get("technology_domain")) or "unspecified",
        "sources": sources,
        "technical_problem": problem,
        "features": features,
        "technical_effects": effects,
        "ai_disclosure_audit": ai_audit,
        "search_units": [
            {
                "feature_id": item["feature_id"],
                "role": item["role"],
                "terms": item["search_terms"],
                "ipc_candidates": item["ipc_candidates"],
                "cpc_candidates": item["cpc_candidates"],
                "evidence": item["evidence"],
            }
            for item in features
            if item["role"] in {"core", "supporting"}
        ],
        "readiness": {
            "search": search_status,
            "drafting": drafting_status,
            "blockers": blockers,
            "warnings": warnings,
            "decision_boundary": "READY只表示底稿具备进入下一阶段的最低证据结构，不表示具备新颖性、创造性或授权前景。",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成技术特征证据图")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--strict", action="store_true", help="草拟准备度非READY时返回失败")
    arguments = parser.parse_args()
    try:
        result = build(load_object(arguments.input))
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result["readiness"], ensure_ascii=False, indent=2))
        if arguments.strict and result["readiness"]["drafting"] != "READY":
            return 2
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

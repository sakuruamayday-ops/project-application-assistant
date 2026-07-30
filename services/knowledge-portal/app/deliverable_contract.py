from __future__ import annotations

from typing import Mapping, Sequence


FOUR_QUESTION_KEYS = (
    "least_certain",
    "largest_omission",
    "most_valuable_innovation",
    "efficiency_improvement",
)
FOUR_QUESTION_LABELS = {
    "least_certain": "眼下最没有把握的事情",
    "largest_omission": "当前最大的遗漏",
    "most_valuable_innovation": "最有价值的创新改进",
    "efficiency_improvement": "效率改进方法",
}
REPORT_TASK_TYPES = frozenset(
    {
        "analysis-report",
        "project-feasibility-report",
        "enterprise-checkup-report",
        "formal-application-report",
    }
)
PEER_COMPARISON_TASK_TYPES = frozenset(
    {
        "analysis-report",
        "project-feasibility-report",
        "enterprise-checkup-report",
    }
)


def _strings(values: object) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    return list(
        dict.fromkeys(
            str(value).strip() for value in values if str(value).strip()
        )
    )


def infer_task_type(query: str, deliverable: Mapping[str, object]) -> str:
    explicit = str(deliverable.get("task_type") or "").strip()
    if explicit:
        return explicit
    if any(term in query for term in ("申报书", "正式材料", "申请书")):
        return "formal-application-report"
    if any(term in query for term in ("可行性报告", "项目分析报告")):
        return "project-feasibility-report"
    if "报告" in query:
        return "analysis-report"
    if any(term in query for term in ("复杂分析", "规则变更", "基础设施迁移")):
        return "complex-analysis"
    return "general-response"


def build_delivery_contract(
    query: str,
    deliverable: Mapping[str, object] | None,
) -> dict[str, object]:
    payload = dict(deliverable or {})
    task_type = infer_task_type(query, payload)
    skill_template = payload.get("skill_template")
    if not isinstance(skill_template, Mapping):
        skill_template = {}
    required_sections = _strings(payload.get("required_sections"))
    required_sections.extend(
        section
        for section in _strings(skill_template.get("required_sections"))
        if section not in required_sections
    )
    report_task = task_type in REPORT_TASK_TYPES
    complex_task = bool(
        payload.get("complex_task")
        or payload.get("requires_four_question_review")
        or report_task
        or task_type
        in {"complex-analysis", "rule-change", "infrastructure-migration"}
    )
    peer_required = bool(
        payload.get("peer_comparison_required")
        if "peer_comparison_required" in payload
        else task_type in PEER_COMPARISON_TASK_TYPES
    )
    policy_selection_required = bool(
        payload.get("policy_selection_required")
        or task_type
        in {
            "project-feasibility-report",
            "enterprise-checkup-report",
            "formal-application-report",
            "rule-change",
        }
    )
    return {
        "schema_version": 1,
        "task_type": task_type,
        "required_sections": required_sections,
        "requires_four_question_review": complex_task,
        "requires_peer_comparison": peer_required,
        "requires_policy_selection_trace": policy_selection_required,
        "requires_skill_template_binding": bool(skill_template),
        "skill_template": dict(skill_template),
        "completion_policy": "missing-required-item-means-needs-revision",
    }


def validate_delivery_contract(
    deliverable: Mapping[str, object] | None,
    contract: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(deliverable or {})
    failures: list[dict[str, object]] = []
    warnings: list[str] = []
    sections = payload.get("sections")
    if isinstance(sections, Mapping):
        present_sections = {
            str(name)
            for name, content in sections.items()
            if str(content or "").strip()
        }
    else:
        present_sections = set(_strings(sections))
    for section in _strings(contract.get("required_sections")):
        if section not in present_sections:
            failures.append(
                {
                    "code": "missing-required-section",
                    "item": section,
                    "message": f"缺少必填章节：{section}",
                }
            )

    if contract.get("requires_skill_template_binding"):
        skill_template = payload.get("skill_template")
        if not isinstance(skill_template, Mapping):
            skill_template = {}
        for key, label in (
            ("skill_id", "Skill标识"),
            ("template_id", "模板底稿标识"),
            ("template_version", "模板版本"),
            ("template_hash", "模板内容哈希"),
        ):
            if not str(skill_template.get(key) or "").strip():
                failures.append(
                    {
                        "code": "missing-template-binding",
                        "item": key,
                        "message": f"模板底稿未绑定{label}",
                    }
                )

    if contract.get("requires_policy_selection_trace"):
        selection = payload.get("policy_selection")
        if not isinstance(selection, Mapping):
            selection = {}
        status = str(selection.get("status") or "")
        selected_documents = selection.get("selected_documents")
        if status not in {
            "official-original",
            "official-citation-fallback",
            "management-baseline-only",
        } or not isinstance(selected_documents, list) or not selected_documents:
            failures.append(
                {
                    "code": "missing-policy-selection",
                    "item": "policy_selection",
                    "message": "缺少可追溯的政策选择与降级链记录",
                }
            )
        if selection.get("prohibited_claims"):
            failures.append(
                {
                    "code": "policy-scope-overreach",
                    "item": "prohibited_claims",
                    "message": "报告仍包含当前证据层禁止生成的年度政策结论",
                    "details": list(selection.get("prohibited_claims") or []),
                }
            )

    if contract.get("requires_peer_comparison"):
        comparison = payload.get("peer_comparison")
        if not isinstance(comparison, Mapping):
            comparison = {}
        peers = comparison.get("peers")
        dimensions = _strings(comparison.get("dimensions"))
        sourced_peers = [
            peer
            for peer in peers or []
            if isinstance(peer, Mapping)
            and str(peer.get("name") or "").strip()
            and str(peer.get("source") or peer.get("source_url") or "").strip()
        ]
        if not sourced_peers:
            failures.append(
                {
                    "code": "missing-peer-evidence",
                    "item": "peer_comparison.peers",
                    "message": "同行对比缺少至少一家有来源的同类企业",
                }
            )
        if not dimensions:
            failures.append(
                {
                    "code": "missing-peer-dimensions",
                    "item": "peer_comparison.dimensions",
                    "message": "同行对比缺少明确比较维度",
                }
            )

    if contract.get("requires_four_question_review"):
        review = payload.get("four_question_review")
        if not isinstance(review, Mapping):
            review = {}
        for key in FOUR_QUESTION_KEYS:
            answer = str(review.get(key) or "").strip()
            if not answer:
                failures.append(
                    {
                        "code": "missing-four-question-answer",
                        "item": key,
                        "message": f"四问复盘未回答：{FOUR_QUESTION_LABELS[key]}",
                    }
                )
            elif answer in {
                FOUR_QUESTION_LABELS[key],
                f"{FOUR_QUESTION_LABELS[key]}是什么？",
            }:
                failures.append(
                    {
                        "code": "empty-four-question-answer",
                        "item": key,
                        "message": (
                            "四问复盘只复述问题、没有实际回答："
                            f"{FOUR_QUESTION_LABELS[key]}"
                        ),
                    }
                )

    status = "passed" if not failures else "needs-revision"
    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "missing_items": [str(item["item"]) for item in failures],
        "repair_instructions": [str(item["message"]) for item in failures],
        "completion_allowed": not failures,
    }

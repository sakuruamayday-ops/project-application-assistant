from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
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
DELIVERY_PROFILE_SKILLS = frozenset(
    {
        "enterprise-panorama-analysis",
        "manufacturing-tax-risk-analysis",
        "sme-score-preassessment",
        "sme-development-projects",
    }
)
ARTIFACT_PASS_STATUSES = {"passed", "verified"}
EVIDENCE_PASS_STATUSES = {
    "verified",
    "computed",
    "claimed",
    "missing",
    "conflicting",
    "current-not-found",
}
SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


@lru_cache(maxsize=1)
def _delivery_registry() -> dict[str, object]:
    configured = os.environ.get("JIAOTANG_DELIVERY_CONTRACTS", "").strip()
    path = (
        Path(configured).expanduser()
        if configured
        else Path(__file__).resolve().parents[3] / "skills" / "delivery-contracts.json"
    )
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"delivery_profiles": {}, "profile_selectors": {}}
    if not isinstance(registry, dict):
        return {"delivery_profiles": {}, "profile_selectors": {}}
    return registry


def _normalized_variant(value: object) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "a": "A",
        "第一版": "A",
        "标准销售版": "A",
        "普通版": "A",
        "b": "B",
        "第二版": "B",
        "gcip深度顾问版": "B",
        "深度顾问版": "B",
        "专业版": "B",
        "c": "C",
        "全生成": "C",
        "两版": "C",
        "全部生成": "C",
    }
    return aliases.get(normalized, str(value or "").strip())


def _normalized_case_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "filing-ready": "filing-ready",
        "正式提交": "filing-ready",
        "提交前": "filing-ready",
        "完整申请": "filing-ready",
    }
    return aliases.get(normalized, str(value or "").strip())


def infer_delivery_profile(deliverable: Mapping[str, object]) -> tuple[str, str]:
    explicit = str(deliverable.get("delivery_profile") or "").strip()
    profiles = _delivery_registry().get("delivery_profiles")
    if not isinstance(profiles, Mapping):
        profiles = {}
    if explicit:
        return (
            explicit,
            "" if explicit in profiles else f"未登记的交付profile：{explicit}",
        )
    template = deliverable.get("skill_template")
    if not isinstance(template, Mapping):
        template = {}
    skill_id = str(
        deliverable.get("skill_id") or template.get("skill_id") or ""
    ).strip()
    selectors = _delivery_registry().get("profile_selectors")
    if not isinstance(selectors, Mapping):
        selectors = {}
    selector = selectors.get(skill_id)
    if not isinstance(selector, Mapping):
        return "", ""
    case_mode = _normalized_case_mode(
        deliverable.get("case_mode") or template.get("case_mode")
    )
    by_case_mode = selector.get("by_case_mode")
    if isinstance(by_case_mode, Mapping):
        if not case_mode:
            return "", ""
        profile_id = str(by_case_mode.get(case_mode) or "").strip()
        if not profile_id:
            return "", f"{skill_id}不支持案件模式：{case_mode}"
        return profile_id, ""
    variant = _normalized_variant(
        deliverable.get("report_variant")
        or deliverable.get("variant")
        or template.get("report_variant")
    )
    by_variant = selector.get("by_report_variant")
    if isinstance(by_variant, Mapping):
        if not variant:
            return "", f"{skill_id}必须先锁定报告版本"
        profile_id = str(by_variant.get(variant) or "").strip()
        if not profile_id:
            return "", f"{skill_id}不支持报告版本：{variant}"
        return profile_id, ""
    return str(selector.get("default") or "").strip(), ""


def _profile(profile_id: str) -> dict[str, object]:
    profiles = _delivery_registry().get("delivery_profiles")
    if not profile_id or not isinstance(profiles, Mapping):
        return {}
    value = profiles.get(profile_id)
    return dict(value) if isinstance(value, Mapping) else {}


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
    profile_id, profile_error = infer_delivery_profile(payload)
    profile = _profile(profile_id)
    skill_template = payload.get("skill_template")
    if not isinstance(skill_template, Mapping):
        skill_template = {}
    required_sections = _strings(payload.get("required_sections"))
    required_sections.extend(
        section
        for section in _strings(skill_template.get("required_sections"))
        if section not in required_sections
    )
    required_sections.extend(
        section
        for section in _strings(profile.get("required_sections"))
        if section not in required_sections
    )
    report_task = task_type in REPORT_TASK_TYPES
    if "requires_four_question_review" in payload:
        complex_task = bool(payload["requires_four_question_review"])
    elif "requires_four_question_review" in profile:
        complex_task = bool(profile["requires_four_question_review"])
    else:
        complex_task = bool(
            payload.get("complex_task")
            or report_task
            or task_type
            in {"complex-analysis", "rule-change", "infrastructure-migration"}
        )
    peer_required = bool(
        payload.get("peer_comparison_required")
        if "peer_comparison_required" in payload
        else (
            profile.get("requires_peer_comparison")
            if "requires_peer_comparison" in profile
            else task_type in PEER_COMPARISON_TASK_TYPES
        )
    )
    policy_selection_required = bool(
        payload.get("policy_selection_required")
        if "policy_selection_required" in payload
        else (
            profile.get("requires_policy_selection_trace")
            if "requires_policy_selection_trace" in profile
            else task_type
            in {
                "project-feasibility-report",
                "enterprise-checkup-report",
                "formal-application-report",
                "rule-change",
            }
        )
    )
    branding_contracts = profile.get("branding_contracts")
    if not isinstance(branding_contracts, list):
        single_branding = profile.get("branding")
        branding_contracts = [single_branding] if isinstance(single_branding, Mapping) else []
    return {
        "schema_version": 2,
        "task_type": task_type,
        "delivery_profile": profile_id,
        "delivery_profile_error": profile_error,
        "delivery_profile_spec": profile,
        "required_sections": required_sections,
        "requires_four_question_review": complex_task,
        "requires_peer_comparison": peer_required,
        "requires_policy_selection_trace": policy_selection_required,
        "requires_skill_template_binding": bool(skill_template),
        "requires_source_trace": bool(profile.get("requires_source_trace")),
        "requires_evidence_ledger": bool(profile.get("requires_evidence_ledger")),
        "required_tables": list(profile.get("required_tables") or []),
        "required_artifacts": list(profile.get("required_artifacts") or []),
        "branding_contracts": [
            dict(item) for item in branding_contracts if isinstance(item, Mapping)
        ],
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
    profile_error = str(contract.get("delivery_profile_error") or "").strip()
    if profile_error:
        failures.append(
            {
                "code": "missing-delivery-profile",
                "item": "delivery_profile",
                "message": profile_error,
            }
        )
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

    source_ids: set[str] = set()
    sources = payload.get("sources")
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            source_id = str(source.get("id") or source.get("source_id") or "").strip()
            title = str(source.get("title") or source.get("name") or "").strip()
            locator = str(
                source.get("url")
                or source.get("source_url")
                or source.get("document_id")
                or source.get("path")
                or ""
            ).strip()
            if source_id and title and locator:
                source_ids.add(source_id)
    if contract.get("requires_source_trace") and not source_ids:
        failures.append(
            {
                "code": "missing-source-trace",
                "item": "sources",
                "message": "缺少同时含来源标识、标题和可验证定位信息的来源清单",
            }
        )

    evidence_items = payload.get("evidence_items")
    valid_evidence = []
    if isinstance(evidence_items, Sequence) and not isinstance(
        evidence_items, (str, bytes)
    ):
        for item in evidence_items:
            if not isinstance(item, Mapping):
                continue
            claim = str(
                item.get("claim_id")
                or item.get("field")
                or item.get("claim")
                or ""
            ).strip()
            status = str(item.get("status") or "").strip()
            item_sources = set(_strings(item.get("source_ids")))
            if (
                claim
                and status in EVIDENCE_PASS_STATUSES
                and item_sources
                and item_sources <= source_ids
            ):
                valid_evidence.append(item)
    if contract.get("requires_evidence_ledger") and not valid_evidence:
        failures.append(
            {
                "code": "missing-evidence-ledger",
                "item": "evidence_items",
                "message": "证据台账缺少可回指来源清单的事实或判断记录",
            }
        )

    tables_by_id: dict[str, Mapping[str, object]] = {}
    tables = payload.get("tables")
    if isinstance(tables, Mapping):
        tables_by_id = {
            str(table_id): table
            for table_id, table in tables.items()
            if isinstance(table, Mapping)
        }
    elif isinstance(tables, Sequence) and not isinstance(tables, (str, bytes)):
        tables_by_id = {
            str(table.get("id") or table.get("name") or ""): table
            for table in tables
            if isinstance(table, Mapping)
            and str(table.get("id") or table.get("name") or "").strip()
        }
    for raw_specification in contract.get("required_tables") or []:
        if not isinstance(raw_specification, Mapping):
            continue
        table_id = str(raw_specification.get("id") or "").strip()
        table = tables_by_id.get(table_id)
        if table is None:
            failures.append(
                {
                    "code": "missing-required-table",
                    "item": table_id,
                    "message": f"缺少内置表格或工作表：{table_id}",
                }
            )
            continue
        columns = set(
            _strings(table.get("columns") or table.get("headers"))
        )
        missing_columns = [
            column
            for column in _strings(raw_specification.get("required_columns"))
            if column not in columns
        ]
        if missing_columns:
            failures.append(
                {
                    "code": "missing-table-columns",
                    "item": table_id,
                    "message": (
                        f"表格{table_id}缺少必填列："
                        + "、".join(missing_columns)
                    ),
                    "details": missing_columns,
                }
            )
        minimum_rows = int(raw_specification.get("min_rows") or 0)
        row_count = int(
            table.get("row_count")
            or (
                len(table.get("rows") or [])
                if isinstance(table.get("rows"), list)
                else 0
            )
        )
        if row_count < minimum_rows:
            failures.append(
                {
                    "code": "insufficient-table-rows",
                    "item": table_id,
                    "message": (
                        f"表格{table_id}有效行数为{row_count}，"
                        f"至少需要{minimum_rows}行"
                    ),
                }
            )

    artifacts_by_role: dict[str, Mapping[str, object]] = {}
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, Sequence) and not isinstance(
        artifacts, (str, bytes)
    ):
        artifacts_by_role = {
            str(artifact.get("role") or ""): artifact
            for artifact in artifacts
            if isinstance(artifact, Mapping)
            and str(artifact.get("role") or "").strip()
        }
    for raw_specification in contract.get("required_artifacts") or []:
        if not isinstance(raw_specification, Mapping):
            continue
        role = str(raw_specification.get("role") or "").strip()
        artifact = artifacts_by_role.get(role)
        if artifact is None:
            failures.append(
                {
                    "code": "missing-required-artifact",
                    "item": role,
                    "message": f"缺少必交付产物：{role}",
                }
            )
            continue
        actual_format = str(artifact.get("format") or "").lower().lstrip(".")
        allowed_formats = {
            value.lower().lstrip(".")
            for value in _strings(raw_specification.get("formats"))
        }
        digest = str(artifact.get("sha256") or "").strip()
        validation = artifact.get("validation")
        if not isinstance(validation, Mapping):
            validation = {}
        required_gate = str(
            raw_specification.get("validation_gate") or ""
        ).strip()
        if allowed_formats and actual_format not in allowed_formats:
            failures.append(
                {
                    "code": "artifact-format-mismatch",
                    "item": role,
                    "message": (
                        f"产物{role}格式为{actual_format or '未声明'}，"
                        f"要求为{'/'.join(sorted(allowed_formats))}"
                    ),
                }
            )
        if raw_specification.get("requires_sha256") and not SHA256_PATTERN.fullmatch(
            digest
        ):
            failures.append(
                {
                    "code": "missing-artifact-hash",
                    "item": role,
                    "message": f"产物{role}缺少有效SHA-256",
                }
            )
        validation_digest = str(validation.get("artifact_sha256") or "").strip()
        if (
            str(validation.get("status") or "") not in ARTIFACT_PASS_STATUSES
            or (required_gate and validation.get("gate") != required_gate)
            or bool(digest and not validation_digest)
            or (
                digest
                and validation_digest
                and digest.removeprefix("sha256:").lower()
                != validation_digest.removeprefix("sha256:").lower()
            )
        ):
            failures.append(
                {
                    "code": "artifact-validation-not-passed",
                    "item": role,
                    "message": (
                        f"产物{role}未取得指定验证器"
                        f"{required_gate or '交付'}的同哈希通过记录"
                    ),
                }
            )

    branding_contracts = contract.get("branding_contracts")
    if not isinstance(branding_contracts, list):
        branding_contracts = []
    for branding_contract in branding_contracts:
        if not isinstance(branding_contract, Mapping) or not branding_contract:
            continue
        branding_audits = payload.get("branding_audits")
        audits_by_role: dict[str, Mapping[str, object]] = {}
        if isinstance(branding_audits, Sequence) and not isinstance(
            branding_audits, (str, bytes)
        ):
            audits_by_role = {
                str(audit.get("artifact_role") or ""): audit
                for audit in branding_audits
                if isinstance(audit, Mapping)
                and str(audit.get("artifact_role") or "").strip()
            }
        for role in _strings(branding_contract.get("artifact_roles")):
            audit = audits_by_role.get(role)
            artifact = artifacts_by_role.get(role, {})
            if audit is None:
                failures.append(
                    {
                        "code": "missing-branding-audit",
                        "item": role,
                        "message": f"产物{role}缺少品牌/免水印审计记录",
                    }
                )
                continue
            mode = str(branding_contract.get("mode") or "")
            expected_variant = str(branding_contract.get("variant") or "")
            units = int(
                audit.get("pages")
                or audit.get("sheets")
                or audit.get("slides")
                or 0
            )
            watermarks = int(audit.get("watermarks") or 0)
            artifact_digest = str(artifact.get("sha256") or "")
            audit_digest = str(audit.get("artifact_sha256") or "")
            passed = str(audit.get("status") or "") in ARTIFACT_PASS_STATUSES
            if mode == "required":
                passed = (
                    passed
                    and bool(audit.get("centered"))
                    and units > 0
                    and watermarks == units
                    and (
                        not expected_variant
                        or str(audit.get("variant") or "") == expected_variant
                    )
                )
            elif mode == "forbidden":
                passed = passed and watermarks == 0
            if artifact_digest:
                passed = passed and bool(audit_digest) and (
                    artifact_digest.removeprefix("sha256:").lower()
                    == audit_digest.removeprefix("sha256:").lower()
                )
            if not passed:
                failures.append(
                    {
                        "code": "branding-audit-not-passed",
                        "item": role,
                        "message": (
                            f"产物{role}未通过"
                            + (
                                "逐页居中品牌水印审计"
                                if mode == "required"
                                else "A版永久免水印审计"
                            )
                        ),
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
    audit = {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "missing_items": [str(item["item"]) for item in failures],
        "repair_instructions": [str(item["message"]) for item in failures],
        "completion_allowed": not failures,
    }
    audit["repair_plan"] = build_delivery_repair_plan(payload, contract, failures)
    return audit


def _repair_task(
    failure: Mapping[str, object],
    *,
    target_path: str,
    action: str,
    required_inputs: Sequence[str],
    preferred_sources: Sequence[str],
    acceptance_criteria: Sequence[str],
    priority: str = "blocking",
) -> dict[str, object]:
    code = str(failure.get("code") or "delivery-contract-failure")
    item = str(failure.get("item") or "")
    return {
        "task_id": f"repair-{code}-{item}".replace("_", "-").replace(".", "-"),
        "failure_code": code,
        "target_path": target_path,
        "action": action,
        "required_inputs": list(required_inputs),
        "preferred_sources": list(preferred_sources),
        "acceptance_criteria": list(acceptance_criteria),
        "priority": priority,
        "blocking": priority == "blocking",
        "status": "pending",
    }


def build_delivery_repair_plan(
    deliverable: Mapping[str, object] | None,
    contract: Mapping[str, object],
    failures: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    payload = dict(deliverable or {})
    tasks: list[dict[str, object]] = []
    for failure in failures:
        code = str(failure.get("code") or "")
        item = str(failure.get("item") or "")
        if code == "missing-delivery-profile":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="delivery_profile",
                    action=(
                        "先根据实际触发Skill和用户已确认的报告版本选择已登记交付profile；"
                        "全景报告必须明确A标准销售版、B深度顾问版或C两版。"
                    ),
                    required_inputs=["实际触发Skill", "用户确认的报告版本或任务阶段"],
                    preferred_sources=["delivery-contracts.json.profile_selectors"],
                    acceptance_criteria=[
                        "delivery_profile命中已登记profile",
                        "不得由模型自行替用户选择全景报告版本",
                    ],
                )
            )
        elif code == "missing-required-section":
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"sections.{item}",
                    action=(
                        f"按已绑定模板在正确顺序插入“{item}”章节，"
                        "从现有事实、判断和来源中回填内容；无证据的字段明确标为待补。"
                    ),
                    required_inputs=[
                        "模板中该章节的字段定义与顺序",
                        "本次任务已核验事实",
                        "对应结论的政策或材料来源",
                    ],
                    preferred_sources=[
                        "已绑定Skill模板底稿",
                        "用户提供材料",
                        "政府官网原文或已审计官方附件",
                    ],
                    acceptance_criteria=[
                        f"sections.{item}存在且正文非空",
                        "章节内事实、判断与来源可逐项追溯",
                    ],
                )
            )
        elif code == "missing-source-trace":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="sources",
                    action=(
                        "补齐来源清单；每条来源写入稳定id、标题和政府URL、"
                        "用户材料路径或知识库文档id，供证据台账回指。"
                    ),
                    required_inputs=["正文中的事实与判断", "本轮实际读取的原文和用户材料"],
                    preferred_sources=["政府官网原文", "用户提供材料", "已审计知识库原文"],
                    acceptance_criteria=[
                        "至少一条来源同时含id、title/name与可验证定位信息",
                        "来源不是泛称或模型记忆",
                    ],
                )
            )
        elif code == "missing-evidence-ledger":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="evidence_items",
                    action=(
                        "为报告核心事实、计算和判断建立证据记录；逐条写明claim_id、"
                        "证据状态和source_ids，并确保source_ids能在来源清单解析。"
                    ),
                    required_inputs=["报告核心断言", "sources来源清单"],
                    preferred_sources=["用户材料页码", "官方原文", "结构化计算底稿"],
                    acceptance_criteria=[
                        "至少一条证据记录可解析到已登记来源",
                        "未知、冲突和当前未命中具有显式状态",
                    ],
                )
            )
        elif code in {
            "missing-required-table",
            "missing-table-columns",
            "insufficient-table-rows",
        }:
            specification = next(
                (
                    raw
                    for raw in contract.get("required_tables") or []
                    if isinstance(raw, Mapping) and raw.get("id") == item
                ),
                {},
            )
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"tables.{item}",
                    action=(
                        f"使用已绑定模板或确定性生成器补齐内置表格/工作表“{item}”；"
                        "保留模板列顺序、公式和来源列，不用模型临时重建近似表格。"
                    ),
                    required_inputs=[
                        "模板底稿或生成器",
                        "企业事实与计算底稿",
                        "证据来源",
                    ],
                    preferred_sources=["已签名Skill资产", "本次企业事实契约"],
                    acceptance_criteria=[
                        f"tables.{item}存在",
                        "必填列完整："
                        + "、".join(_strings(specification.get("required_columns"))),
                        (
                            f"有效行数不少于{specification.get('min_rows')}"
                            if specification.get("min_rows")
                            else "表结构通过生成器校验"
                        ),
                    ],
                )
            )
        elif code in {
            "missing-required-artifact",
            "artifact-format-mismatch",
            "missing-artifact-hash",
            "artifact-validation-not-passed",
        }:
            specification = next(
                (
                    raw
                    for raw in contract.get("required_artifacts") or []
                    if isinstance(raw, Mapping) and raw.get("role") == item
                ),
                {},
            )
            gate = str(specification.get("validation_gate") or "交付验证器")
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"artifacts.{item}",
                    action=(
                        f"由已签名模板生成器重新生成产物“{item}”，运行{gate}；"
                        "记录文件路径、格式、SHA-256及验证器对同一哈希的通过结果。"
                    ),
                    required_inputs=["模板生成输入", "产物原文件", "指定验证器"],
                    preferred_sources=["已签名Skill生成器", "共享品牌与文档校验运行时"],
                    acceptance_criteria=[
                        "产物格式属于："
                        + "/".join(_strings(specification.get("formats"))),
                        "产物SHA-256为64位十六进制",
                        f"validation.gate={gate}且status=passed",
                        "validation.artifact_sha256与产物哈希一致",
                    ],
                )
            )
        elif code in {"missing-branding-audit", "branding-audit-not-passed"}:
            branding = next(
                (
                    raw
                    for raw in contract.get("branding_contracts") or []
                    if isinstance(raw, Mapping)
                    and item in _strings(raw.get("artifact_roles"))
                ),
                {},
            )
            mode = str(branding.get("mode") or "")
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"branding_audits.{item}",
                    action=(
                        (
                            "对最终PDF运行共享品牌双遍处理与逐页交付闸门，"
                            "确认每页恰有一个同尺寸居中金色品牌水印。"
                        )
                        if mode == "required"
                        else (
                            "对A标准销售版运行免水印检查，确认主水印与角标水印均为0；"
                            "同时保留报告人和作者元数据检查。"
                        )
                    ),
                    required_inputs=["最终产物", "产物SHA-256", "品牌配置与交付闸门"],
                    preferred_sources=["skills/_runtime/gongchuang-branding"],
                    acceptance_criteria=[
                        "branding_audit.status=passed",
                        "branding_audit.artifact_sha256与产物哈希一致",
                        (
                            "watermarks=pages/sheets/slides、centered=true且variant正确"
                            if mode == "required"
                            else "watermarks=0"
                        ),
                    ],
                )
            )
        elif code == "missing-template-binding":
            labels = {
                "skill_id": "Skill标识",
                "template_id": "模板底稿标识",
                "template_version": "模板版本",
                "template_hash": "模板内容哈希",
            }
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"skill_template.{item}",
                    action=(
                        f"从实际读取的Skill和模板底稿写入{labels.get(item, item)}，"
                        "禁止凭名称猜测版本或哈希。"
                    ),
                    required_inputs=["实际Skill清单", "实际模板文件元数据"],
                    preferred_sources=["本次运行已读取的SKILL.md", "模板原文件"],
                    acceptance_criteria=[
                        f"skill_template.{item}为非空真实值",
                        "模板内容哈希可由模板原文件复算",
                    ],
                )
            )
        elif code == "missing-policy-selection":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="policy_selection",
                    action=(
                        "重新执行政策选择降级链：发文机关原文→下级政府官网明确引用"
                        "→最近一次申报采用的管理办法；记录每级命中或未命中结果。"
                    ),
                    required_inputs=[
                        "目标项目、地区、判断年度和查询日",
                        "候选政策标题、文号、发布日期、状态与URL",
                    ],
                    preferred_sources=[
                        "发文机关政府官网",
                        "下级政府官网的上级文件引用",
                        "政府公报或已审计官方附件",
                    ],
                    acceptance_criteria=[
                        "policy_selection.status属于允许状态",
                        "selected_documents至少一份且含可验证来源",
                        "征求意见稿与正式政策状态分开标注",
                    ],
                )
            )
        elif code == "policy-scope-overreach":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="policy_selection.prohibited_claims",
                    action=(
                        "逐条定位越界结论：删除、改为预测或改为“当前检索层未命中”；"
                        "征求意见稿不得写成已生效，但可作为前瞻准备主基线。"
                    ),
                    required_inputs=[
                        "prohibited_claims明细",
                        "每条结论对应的证据层和政策状态",
                    ],
                    preferred_sources=["政策选择审计轨迹", "政策时间类型检查结果"],
                    acceptance_criteria=[
                        "prohibited_claims为空",
                        "预测、历史事实与当前正式判断具有不同标签",
                    ],
                )
            )
        elif code == "missing-peer-evidence":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="peer_comparison.peers",
                    action=(
                        "从同一项目公示名单中选择至少一家同地区、同项目或同细分领域企业，"
                        "补入企业名称、可比理由、名单年度和来源URL。"
                    ),
                    required_inputs=["目标企业所属行业与项目", "同项目政府公示名单"],
                    preferred_sources=[
                        "政府认定或公示名单",
                        "政府官网企业案例",
                        "企业官网仅作辅助",
                    ],
                    acceptance_criteria=[
                        "至少一家同行同时含name与source_url",
                        "可比理由没有跨项目或跨产业环节",
                    ],
                )
            )
        elif code == "missing-peer-dimensions":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="peer_comparison.dimensions",
                    action=(
                        "按项目门槛和报告目标补齐比较维度；至少覆盖资格门槛、"
                        "研发创新、市场或产业链位置，并说明统一口径。"
                    ),
                    required_inputs=["项目门槛字段", "企业事实字段", "同行公开字段"],
                    preferred_sources=["正式管理办法", "同一批次名单附件", "企业申报材料"],
                    acceptance_criteria=[
                        "dimensions为非空列表",
                        "每个维度在目标企业和同行间使用同一口径",
                    ],
                )
            )
        elif code in {
            "missing-four-question-answer",
            "empty-four-question-answer",
        }:
            label = FOUR_QUESTION_LABELS.get(item, item)
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"four_question_review.{item}",
                    action=(
                        f"结合本次实际证据、缺口和实现结果，写出“{label}”的具体答案；"
                        "不得只复述问题。"
                    ),
                    required_inputs=[
                        "本次未核验或存在冲突的事实",
                        "尚未完成的覆盖单元",
                        "已实施的改进与测试结果",
                    ],
                    preferred_sources=["本次审计结果", "测试日志", "政策覆盖矩阵"],
                    acceptance_criteria=[
                        f"four_question_review.{item}为非空具体回答",
                        "答案包含本次任务特有对象或证据，不是通用套话",
                    ],
                )
            )
        else:
            tasks.append(
                _repair_task(
                    failure,
                    target_path=item,
                    action=str(failure.get("message") or "修复交付契约失败项"),
                    required_inputs=["失败项对应的原始内容与证据"],
                    preferred_sources=["本次任务已核验来源"],
                    acceptance_criteria=[f"门禁失败项{code}不再出现"],
                )
            )
    return {
        "schema_version": 1,
        "status": "not-needed" if not tasks else "repair-required",
        "task_count": len(tasks),
        "blocking_task_count": sum(task["blocking"] for task in tasks),
        "tasks": tasks,
        "rerun": {
            "required": bool(tasks),
            "action": "完成全部阻断任务后重新执行delivery_contract_audit",
            "pass_condition": "completion_allowed=true",
        },
        "context": {
            "task_type": contract.get("task_type"),
            "template_bound": bool(payload.get("skill_template")),
        },
    }

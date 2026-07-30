from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping, Sequence

from app.policy_lifecycle import build_policy_dependency_graph
from app.rule_structure import audit_composite_rule_structure


RULE_IR_SCHEMA_VERSION = 1
SHARED_KERNEL_VERSION = "1.4"
SHARED_EXECUTION_KERNELS = (
    "task-omission-preflight",
    "project-router",
    "policy-version-gate",
    "policy-time-type-checker",
    "policy-retrieval-cascade",
    "fact-contract-normalizer",
    "evidence-conflict-resolver",
    "layer-selector",
    "native-rule-combinator",
    "composite-rule-structure-gate",
    "requirement-comparator",
    "lifecycle-state-machine",
    "coverage-hash-planner",
    "policy-change-impact-simulator",
    "four-city-policy-transition-resolver",
    "deliverable-contract-gate",
    "deliverable-contract-auto-repair",
    "explanation-trace",
)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_algorithm_packs(pack_dir: Path) -> list[dict[str, object]]:
    packs: list[dict[str, object]] = []
    for path in sorted(pack_dir.glob("*.json")):
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}顶层必须为对象")
        packs.append(payload)
    return packs


def lifecycle_rule_index(
    lifecycle_payload: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    index: dict[str, dict[str, object]] = {}
    for raw_rule in lifecycle_payload.get("projects", []):
        if not isinstance(raw_rule, Mapping):
            continue
        rule = dict(raw_rule)
        project_name = str(rule.get("project_name") or "").strip()
        if not project_name:
            continue
        for name in [project_name, *rule.get("aliases", [])]:
            normalized_name = str(name or "").strip()
            if normalized_name:
                index.setdefault(normalized_name, rule)
    return index


def policy_version_id(
    project: Mapping[str, object],
    lifecycle_rule: Mapping[str, object] | None = None,
) -> str:
    basis = {
        "project_id": project.get("project_id"),
        "project_name": project.get("project_name"),
        "version": project.get("version"),
        "rule_layers": project.get("rule_layers", []),
        "rule_cards": project.get("rule_cards", []),
        "lifecycle_rule": dict(lifecycle_rule or {}),
    }
    return f"policy-{content_digest(basis)[:20]}"


def _derived_confirmed_rule_baseline(
    project: Mapping[str, object],
) -> dict[str, object]:
    documents: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    layers = [
        layer
        for layer in project.get("rule_layers", [])
        if isinstance(layer, Mapping)
    ]
    rules = [
        rule
        for layer in layers
        for rule in layer.get("rules", [])
        if isinstance(rule, Mapping)
    ] or [
        rule
        for rule in project.get("rule_cards", [])
        if isinstance(rule, Mapping)
    ]
    for rule in rules:
        if rule.get("source_display") is False:
            continue
        title = str(rule.get("source") or "").strip()
        url = str(rule.get("source_url") or "").strip()
        if not title and not url:
            continue
        source_key = (title, url)
        if source_key in seen:
            continue
        seen.add(source_key)
        approved_at = str(rule.get("approved_at") or "")
        year_match = re.search(r"(20\d{2})", approved_at + title)
        documents.append(
            {
                "document_id": (
                    f"{project.get('project_id')}-confirmed-"
                    f"{content_digest(source_key)[:12]}"
                ),
                "title": title or url,
                "issued_year": int(year_match.group(1)) if year_match else 0,
                "status": "current",
                "authority": "正式规则源所载主管部门",
                "official_url": url,
                "relation": "governed-by",
                "current_upstream_basis": True,
            }
        )
    return {
        "baseline_status": "complete",
        "decision_mode": "confirmed-threshold-rules",
        "policy_documents": documents,
        "dependencies": [],
        "provenance": "derived-from-confirmed-rule-cards",
    }


def apply_policy_baselines(
    packs: Sequence[Mapping[str, object]],
    baseline_registry: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    registry_by_project = {
        str(item.get("project_id") or ""): dict(item)
        for item in (baseline_registry or {}).get("baselines", [])
        if isinstance(item, Mapping) and str(item.get("project_id") or "")
    }
    enriched: list[dict[str, object]] = []
    for raw_pack in packs:
        pack = dict(raw_pack)
        project_id = str(pack.get("project_id") or "")
        baseline = registry_by_project.get(project_id)
        if baseline:
            pack["policy_baseline"] = baseline
            if str(pack.get("coverage_status") or "") == "routing-only":
                pack["coverage_status"] = "policy-baseline-confirmed"
        elif str(pack.get("coverage_status") or "") == "rules-confirmed":
            pack["policy_baseline"] = _derived_confirmed_rule_baseline(pack)
        enriched.append(pack)
    return enriched


def build_algorithm_card(
    project: Mapping[str, object],
    lifecycle_rule: Mapping[str, object] | None = None,
) -> dict[str, object]:
    project_id = str(project.get("project_id") or "")
    coverage_status = str(project.get("coverage_status") or "routing-only")
    rule_layers = [
        layer
        for layer in project.get("rule_layers", [])
        if isinstance(layer, Mapping)
    ]
    confirmed_rules = [
        rule
        for layer in rule_layers
        for rule in layer.get("rules", [])
        if isinstance(rule, Mapping)
        and str(rule.get("review_status") or "") == "confirmed"
    ]
    if not rule_layers:
        confirmed_rules = [
            rule
            for rule in project.get("rule_cards", [])
            if isinstance(rule, Mapping)
            and str(rule.get("review_status") or "") == "confirmed"
        ]
    structure_audit = audit_composite_rule_structure(project)
    return {
        "schema_version": 1,
        "algorithm_id": f"project-decision-{project_id}",
        "algorithm_name": f"{project.get('project_name', '')}项目决策算法",
        "algorithm_version": str(project.get("version") or "1.0"),
        "project_id": project_id,
        "project_name": str(project.get("project_name") or ""),
        "coverage_status": coverage_status,
        "decision_boundary": (
            "已确认政策规则可形成门槛判断；年度通知与属地规则仍按适用层选择。"
            if coverage_status == "rules-confirmed"
            else (
                "已补齐最新政策基线、适用窗口和依赖关系；未编译完整门槛前，"
                "仅作政策查询、预测准备和历史回放，不直接形成符合或不符合结论。"
                if coverage_status == "policy-baseline-confirmed"
                else "仅识别项目并路由政策证据，不直接形成符合或不符合结论。"
            )
        ),
        "policy_version_id": policy_version_id(project, lifecycle_rule),
        "inputs": {
            "project_context": "项目名称、年度、申请类型与属地",
            "enterprise_facts": "统一事实契约中的字段、值、证据状态与来源",
            "as_of": "判断或回放的时间点",
        },
        "outputs": {
            "preflight_trace": "任务目标、高影响遗漏、低影响假设与单次最小追问",
            "conclusion": "eligible、conditional、ineligible或undetermined",
            "conclusion_semantics": "当前判断、历史事实、预测或回测模拟",
            "rule_trace": "选中的规则层、逐规则比较和证据引用",
            "lifecycle_trace": "认定、复核、重新认定、变更或撤销迁移",
        },
        "shared_execution_kernels": list(SHARED_EXECUTION_KERNELS),
        "project_specific_assets": {
            "fact_fields": len(project.get("fact_fields", [])),
            "confirmed_rules": len(confirmed_rules),
            "rule_layers": len(rule_layers),
            "gold_cases": len(project.get("gold_cases", [])),
        },
        "explainability": {
            "level": "field-and-source-trace",
            "requirements": [
                "结论必须回指规则ID和政策版本",
                "事实必须保留证据状态与来源",
                "未知或冲突事实不得静默转为满足",
            ],
        },
        "incremental_update": {
            "strategy": "content-addressed-compile",
            "unchanged": "复用已编译项目节点和算法卡",
            "changed": "仅重编译源内容哈希发生变化的项目节点",
        },
        "quality_gates": {
            "task_preflight_required": True,
            "policy_time_checked": True,
            "native_rule_combinator": True,
            "composite_rule_structure": structure_audit,
            "deliverable_contract_required": True,
            "policy_retrieval_cascade_required": True,
            "pack_validation": True,
            "gold_case_count": len(project.get("gold_cases", [])),
            "formal_decision_enabled": (
                coverage_status == "rules-confirmed"
                and structure_audit["formal_decision_allowed"]
            ),
            "policy_baseline_complete": coverage_status in {
                "rules-confirmed",
                "policy-baseline-confirmed",
            },
        },
        "limitations": [
            (
                "政策基线完整但尚未编译全部门槛规则"
                if coverage_status == "policy-baseline-confirmed"
                else "routing-only项目尚未具备正式门槛规则"
                if coverage_status == "routing-only"
                else "年度通知与属地覆盖仍须按查询时点选择"
            ),
            "名单未披露或主体匹配冲突时只能输出待核验",
            "算法不替代主管部门最终审核结论",
        ],
    }


def project_compile_input_hash(
    project: Mapping[str, object],
    lifecycle_rule: Mapping[str, object] | None,
    fact_contract: Mapping[str, object],
) -> str:
    """Return the exact dependency hash for one project compilation unit."""
    return content_digest(
        {
            "project": dict(project),
            "lifecycle_rule": dict(lifecycle_rule or {}),
            "fact_contract": dict(fact_contract),
            "compiler_schema": RULE_IR_SCHEMA_VERSION,
            "kernel_version": SHARED_KERNEL_VERSION,
        }
    )


def compile_rule_ir(
    packs: Sequence[Mapping[str, object]],
    lifecycle_payload: Mapping[str, object],
    fact_contract: Mapping[str, object],
    baseline_registry: Mapping[str, object] | None = None,
    *,
    previous_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    lifecycle_rules = lifecycle_rule_index(lifecycle_payload)
    sorted_packs = sorted(
        apply_policy_baselines(packs, baseline_registry),
        key=lambda item: str(item.get("project_id") or ""),
    )
    source_basis = {
        "packs": sorted_packs,
        "lifecycle": lifecycle_payload,
        "fact_contract": fact_contract,
        "compiler_schema": RULE_IR_SCHEMA_VERSION,
        "kernel_version": SHARED_KERNEL_VERSION,
        "policy_baseline_registry": dict(baseline_registry or {}),
    }
    source_digest = content_digest(source_basis)
    projects: dict[str, dict[str, object]] = {}
    alias_index: dict[str, list[str]] = {}
    policy_index: dict[str, str] = {}
    algorithm_cards: dict[str, dict[str, object]] = {}
    compiled_project_ids: list[str] = []
    reused_project_ids: list[str] = []
    previous_projects = (
        previous_payload.get("projects", {})
        if isinstance(previous_payload, Mapping)
        else {}
    )
    previous_cards = (
        previous_payload.get("algorithm_cards", {})
        if isinstance(previous_payload, Mapping)
        else {}
    )
    if not isinstance(previous_projects, Mapping):
        previous_projects = {}
    if not isinstance(previous_cards, Mapping):
        previous_cards = {}
    for pack in sorted_packs:
        project_id = str(pack.get("project_id") or "").strip()
        project_name = str(pack.get("project_name") or "").strip()
        if not project_id or not project_name:
            raise ValueError("项目算法包缺少project_id或project_name")
        if project_id in projects:
            raise ValueError(f"重复project_id：{project_id}")
        lifecycle_rule = next(
            (
                lifecycle_rules[candidate]
                for candidate in [
                    project_name,
                    *pack.get("aliases", []),
                ]
                if str(candidate or "").strip() in lifecycle_rules
            ),
            None,
        )
        version_id = policy_version_id(pack, lifecycle_rule)
        compile_input_hash = project_compile_input_hash(
            pack,
            lifecycle_rule,
            fact_contract,
        )
        previous_project = previous_projects.get(project_id)
        previous_card = previous_cards.get(project_id)
        can_reuse = (
            isinstance(previous_project, Mapping)
            and isinstance(previous_card, Mapping)
            and previous_project.get("compile_input_hash") == compile_input_hash
        )
        if can_reuse:
            compiled_project = dict(previous_project)
            algorithm_card = dict(previous_card)
            reused_project_ids.append(project_id)
        else:
            compiled_project = {
                **pack,
                "ir_node_id": f"project:{project_id}",
                "policy_version_id": version_id,
                "source_content_hash": content_digest(pack),
                "compile_input_hash": compile_input_hash,
                "shared_kernel_version": SHARED_KERNEL_VERSION,
                "lifecycle_rule": dict(lifecycle_rule or {}),
            }
            algorithm_card = build_algorithm_card(pack, lifecycle_rule)
            algorithm_card["compile_input_hash"] = compile_input_hash
            compiled_project_ids.append(project_id)
        projects[project_id] = compiled_project
        policy_index[project_id] = version_id
        algorithm_cards[project_id] = algorithm_card
        for alias in [
            project_id,
            project_name,
            *pack.get("aliases", []),
        ]:
            normalized = "".join(
                character.lower()
                for character in str(alias)
                if character.isalnum() or "\u4e00" <= character <= "\u9fff"
            )
            if normalized:
                alias_index.setdefault(normalized, []).append(project_id)
    as_of_year = int((baseline_registry or {}).get("as_of_year") or 2026)
    window_years = int((baseline_registry or {}).get("window_years") or 5)
    dependency_graph = build_policy_dependency_graph(
        sorted_packs,
        as_of_year=as_of_year,
        window_years=window_years,
    )
    rules_confirmed_count = sum(
        str(pack.get("coverage_status") or "") == "rules-confirmed"
        for pack in sorted_packs
    )
    policy_baseline_count = sum(
        str(pack.get("coverage_status") or "") == "policy-baseline-confirmed"
        for pack in sorted_packs
    )
    routing_only_count = sum(
        str(pack.get("coverage_status") or "") == "routing-only"
        for pack in sorted_packs
    )
    previous_project_ids = (
        set(str(project_id) for project_id in previous_projects)
        if isinstance(previous_projects, Mapping)
        else set()
    )
    removed_project_ids = sorted(previous_project_ids - set(projects))
    return {
        "schema_version": RULE_IR_SCHEMA_VERSION,
        "ir_type": "jiaotang-unified-project-rule-ir",
        "source_digest": source_digest,
        "shared_kernel": {
            "version": SHARED_KERNEL_VERSION,
            "components": list(SHARED_EXECUTION_KERNELS),
        },
        "fact_contract": fact_contract,
        "projects": projects,
        "indexes": {
            "alias_to_project_ids": {
                alias: sorted(set(project_ids))
                for alias, project_ids in sorted(alias_index.items())
            },
            "project_to_policy_version": policy_index,
        },
        "algorithm_cards": algorithm_cards,
        "policy_dependency_graph": dependency_graph,
        "incremental_compilation": {
            "strategy": "project-dependency-content-hash",
            "compiled_project_ids": compiled_project_ids,
            "reused_project_ids": reused_project_ids,
            "removed_project_ids": removed_project_ids,
            "compiled_count": len(compiled_project_ids),
            "reused_count": len(reused_project_ids),
            "removed_count": len(removed_project_ids),
        },
        "policy_execution_window": {
            "as_of_year": as_of_year,
            "window_years": window_years,
            "start_year": as_of_year - window_years + 1,
            "end_year": as_of_year,
            "exception_flags": [
                "still_effective",
                "cited_by_current_notice",
                "current_upstream_basis",
            ],
        },
        "metrics": {
            "project_count": len(projects),
            "rules_confirmed_count": rules_confirmed_count,
            "policy_baseline_count": policy_baseline_count,
            "policy_covered_count": rules_confirmed_count + policy_baseline_count,
            "routing_only_count": routing_only_count,
            "shared_kernel_count": len(SHARED_EXECUTION_KERNELS),
            "policy_dependency_nodes": len(dependency_graph["nodes"]),
            "policy_dependency_edges": len(dependency_graph["edges"]),
            "execution_policy_documents": len(
                dependency_graph["execution_document_ids"]
            ),
            "cold_archive_policy_documents": len(
                dependency_graph["cold_archive_document_ids"]
            ),
            "compiled_projects": len(compiled_project_ids),
            "reused_projects": len(reused_project_ids),
        },
    }


def write_compiled_rule_ir(
    output_path: Path,
    payload: Mapping[str, object],
) -> str:
    previous: Mapping[str, object] = {}
    if output_path.is_file():
        loaded = read_json(output_path)
        if isinstance(loaded, Mapping):
            previous = loaded
    if previous.get("source_digest") == payload.get("source_digest"):
        return "hash_reused"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return "compiled"


def compiled_projects(payload: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    projects = payload.get("projects", {})
    if not isinstance(projects, Mapping):
        return ()
    return tuple(
        dict(project)
        for _, project in sorted(projects.items())
        if isinstance(project, Mapping)
    )

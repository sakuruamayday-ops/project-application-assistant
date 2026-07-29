from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence


RULE_IR_SCHEMA_VERSION = 1
SHARED_KERNEL_VERSION = "1.0"
SHARED_EXECUTION_KERNELS = (
    "project-router",
    "policy-version-gate",
    "fact-contract-normalizer",
    "evidence-conflict-resolver",
    "layer-selector",
    "requirement-comparator",
    "lifecycle-state-machine",
    "coverage-hash-planner",
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
    return {
        str(rule.get("project_name") or ""): dict(rule)
        for rule in lifecycle_payload.get("projects", [])
        if isinstance(rule, Mapping) and str(rule.get("project_name") or "")
    }


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
            else "仅识别项目并路由政策证据，不直接形成符合或不符合结论。"
        ),
        "policy_version_id": policy_version_id(project, lifecycle_rule),
        "inputs": {
            "project_context": "项目名称、年度、申请类型与属地",
            "enterprise_facts": "统一事实契约中的字段、值、证据状态与来源",
            "as_of": "判断或回放的时间点",
        },
        "outputs": {
            "conclusion": "eligible、conditional、ineligible或undetermined",
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
            "pack_validation": True,
            "gold_case_count": len(project.get("gold_cases", [])),
            "formal_decision_enabled": coverage_status == "rules-confirmed",
        },
        "limitations": [
            "routing-only项目尚未具备正式门槛规则",
            "名单未披露或主体匹配冲突时只能输出待核验",
            "算法不替代主管部门最终审核结论",
        ],
    }


def compile_rule_ir(
    packs: Sequence[Mapping[str, object]],
    lifecycle_payload: Mapping[str, object],
    fact_contract: Mapping[str, object],
) -> dict[str, object]:
    lifecycle_rules = lifecycle_rule_index(lifecycle_payload)
    sorted_packs = sorted(
        (dict(pack) for pack in packs),
        key=lambda item: str(item.get("project_id") or ""),
    )
    source_basis = {
        "packs": sorted_packs,
        "lifecycle": lifecycle_payload,
        "fact_contract": fact_contract,
        "compiler_schema": RULE_IR_SCHEMA_VERSION,
        "kernel_version": SHARED_KERNEL_VERSION,
    }
    source_digest = content_digest(source_basis)
    projects: dict[str, dict[str, object]] = {}
    alias_index: dict[str, list[str]] = {}
    policy_index: dict[str, str] = {}
    algorithm_cards: dict[str, dict[str, object]] = {}
    for pack in sorted_packs:
        project_id = str(pack.get("project_id") or "").strip()
        project_name = str(pack.get("project_name") or "").strip()
        if not project_id or not project_name:
            raise ValueError("项目算法包缺少project_id或project_name")
        if project_id in projects:
            raise ValueError(f"重复project_id：{project_id}")
        lifecycle_rule = lifecycle_rules.get(project_name)
        version_id = policy_version_id(pack, lifecycle_rule)
        compiled_project = {
            **pack,
            "ir_node_id": f"project:{project_id}",
            "policy_version_id": version_id,
            "source_content_hash": content_digest(pack),
            "shared_kernel_version": SHARED_KERNEL_VERSION,
            "lifecycle_rule": dict(lifecycle_rule or {}),
        }
        projects[project_id] = compiled_project
        policy_index[project_id] = version_id
        algorithm_cards[project_id] = build_algorithm_card(pack, lifecycle_rule)
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
        "metrics": {
            "project_count": len(projects),
            "rules_confirmed_count": sum(
                str(pack.get("coverage_status") or "") == "rules-confirmed"
                for pack in sorted_packs
            ),
            "routing_only_count": sum(
                str(pack.get("coverage_status") or "") != "rules-confirmed"
                for pack in sorted_packs
            ),
            "shared_kernel_count": len(SHARED_EXECUTION_KERNELS),
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

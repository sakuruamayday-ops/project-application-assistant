#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PORTAL_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = PORTAL_DIR.parents[1]
if str(PORTAL_DIR) not in sys.path:
    sys.path.insert(0, str(PORTAL_DIR))

from app.rule_structure import audit_composite_rule_structure


DEFAULT_RULES = (
    ROOT_DIR
    / "skills"
    / "project-matching"
    / "references"
    / "high-frequency-project-retrieval-rules.json"
)
DEFAULT_PACKS = PORTAL_DIR / "references" / "project-algorithm-packs"
DEFAULT_RULE_SOURCES = (
    PORTAL_DIR / "references" / "project-algorithm-rule-sources"
)
DEFAULT_FACT_CONTRACT = PORTAL_DIR / "references" / "lifecycle-fact-contract.json"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def unique(values: list[object]) -> list[str]:
    return list(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )


def existing_packs(pack_dir: Path) -> tuple[dict[str, dict[str, object]], dict[str, Path]]:
    by_project: dict[str, dict[str, object]] = {}
    paths: dict[str, Path] = {}
    for path in sorted(pack_dir.glob("*.json")):
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        project_name = str(payload.get("project_name") or "")
        if project_name:
            by_project[project_name] = payload
            paths[project_name] = path
    return by_project, paths


def target_descriptors(rules: list[dict[str, object]]) -> list[dict[str, object]]:
    descriptors: dict[str, dict[str, object]] = {}
    for rule in rules:
        targets = unique(rule.get("targets", []))
        for target_index, target in enumerate(targets, start=1):
            descriptor = descriptors.setdefault(
                target,
                {
                    "project_name": target,
                    "rule_ids": [],
                    "aliases": [],
                    "preferred_ids": [],
                },
            )
            descriptor["rule_ids"].append(str(rule.get("id") or ""))
            descriptor["aliases"].extend(rule.get("aliases", []))
            if len(targets) == 1:
                descriptor["preferred_ids"].append(str(rule.get("id") or ""))
            elif not descriptor["preferred_ids"]:
                descriptor["preferred_ids"].append(
                    f"{rule.get('id')}-{target_index}"
                )
    results: list[dict[str, object]] = []
    used_ids: set[str] = set()
    for target, descriptor in sorted(descriptors.items()):
        candidates = unique(descriptor["preferred_ids"] or descriptor["rule_ids"])
        project_id = candidates[0] if candidates else (
            "project-" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:12]
        )
        if project_id in used_ids:
            project_id += "-" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:6]
        used_ids.add(project_id)
        results.append(
            {
                "project_id": project_id,
                "project_name": target,
                "aliases": unique(descriptor["aliases"]),
                "source_retrieval_rule_ids": unique(descriptor["rule_ids"]),
            }
        )
    return results


def scaffold_pack(descriptor: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "project_id": descriptor["project_id"],
        "project_name": descriptor["project_name"],
        "version": "1.0",
        "coverage_status": "routing-only",
        "aliases": descriptor["aliases"],
        "source_retrieval_rule_ids": descriptor["source_retrieval_rule_ids"],
        "fact_fields": [],
        "rule_cards": [],
        "gold_cases": [
            {
                "case_id": "rules-pending",
                "facts": [],
                "confirm_rule_ids": [],
                "expected_conclusion": "undetermined",
            }
        ],
    }


def sync_packs(
    *,
    rules_path: Path,
    pack_dir: Path,
    write: bool,
) -> dict[str, object]:
    payload = load_json(rules_path)
    rules = payload.get("rules", [])
    descriptors = target_descriptors(rules)
    existing, paths = existing_packs(pack_dir)
    created: list[str] = []
    updated: list[str] = []
    for descriptor in descriptors:
        project_name = str(descriptor["project_name"])
        if project_name in existing:
            pack = existing[project_name]
            changed = False
            merged_aliases = unique(
                [*pack.get("aliases", []), *descriptor.get("aliases", [])]
            )
            if merged_aliases != pack.get("aliases", []):
                pack["aliases"] = merged_aliases
                changed = True
            source_rule_ids = unique(
                [
                    *pack.get("source_retrieval_rule_ids", []),
                    *descriptor.get("source_retrieval_rule_ids", []),
                ]
            )
            if source_rule_ids != pack.get("source_retrieval_rule_ids", []):
                pack["source_retrieval_rule_ids"] = source_rule_ids
                changed = True
            if changed:
                updated.append(project_name)
                if write:
                    write_json(paths[project_name], pack)
            continue
        pack = scaffold_pack(descriptor)
        created.append(project_name)
        if write:
            write_json(pack_dir / f"{descriptor['project_id']}.json", pack)
    return {
        "status": "pass",
        "write": write,
        "high_frequency_projects": len(descriptors),
        "existing_before": len(existing),
        "created": created,
        "updated": updated,
        "covered_after": len(existing) + len(created),
    }


def rule_values(rule: dict[str, object]) -> tuple[object, object]:
    operator = str(rule.get("operator") or "")
    expected = rule.get("expected")
    if operator == "exists":
        return "已提供", None
    if operator == "truthy":
        return True, False
    if operator == "falsy":
        return False, True
    if operator == "equals":
        return expected, "__不匹配__"
    if operator == "not-equals":
        return "__其他值__", expected
    if operator in {"in", "not-in"} and isinstance(expected, list) and expected:
        inside, outside = expected[0], "__不在范围__"
        return (inside, outside) if operator == "in" else (outside, inside)
    if operator in {"gte", "gt", "lte", "lt"} and isinstance(expected, (int, float)):
        delta = 1 if expected == 0 else max(abs(expected) * 0.01, 0.01)
        if operator == "gte":
            return expected, expected - delta
        if operator == "gt":
            return expected + delta, expected
        if operator == "lte":
            return expected, expected + delta
        return expected - delta, expected
    if operator == "contains":
        return expected, "__不包含__"
    return expected, None


def generated_gold_cases(rules: list[dict[str, object]]) -> list[dict[str, object]]:
    if not rules:
        return scaffold_pack(
            {"project_id": "placeholder", "project_name": "placeholder", "aliases": []}
        )["gold_cases"]
    def assignments(
        requirement: dict[str, object],
        *,
        passing: bool,
        known: dict[str, object] | None = None,
    ) -> list[tuple[str, object]]:
        known = dict(known or {})

        def compatible(values: list[tuple[str, object]]) -> bool:
            return all(
                not field or field not in known or known[field] == value
                for field, value in values
            )

        def extend_known(values: list[tuple[str, object]]) -> None:
            for field, value in values:
                if field:
                    known.setdefault(field, value)

        children = requirement.get("children")
        if isinstance(children, list) and children:
            valid_children = [
                child for child in children if isinstance(child, dict)
            ]
            logic = str(requirement.get("logic") or "")
            if passing and logic == "any":
                for child in valid_children:
                    candidate = assignments(child, passing=True, known=known)
                    if compatible(candidate):
                        return candidate
                return []
            if not passing and logic == "all":
                selected: list[tuple[str, object]] = []
                for index, child in enumerate(valid_children):
                    candidate = assignments(
                        child,
                        passing=index != 0,
                        known=known,
                    )
                    if compatible(candidate):
                        selected.extend(candidate)
                        extend_known(candidate)
                return selected
            selected = []
            for child in valid_children:
                candidate = assignments(child, passing=passing, known=known)
                if not compatible(candidate):
                    return [*selected, *candidate]
                selected.extend(candidate)
                extend_known(candidate)
            return selected
        positive, negative = rule_values(requirement)
        exclusion = str(requirement.get("type")) == "exclusion"
        pass_value = negative if exclusion else positive
        fail_value = positive if exclusion else negative
        return [(str(requirement.get("field") or ""), pass_value if passing else fail_value)]

    def fact_rows(
        values: list[tuple[str, object]],
        *,
        pending_field: str = "",
    ) -> list[dict[str, object]]:
        by_field: dict[str, object] = {}
        for field, value in values:
            if field:
                by_field.setdefault(field, value)
        return [
            {
                "field": field,
                "value": value,
                "evidence_state": (
                    "claimed" if field == pending_field else "verified"
                ),
                "source": "金标准事实",
            }
            for field, value in by_field.items()
        ]

    def scenario_values(
        scenario_rules: list[tuple[dict[str, object], bool]],
    ) -> list[tuple[str, object]]:
        values: list[tuple[str, object]] = []
        known: dict[str, object] = {}
        for rule, passing in scenario_rules:
            candidate = assignments(rule, passing=passing, known=known)
            values.extend(candidate)
            for field, value in candidate:
                if field:
                    known.setdefault(field, value)
        return values

    eligible_values = scenario_values([(rule, True) for rule in rules])
    failed_values = scenario_values(
        [(rules[0], False), *[(rule, True) for rule in rules[1:]]]
    )
    first_positive = assignments(rules[0], passing=True)
    pending_field = first_positive[0][0] if first_positive else ""
    eligible_facts = fact_rows(eligible_values)
    failed_facts = fact_rows(failed_values)
    pending_facts = fact_rows(eligible_values, pending_field=pending_field)
    rule_ids = [str(rule["rule_id"]) for rule in rules]
    return [
        {
            "case_id": "eligible-verified",
            "facts": eligible_facts,
            "confirm_rule_ids": rule_ids,
            "expected_conclusion": "eligible",
        },
        {
            "case_id": "conditional-pending",
            "facts": pending_facts,
            "confirm_rule_ids": rule_ids,
            "expected_conclusion": "conditional",
        },
        {
            "case_id": "ineligible-failed",
            "facts": failed_facts,
            "confirm_rule_ids": rule_ids,
            "expected_conclusion": "ineligible",
        },
    ]


def requirement_leaf_fields(
    requirements: list[dict[str, object]],
) -> list[str]:
    fields: list[str] = []
    for requirement in requirements:
        children = requirement.get("children")
        if isinstance(children, list):
            fields.extend(
                requirement_leaf_fields(
                    [child for child in children if isinstance(child, dict)]
                )
            )
            continue
        field = str(requirement.get("field") or "").strip()
        if field:
            fields.append(field)
    return unique(fields)


def confirmed_rule_cards(
    *,
    source: dict[str, object],
    rules: object,
    layer: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    if not isinstance(rules, list):
        raise ValueError("规则层rules必须为列表")
    audit_source = {**source, **(layer or {})}
    policy_status = str(audit_source.get("policy_status") or "")
    layer_type = str((layer or {}).get("layer_type") or "")
    allowed_statuses = (
        {"draft", "active_candidate"}
        if layer_type == "prospective"
        else {"current"}
    )
    if layer is not None and (
        layer.get("year") or layer.get("years")
    ):
        allowed_statuses.add("historical_reference")
    if policy_status not in allowed_statuses:
        raise ValueError("政策状态与规则层类型不匹配")
    for field in ("approved_by", "approved_at", "source_url"):
        if not str(audit_source.get(field) or "").strip():
            raise ValueError(f"确认规则层缺少{field}")
    cards: list[dict[str, object]] = []
    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            raise ValueError("规则层中的每条规则必须为对象")
        rule = dict(raw_rule)
        rule.update(
            {
                "policy_status": policy_status,
                "review_status": "confirmed",
                "approved_by": audit_source["approved_by"],
                "approved_at": audit_source["approved_at"],
                "source_url": audit_source["source_url"],
            }
        )
        for provenance_field in (
            "source_archive_path",
            "source_archive_sha256",
        ):
            if str(audit_source.get(provenance_field) or "").strip():
                rule[provenance_field] = audit_source[provenance_field]
        cards.append(rule)
    return cards


def build_rule_layers(source: dict[str, object]) -> list[dict[str, object]]:
    stable_rules = source.get("rules", [])
    if not isinstance(stable_rules, list) or not stable_rules:
        raise ValueError("确认规则文件rules不能为空")
    raw_stable_applicability = source.get("stable_applicability", {})
    if not isinstance(raw_stable_applicability, dict):
        raise ValueError("stable_applicability必须为对象")
    stable_applicability = {
        "years": unique(raw_stable_applicability.get("years", [])),
        "regions": unique(raw_stable_applicability.get("regions", [])),
        "application_types": unique(
            raw_stable_applicability.get("application_types", [])
        ),
    }
    layers: list[dict[str, object]] = [
        {
            "layer_id": "stable-management",
            "layer_type": "stable",
            "policy_time_type": "stable-management",
            "label": "稳定管理办法",
            "applicability": {
                key: values
                for key, values in stable_applicability.items()
                if values
            },
            **{
                key: source[key]
                for key in (
                    "effective_from",
                    "effective_to",
                    "source_url",
                    "source_archive_path",
                    "source_archive_sha256",
                    "source_scope_level",
                    "source_scope_region",
                )
                if str(source.get(key) or "").strip()
            },
            "rules": confirmed_rule_cards(source=source, rules=stable_rules),
        }
    ]
    for layer_type, source_key, label in (
        ("annual", "annual_overlays", "年度通知"),
        ("jurisdiction", "jurisdiction_overlays", "属地覆盖"),
        ("prospective", "prospective_overlays", "征求意见前瞻规则"),
    ):
        raw_layers = source.get(source_key, [])
        if not isinstance(raw_layers, list):
            raise ValueError(f"{source_key}必须为列表")
        for index, raw_layer in enumerate(raw_layers, start=1):
            if not isinstance(raw_layer, dict):
                raise ValueError(f"{source_key}[{index}]必须为对象")
            layer_id = str(raw_layer.get("overlay_id") or "").strip()
            if not layer_id:
                raise ValueError(f"{source_key}[{index}]缺少overlay_id")
            applicability = {
                "years": unique(
                    raw_layer.get("years", [])
                    or ([raw_layer["year"]] if raw_layer.get("year") else [])
                ),
                "regions": unique(raw_layer.get("regions", [])),
                "application_types": unique(
                    raw_layer.get("application_types", [])
                ),
            }
            if layer_type == "annual" and not applicability["years"]:
                raise ValueError(f"{source_key}[{index}]缺少year或years")
            if layer_type == "jurisdiction" and not applicability["regions"]:
                raise ValueError(f"{source_key}[{index}]缺少regions")
            raw_layer = {**raw_layer, "layer_type": layer_type}
            layers.append(
                {
                    "layer_id": layer_id,
                    "layer_type": layer_type,
                    "policy_time_type": (
                        "annual-notice"
                        if layer_type == "annual"
                        else "jurisdiction-detail"
                        if layer_type == "jurisdiction"
                        else "consultation-draft"
                    ),
                    "label": str(raw_layer.get("label") or label),
                    "applicability": {
                        key: values
                        for key, values in applicability.items()
                        if values
                    },
                    **{
                        key: raw_layer.get(key)
                        for key in (
                            "effective_from",
                            "effective_to",
                            "source_url",
                            "source_archive_path",
                            "source_archive_sha256",
                            "source_role",
                            "retrieval_channel",
                            "published_at",
                            "issued_at",
                            "application_open_date",
                            "authority_recommendation_deadline",
                            "enterprise_deadline",
                            "enterprise_deadline_note",
                            "provincial_review_schedule",
                            "replaces_rule_ids",
                            "replacement_signal",
                            "replaces_policy_title",
                            "transition_notice",
                            "source_scope_level",
                            "source_scope_region",
                        )
                        if key == "enterprise_deadline"
                        or (
                            raw_layer.get(key) is not None
                            and (
                            not isinstance(raw_layer.get(key), str)
                            or str(raw_layer.get(key) or "").strip()
                            )
                        )
                    },
                    "rules": confirmed_rule_cards(
                        source=source,
                        layer=raw_layer,
                        rules=raw_layer.get("rules", []),
                    ),
                }
            )
    return layers


def generate_from_confirmed_rules(
    *,
    input_path: Path,
    output_path: Path,
    fact_contract_path: Path,
) -> dict[str, object]:
    source = load_json(input_path)
    if not isinstance(source, dict):
        raise ValueError("确认规则文件顶层必须为对象")
    if str(source.get("policy_status") or "") != "current":
        raise ValueError("仅允许从current政策生成正式算法包")
    for field in ("approved_by", "approved_at", "source_url"):
        if not str(source.get(field) or "").strip():
            raise ValueError(f"确认规则文件缺少{field}")
    structure_audit = audit_composite_rule_structure(source)
    if not structure_audit["formal_decision_allowed"]:
        unresolved = "、".join(
            str(item.get("field") or "")
            for item in structure_audit["unresolved_composite_leaves"]
        )
        raise ValueError(
            "确认规则仍含未分类综合布尔叶子，禁止生成正式算法包："
            + unresolved
        )
    rule_layers = build_rule_layers(source)
    rules = [
        rule
        for layer in rule_layers
        for rule in layer["rules"]
    ]
    base_fields = {
        str(field.get("field")): field
        for field in load_json(fact_contract_path).get("fields", [])
    }
    explicit_fields = {
        str(field.get("field")): field for field in source.get("fact_fields", [])
    }
    rule_cards: list[dict[str, object]] = list(rule_layers[0]["rules"])
    fact_fields: list[dict[str, object]] = []
    for field in requirement_leaf_fields(rules):
        field_spec = explicit_fields.get(field) or base_fields.get(field)
        if not field_spec:
            raise ValueError(f"规则字段未进入事实契约：{field}")
        fact_fields.append(dict(field_spec))
    existing = {}
    if output_path.exists():
        loaded_existing = load_json(output_path)
        if isinstance(loaded_existing, dict):
            existing = loaded_existing
    pack = {
        "schema_version": 1,
        "project_id": source["project_id"],
        "project_name": source["project_name"],
        "version": str(source.get("version") or "1.0"),
        "coverage_status": "rules-confirmed",
        "aliases": unique(
            [*existing.get("aliases", []), *source.get("aliases", [])]
        ),
        "source_retrieval_rule_ids": unique(
            [
                *existing.get("source_retrieval_rule_ids", []),
                *source.get("source_retrieval_rule_ids", []),
            ]
        ),
        **{
            key: source[key]
            for key in (
                "canonical_project_id",
                "variant_of",
                "ui_hidden",
                "policy_transition",
                "jurisdiction_source_contract",
            )
            if key in source
        },
        "fact_fields": list(
            {str(field["field"]): field for field in fact_fields}.values()
        ),
        "rule_cards": rule_cards,
        "rule_layers": rule_layers,
        "gold_cases": (
            source["gold_cases"]
            if isinstance(source.get("gold_cases"), list)
            and source["gold_cases"]
            else generated_gold_cases(rule_cards)
        ),
    }
    write_json(output_path, pack)
    return {
        "status": "pass",
        "output": str(output_path),
        "rules": len(rule_cards),
        "layers": len(rule_layers),
        "gold_cases": len(pack["gold_cases"]),
    }


def generate_all_confirmed_rules(
    *,
    sources_dir: Path,
    packs_dir: Path,
    fact_contract_path: Path,
) -> dict[str, object]:
    generated: list[dict[str, object]] = []
    for source_path in sorted(sources_dir.glob("*.json")):
        source = load_json(source_path)
        if not isinstance(source, dict):
            raise ValueError(f"{source_path.name}顶层必须为对象")
        project_id = str(source.get("project_id") or "").strip()
        if not project_id:
            raise ValueError(f"{source_path.name}缺少project_id")
        generated.append(
            generate_from_confirmed_rules(
                input_path=source_path,
                output_path=packs_dir / f"{project_id}.json",
                fact_contract_path=fact_contract_path,
            )
        )
    if not generated:
        raise ValueError("没有发现已确认规则源文件")
    packs = [
        payload
        for payload in (
            load_json(path)
            for path in sorted(packs_dir.glob("*.json"))
        )
        if isinstance(payload, dict)
    ]
    routing_only = [
        str(pack.get("project_name") or "")
        for pack in packs
        if str(pack.get("coverage_status") or "") != "rules-confirmed"
    ]
    return {
        "status": "pass",
        "generated_packs": len(generated),
        "outputs": [item["output"] for item in generated],
        "coverage": {
            "total": len(packs),
            "rules_confirmed": len(packs) - len(routing_only),
            "routing_only": len(routing_only),
            "routing_only_projects": routing_only,
        },
    }


def project_priority_queue(
    *,
    database_path: Path,
    packs_dir: Path,
    days: int,
) -> dict[str, object]:
    if not database_path.is_file():
        raise ValueError(f"团队数据库不存在：{database_path}")
    since = (
        datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    ).isoformat(timespec="seconds")
    packs = [
        payload
        for payload in (
            load_json(path)
            for path in sorted(packs_dir.glob("*.json"))
        )
        if isinstance(payload, dict)
    ]
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(api_usage)")
        }
        usage_by_rule: dict[str, dict[str, object]] = {}
        if "project_rule_id" in columns:
            rows = connection.execute(
                """
                SELECT project_rule_id,COUNT(*) AS total,
                       COUNT(DISTINCT user_id) AS users
                FROM api_usage
                WHERE called_at>=?
                  AND project_rule_id<>''
                  AND counts_toward_usage=1
                GROUP BY project_rule_id
                """,
                (since,),
            ).fetchall()
            usage_by_rule = {
                str(row["project_rule_id"]): {
                    "total": int(row["total"] or 0),
                    "users": int(row["users"] or 0),
                }
                for row in rows
            }
    queue: list[dict[str, object]] = []
    for pack in packs:
        if str(pack.get("coverage_status") or "") == "rules-confirmed":
            continue
        source_rule_ids = [
            str(rule_id)
            for rule_id in pack.get("source_retrieval_rule_ids", [])
            if str(rule_id)
        ]
        total = sum(
            int(usage_by_rule.get(rule_id, {}).get("total", 0))
            for rule_id in source_rule_ids
        )
        users = max(
            (
                int(usage_by_rule.get(rule_id, {}).get("users", 0))
                for rule_id in source_rule_ids
            ),
            default=0,
        )
        queue.append(
            {
                "project_id": str(pack.get("project_id") or ""),
                "project_name": str(pack.get("project_name") or ""),
                "usage": total,
                "users": users,
                "source_retrieval_rule_ids": source_rule_ids,
            }
        )
    queue.sort(key=lambda item: (-int(item["usage"]), str(item["project_name"])))
    observed_rank = 0
    for item in queue:
        if int(item["usage"]) <= 0:
            item["rank"] = None
            item["priority"] = "waiting-for-samples"
            continue
        observed_rank += 1
        item["rank"] = observed_rank
        item["priority"] = "high" if observed_rank <= 5 else "normal"
    return {
        "status": "pass",
        "window_days": max(1, int(days)),
        "routing_only": len(queue),
        "high_priority": sum(item["priority"] == "high" for item in queue),
        "queue": queue,
    }


def template_payload() -> dict[str, object]:
    return {
        "project_id": "replace-with-stable-id",
        "project_name": "替换为正式项目名称",
        "version": "1.0",
        "aliases": ["项目简称"],
        "policy_status": "current",
        "approved_by": "规则确认人",
        "approved_at": "YYYY-MM-DD HH:MM:SS",
        "source_url": "https://官方政策原文地址",
        "stable_applicability": {
            "application_types": []
        },
        "fact_fields": [],
        "rules": [
            {
                "rule_id": "stable-rule-id",
                "type": "hard-threshold",
                "field": "统一事实字段",
                "operator": "gte",
                "expected": 0,
                "unit": "万元",
                "source": "正式政策名称及文号",
                "source_quote": "逐字保存对应政策原文条款"
            }
        ],
        "annual_overlays": [
            {
                "overlay_id": "annual-YYYY",
                "label": "YYYY年度申报通知",
                "year": "YYYY",
                "policy_status": "current",
                "approved_by": "规则确认人",
                "approved_at": "YYYY-MM-DD HH:MM:SS",
                "source_url": "https://年度通知官方地址",
                "application_types": [],
                "rules": []
            }
        ],
        "jurisdiction_overlays": [
            {
                "overlay_id": "region-example",
                "label": "属地实施细则",
                "regions": ["浙江省", "杭州市"],
                "policy_status": "current",
                "approved_by": "规则确认人",
                "approved_at": "YYYY-MM-DD HH:MM:SS",
                "source_url": "https://属地政策官方地址",
                "years": [],
                "application_types": [],
                "rules": []
            }
        ],
        "prospective_overlays": [
            {
                "overlay_id": "consultation-draft-example",
                "label": "已核验征求意见稿",
                "policy_status": "draft",
                "approved_by": "规则核验人",
                "approved_at": "YYYY-MM-DD HH:MM:SS",
                "source_url": "https://征求意见公告地址",
                "application_types": ["recognition"],
                "rules": []
            }
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    sync_parser.add_argument("--packs-dir", type=Path, default=DEFAULT_PACKS)
    sync_parser.add_argument("--write", action="store_true")

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--input", type=Path, required=True)
    generate_parser.add_argument("--output", type=Path, required=True)
    generate_parser.add_argument(
        "--fact-contract",
        type=Path,
        default=DEFAULT_FACT_CONTRACT,
    )

    generate_all_parser = subparsers.add_parser("generate-all")
    generate_all_parser.add_argument(
        "--sources-dir",
        type=Path,
        default=DEFAULT_RULE_SOURCES,
    )
    generate_all_parser.add_argument(
        "--packs-dir",
        type=Path,
        default=DEFAULT_PACKS,
    )
    generate_all_parser.add_argument(
        "--fact-contract",
        type=Path,
        default=DEFAULT_FACT_CONTRACT,
    )

    priority_parser = subparsers.add_parser("priority-queue")
    priority_parser.add_argument("--database", type=Path, required=True)
    priority_parser.add_argument("--packs-dir", type=Path, default=DEFAULT_PACKS)
    priority_parser.add_argument("--days", type=int, default=7)

    template_parser = subparsers.add_parser("template")
    template_parser.add_argument("--output", type=Path, required=True)

    arguments = parser.parse_args()
    try:
        if arguments.command == "sync":
            result = sync_packs(
                rules_path=arguments.rules,
                pack_dir=arguments.packs_dir,
                write=arguments.write,
            )
        elif arguments.command == "generate":
            result = generate_from_confirmed_rules(
                input_path=arguments.input,
                output_path=arguments.output,
                fact_contract_path=arguments.fact_contract,
            )
        elif arguments.command == "generate-all":
            result = generate_all_confirmed_rules(
                sources_dir=arguments.sources_dir,
                packs_dir=arguments.packs_dir,
                fact_contract_path=arguments.fact_contract,
            )
        elif arguments.command == "priority-queue":
            result = project_priority_queue(
                database_path=arguments.database,
                packs_dir=arguments.packs_dir,
                days=arguments.days,
            )
        else:
            write_json(arguments.output, template_payload())
            result = {"status": "pass", "output": str(arguments.output)}
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "fail", "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

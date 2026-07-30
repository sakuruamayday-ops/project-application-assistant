from __future__ import annotations

import hashlib
import json
import math
from typing import Mapping, Sequence


SCORE_METHODS = frozenset(
    {"band", "count-step", "alternative-count-step", "reviewed"}
)
EXECUTION_MODES = frozenset(
    {
        "project-rule-layer",
        "leaf-threshold-and-score",
        "leaf-threshold-no-score",
    }
)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _city_variant(
    registry: Mapping[str, object],
    city: str,
) -> dict[str, object] | None:
    return next(
        (
            dict(item)
            for item in registry.get("city_variants", [])
            if isinstance(item, Mapping)
            and str(item.get("city") or "") == city
        ),
        None,
    )


def _track(
    registry: Mapping[str, object],
    city: str,
    track_id: str,
) -> dict[str, object] | None:
    variant = _city_variant(registry, city)
    if variant is None:
        return None
    track = next(
        (
            dict(item)
            for item in variant.get("tracks", [])
            if isinstance(item, Mapping)
            and str(item.get("track_id") or "") == track_id
        ),
        None,
    )
    if track is not None:
        track["_source_documents"] = [
            dict(item)
            for item in variant.get("source_documents", [])
            if isinstance(item, Mapping)
        ]
    return track


def threshold_track_catalog(
    registry: Mapping[str, object],
    city: str,
) -> list[dict[str, object]]:
    variant = _city_variant(registry, city)
    if variant is None:
        return []
    return [
        {
            "track_id": item.get("track_id"),
            "track_name": item.get("track_name"),
            "execution_mode": item.get("execution_mode"),
            "policy_status": item.get("policy_status"),
            "formal_conclusion_allowed": item.get(
                "formal_conclusion_allowed",
                str(item.get("policy_status") or "") == "current",
            ),
            "score_threshold": item.get("score_threshold"),
            "score_model": item.get("score_model", "leaf-score"),
            "score_reason": item.get("score_reason"),
        }
        for item in variant.get("tracks", [])
        if isinstance(item, Mapping)
    ]


def validate_threshold_registry(
    registry: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []
    cities = [
        str(item.get("city") or "")
        for item in registry.get("city_variants", [])
        if isinstance(item, Mapping)
    ]
    if set(cities) != {"杭州市", "宁波市", "绍兴市", "金华市"}:
        errors.append("研发平台阈值包必须覆盖杭州、宁波、绍兴、金华四市")
    if len(cities) != len(set(cities)):
        errors.append("研发平台阈值包城市不得重复")
    seen_track_ids: set[str] = set()
    seen_leaf_ids: set[str] = set()
    for variant in registry.get("city_variants", []):
        if not isinstance(variant, Mapping):
            errors.append("city_variants中的城市记录必须为对象")
            continue
        city = str(variant.get("city") or "")
        tracks = [
            item
            for item in variant.get("tracks", [])
            if isinstance(item, Mapping)
        ]
        if not tracks:
            errors.append(f"{city}缺少阈值轨道")
        for track in tracks:
            track_id = str(track.get("track_id") or "").strip()
            if not track_id:
                errors.append(f"{city}存在缺少track_id的阈值轨道")
            elif track_id in seen_track_ids:
                errors.append(f"阈值轨道重复：{track_id}")
            seen_track_ids.add(track_id)
            mode = str(track.get("execution_mode") or "")
            if mode not in EXECUTION_MODES:
                errors.append(f"{track_id}的execution_mode无效")
            if mode == "project-rule-layer":
                if not str(track.get("project_id") or ""):
                    errors.append(f"{track_id}缺少project_id")
                if not str(track.get("rule_layer_id") or ""):
                    errors.append(f"{track_id}缺少rule_layer_id")
                continue
            hard_rules = track.get("hard_rules")
            if not isinstance(hard_rules, list) or not hard_rules:
                errors.append(f"{track_id}缺少hard_rules")
            if mode == "leaf-threshold-no-score":
                if track.get("score_groups"):
                    errors.append(f"{track_id}无评分制却配置了score_groups")
                continue
            if _number(track.get("score_threshold")) is None:
                errors.append(f"{track_id}缺少score_threshold")
            groups = track.get("score_groups")
            if not isinstance(groups, list) or not groups:
                errors.append(f"{track_id}缺少score_groups")
                continue
            for group in groups:
                if not isinstance(group, Mapping):
                    errors.append(f"{track_id}存在非对象评分组")
                    continue
                if _number(group.get("cap")) is None:
                    errors.append(f"{track_id}评分组缺少cap")
                for leaf in group.get("leaves", []):
                    if not isinstance(leaf, Mapping):
                        errors.append(f"{track_id}存在非对象评分叶节点")
                        continue
                    leaf_id = str(leaf.get("leaf_id") or "").strip()
                    if not leaf_id:
                        errors.append(f"{track_id}存在缺少leaf_id的评分叶节点")
                    elif leaf_id in seen_leaf_ids:
                        errors.append(f"评分叶节点重复：{leaf_id}")
                    seen_leaf_ids.add(leaf_id)
                    method = str(leaf.get("method") or "")
                    if method not in SCORE_METHODS:
                        errors.append(f"{leaf_id}的method无效")
                    if method in {"band", "count-step", "reviewed"} and not str(
                        leaf.get("field") or ""
                    ):
                        errors.append(f"{leaf_id}缺少field")
                    if method == "band" and not leaf.get("bands"):
                        errors.append(f"{leaf_id}缺少bands")
                    if method == "alternative-count-step" and (
                        not leaf.get("fields") or not leaf.get("routes")
                    ):
                        errors.append(f"{leaf_id}缺少fields或routes")
    return list(dict.fromkeys(errors))


def _condition_matches(
    condition: Mapping[str, object],
    facts: Mapping[str, object],
) -> bool:
    field = str(condition.get("when_field") or "")
    if not field or field not in facts:
        return False
    actual = facts.get(field)
    if "when_values" in condition:
        return actual in condition.get("when_values", [])
    return actual == condition.get("when_value")


def _score_band(
    leaf: Mapping[str, object],
    facts: Mapping[str, object],
) -> tuple[float | None, list[str], str]:
    field = str(leaf.get("field") or "")
    actual = _number(facts.get(field))
    if actual is None:
        return None, [field], "缺少可计算的数值"
    bands = [
        dict(item)
        for item in leaf.get("bands", [])
        if isinstance(item, Mapping)
    ]
    multiplier_spec = leaf.get("threshold_multiplier")
    if isinstance(multiplier_spec, Mapping) and _condition_matches(
        multiplier_spec,
        facts,
    ):
        explicit = multiplier_spec.get("explicit_profile")
        if isinstance(explicit, list) and explicit:
            bands = [
                dict(item) for item in explicit if isinstance(item, Mapping)
            ]
        else:
            multiplier = _number(multiplier_spec.get("multiplier"))
            if multiplier is not None:
                bands = [
                    {
                        **band,
                        "min": (_number(band.get("min")) or 0) * multiplier,
                    }
                    for band in bands
                ]
    score = 0.0
    for band in sorted(
        bands,
        key=lambda item: _number(item.get("min")) or float("-inf"),
    ):
        minimum = _number(band.get("min"))
        band_score = _number(band.get("score"))
        if minimum is None or band_score is None:
            continue
        if actual >= minimum:
            score = max(score, band_score)
    maximum = _number(leaf.get("max_score"))
    if maximum is not None:
        score = min(score, maximum)
    return score, [], f"按分档计算，事实值为{actual:g}"


def _score_count_step(
    leaf: Mapping[str, object],
    facts: Mapping[str, object],
) -> tuple[float | None, list[str], str]:
    field = str(leaf.get("field") or "")
    actual = _number(facts.get(field))
    if actual is None:
        return None, [field], "缺少可计算的数量"
    base_min = _number(leaf.get("base_min")) or 0
    if actual < base_min:
        return 0.0, [], f"数量{actual:g}低于基础档{base_min:g}"
    base_score = _number(leaf.get("base_score")) or 0
    every = _number(leaf.get("increment_every")) or 1
    increment = _number(leaf.get("increment_score")) or 0
    score = base_score + math.floor((actual - base_min) / every) * increment
    maximum = _number(leaf.get("max_score"))
    if maximum is not None:
        score = min(score, maximum)
    return score, [], f"按基础分和递增档计算，数量为{actual:g}"


def _score_alternative_count_step(
    leaf: Mapping[str, object],
    facts: Mapping[str, object],
) -> tuple[float | None, list[str], str]:
    aliases = {
        str(alias): str(field)
        for alias, field in (
            leaf.get("fields", {}).items()
            if isinstance(leaf.get("fields"), Mapping)
            else []
        )
    }
    missing = [field for field in aliases.values() if _number(facts.get(field)) is None]
    if missing:
        return None, sorted(set(missing)), "备选知识产权路径字段不完整"
    counts = {
        alias: _number(facts.get(field)) or 0 for alias, field in aliases.items()
    }
    route_scores: list[float] = []
    for route in leaf.get("routes", []):
        if not isinstance(route, Mapping):
            continue
        base_alias = str(route.get("base_field") or "")
        base_min = _number(route.get("base_min")) or 0
        if counts.get(base_alias, 0) < base_min:
            continue
        weighted_extra = 0.0
        weights = route.get("increment_weights", {})
        if isinstance(weights, Mapping):
            for alias, weight_value in weights.items():
                count = counts.get(str(alias), 0)
                if str(alias) == base_alias:
                    count -= base_min
                weighted_extra += max(0.0, count) * (_number(weight_value) or 0)
        if str(leaf.get("rounding") or "floor") == "floor":
            weighted_extra = math.floor(weighted_extra)
        route_scores.append(
            (_number(route.get("base_score")) or 0) + weighted_extra
        )
    score = max(route_scores, default=0.0)
    maximum = _number(leaf.get("max_score"))
    if maximum is not None:
        score = min(score, maximum)
    return score, [], "按I类或II类知识产权的最优合规路径计算"


def _score_reviewed(
    leaf: Mapping[str, object],
    facts: Mapping[str, object],
) -> tuple[float | None, list[str], str]:
    field = str(leaf.get("field") or "")
    actual = _number(facts.get(field))
    if actual is None:
        return None, [field], "需要专家或材料审核后确认分值"
    minimum = _number(leaf.get("min_score")) or 0
    maximum = _number(leaf.get("max_score"))
    if maximum is None or actual < minimum or actual > maximum:
        return None, [field], f"人工分值必须在{minimum:g}至{maximum:g}之间"
    return actual, [], "使用经审核确认的人工分值"


def _evaluate_score_leaf(
    leaf: Mapping[str, object],
    facts: Mapping[str, object],
) -> dict[str, object]:
    method = str(leaf.get("method") or "")
    evaluator = {
        "band": _score_band,
        "count-step": _score_count_step,
        "alternative-count-step": _score_alternative_count_step,
        "reviewed": _score_reviewed,
    }.get(method)
    if evaluator is None:
        return {
            "leaf_id": leaf.get("leaf_id"),
            "status": "invalid",
            "score": None,
            "missing_fields": [],
            "reason": "未知评分方法",
        }
    score, missing, reason = evaluator(leaf, facts)
    return {
        "leaf_id": leaf.get("leaf_id"),
        "label": leaf.get("label"),
        "method": method,
        "status": "computed" if score is not None else "pending",
        "score": score,
        "max_score": leaf.get("max_score"),
        "missing_fields": missing,
        "reason": reason,
    }


def _compare(actual: object, operator: str, expected: object) -> bool | None:
    if operator == "truthy":
        return bool(actual)
    if operator == "falsy":
        return not bool(actual)
    if operator == "equals":
        return actual == expected
    if operator in {"in", "not-in"}:
        if not isinstance(expected, Sequence) or isinstance(expected, (str, bytes)):
            return None
        matched = actual in expected
        return matched if operator == "in" else not matched
    actual_number = _number(actual)
    expected_number = _number(expected)
    if actual_number is None or expected_number is None:
        return None
    if operator == "gte":
        return actual_number >= expected_number
    if operator == "gt":
        return actual_number > expected_number
    if operator == "lte":
        return actual_number <= expected_number
    if operator == "lt":
        return actual_number < expected_number
    return None


def _evaluate_rule(
    rule: Mapping[str, object],
    facts: Mapping[str, object],
) -> dict[str, object]:
    logic = str(rule.get("logic") or "")
    if logic in {"all", "any"}:
        children = [
            _evaluate_rule(child, facts)
            for child in rule.get("children", [])
            if isinstance(child, Mapping)
        ]
        statuses = [str(child.get("status") or "") for child in children]
        if logic == "all":
            status = (
                "failed"
                if "failed" in statuses
                else "pending"
                if "pending" in statuses
                else "passed"
            )
        else:
            status = (
                "passed"
                if "passed" in statuses
                else "pending"
                if "pending" in statuses
                else "failed"
            )
        return {
            "rule_id": rule.get("rule_id"),
            "logic": logic,
            "status": status,
            "children": children,
            "missing_fields": sorted(
                {
                    field
                    for child in children
                    for field in child.get("missing_fields", [])
                }
            ),
        }
    field = str(rule.get("field") or "")
    if field not in facts:
        return {
            "rule_id": rule.get("rule_id"),
            "field": field,
            "status": "pending",
            "missing_fields": [field],
            "reason": "缺少企业事实",
        }
    actual = facts.get(field)
    operator = str(rule.get("operator") or "")
    matched = _compare(actual, operator, rule.get("expected"))
    return {
        "rule_id": rule.get("rule_id"),
        "field": field,
        "operator": operator,
        "expected": rule.get("expected"),
        "actual": actual,
        "status": (
            "passed" if matched is True else "failed" if matched is False else "pending"
        ),
        "missing_fields": [],
        "reason": "按原生叶节点运算符比较",
    }


def evaluate_threshold_track(
    registry: Mapping[str, object],
    *,
    city: str,
    track_id: str,
    facts: Mapping[str, object],
) -> dict[str, object]:
    track = _track(registry, city, track_id)
    if track is None:
        return {
            "status": "unresolved",
            "city": city,
            "track_id": track_id,
            "formal_conclusion_allowed": False,
            "reason": "城市或阈值轨道未登记",
        }
    mode = str(track.get("execution_mode") or "")
    if mode == "project-rule-layer":
        return {
            "status": "delegated",
            "city": city,
            "track_id": track_id,
            "track_name": track.get("track_name"),
            "project_id": track.get("project_id"),
            "rule_layer_id": track.get("rule_layer_id"),
            "policy_status": track.get("policy_status"),
            "formal_conclusion_allowed": track.get(
                "formal_conclusion_allowed",
                str(track.get("policy_status") or "") == "current",
            ),
            "reason": "该轨道复用已编译的项目规则层",
        }

    score_groups: list[dict[str, object]] = []
    missing_score_fields: set[str] = set()
    base_score = 0.0
    bonus_score = 0.0
    score_complete = mode == "leaf-threshold-no-score"
    computed_score: float | None = None
    if mode == "leaf-threshold-and-score":
        for group in track.get("score_groups", []):
            if not isinstance(group, Mapping):
                continue
            leaf_results = [
                _evaluate_score_leaf(leaf, facts)
                for leaf in group.get("leaves", [])
                if isinstance(leaf, Mapping)
            ]
            for leaf in leaf_results:
                missing_score_fields.update(leaf.get("missing_fields", []))
            raw_score = sum(
                float(leaf["score"])
                for leaf in leaf_results
                if leaf.get("score") is not None
            )
            cap = _number(group.get("cap"))
            group_score = min(raw_score, cap) if cap is not None else raw_score
            is_bonus = bool(group.get("bonus"))
            if is_bonus:
                bonus_score += group_score
            else:
                base_score += group_score
            score_groups.append(
                {
                    "group_id": group.get("group_id"),
                    "label": group.get("label"),
                    "cap": group.get("cap"),
                    "bonus": is_bonus,
                    "score": group_score,
                    "status": (
                        "complete"
                        if all(leaf["status"] == "computed" for leaf in leaf_results)
                        else "pending"
                    ),
                    "leaves": leaf_results,
                }
            )
        base_cap = _number(track.get("base_score_cap"))
        bonus_cap = _number(track.get("bonus_score_cap"))
        if base_cap is not None:
            base_score = min(base_score, base_cap)
        if bonus_cap is not None:
            bonus_score = min(bonus_score, bonus_cap)
        score_complete = not missing_score_fields
        if score_complete:
            computed_score = base_score + bonus_score

    evaluation_facts = dict(facts)
    if computed_score is not None:
        evaluation_facts["$computed_score"] = computed_score
    hard_results = [
        _evaluate_rule(rule, evaluation_facts)
        for rule in track.get("hard_rules", [])
        if isinstance(rule, Mapping)
    ]
    submission_results = [
        _evaluate_rule(rule, evaluation_facts)
        for rule in track.get("submission_rules", [])
        if isinstance(rule, Mapping)
    ]
    preference_results = [
        _evaluate_rule(rule, evaluation_facts)
        for rule in track.get("preference_rules", [])
        if isinstance(rule, Mapping)
    ]
    hard_statuses = {str(item.get("status") or "") for item in hard_results}
    submission_statuses = {
        str(item.get("status") or "") for item in submission_results
    }
    exception_requested = any(
        bool(facts.get(str(item.get("field") or "")))
        for item in track.get("manual_exceptions", [])
        if isinstance(item, Mapping)
    )
    if "failed" in hard_statuses:
        conclusion = "manual-review" if exception_requested else "ineligible"
    elif "pending" in hard_statuses:
        conclusion = "conditional"
    elif submission_statuses & {"pending", "failed"}:
        conclusion = "conditional"
    else:
        conclusion = "eligible"
    formal_allowed = bool(track.get("formal_conclusion_allowed", True))
    if not formal_allowed:
        conclusion = "prospective-only"
    return {
        "status": "evaluated",
        "city": city,
        "track_id": track_id,
        "track_name": track.get("track_name"),
        "execution_mode": mode,
        "policy_status": track.get("policy_status"),
        "formal_conclusion_allowed": formal_allowed,
        "conclusion": conclusion,
        "hard_gates": hard_results,
        "preferences": preference_results,
        "manual_exceptions": list(track.get("manual_exceptions", [])),
        "source_documents": list(track.get("_source_documents", [])),
        "submission": {
            "status": (
                "complete"
                if submission_results
                and all(item["status"] == "passed" for item in submission_results)
                else "not-required"
                if not submission_results
                else "pending"
            ),
            "rules": submission_results,
        },
        "scoring": {
            "enabled": mode == "leaf-threshold-and-score",
            "status": (
                "complete"
                if score_complete
                else "not-applicable"
                if mode == "leaf-threshold-no-score"
                else "pending"
            ),
            "base_score": base_score if mode == "leaf-threshold-and-score" else None,
            "bonus_score": bonus_score if mode == "leaf-threshold-and-score" else None,
            "total_score": computed_score,
            "threshold": track.get("score_threshold"),
            "missing_fields": sorted(missing_score_fields),
            "groups": score_groups,
            "reason": track.get("score_reason"),
        },
        "threshold_pack_hash": _digest(track),
    }

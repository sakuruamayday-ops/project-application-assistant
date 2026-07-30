from __future__ import annotations

from typing import Mapping, Sequence


PREFLIGHT_DIMENSIONS = (
    "target",
    "task_type",
    "policy_context",
    "source_data",
    "calculation_scope",
    "output_contract",
    "authorization",
)
VALID_IMPACTS = {"high", "low"}
VALID_RESOLUTIONS = {"ask-user", "discover", "assume"}


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _normalized_requirement(raw: Mapping[str, object]) -> dict[str, object]:
    key = str(raw.get("key") or "").strip()
    label = str(raw.get("label") or "").strip()
    dimension = str(raw.get("dimension") or "").strip()
    impact = str(raw.get("impact") or "high").strip()
    resolution = str(raw.get("resolution") or "ask-user").strip()
    if not key or not label:
        raise ValueError("前置复盘字段必须包含key和label")
    if dimension not in PREFLIGHT_DIMENSIONS:
        raise ValueError(f"未知前置复盘维度：{dimension}")
    if impact not in VALID_IMPACTS:
        raise ValueError(f"未知影响级别：{impact}")
    if resolution not in VALID_RESOLUTIONS:
        raise ValueError(f"未知补齐方式：{resolution}")
    if impact == "high" and resolution == "assume":
        raise ValueError(f"高影响字段不得静默假设：{key}")
    if impact == "low" and resolution == "assume" and "default" not in raw:
        raise ValueError(f"低影响假设字段必须声明default：{key}")
    return {
        "key": key,
        "label": label,
        "dimension": dimension,
        "impact": impact,
        "resolution": resolution,
        "reason": str(raw.get("reason") or "").strip(),
        "allowed_values": list(raw.get("allowed_values") or []),
        **({"default": raw["default"]} if "default" in raw else {}),
    }


def assess_task_preflight(
    *,
    objective: str,
    requirements: Sequence[Mapping[str, object]],
    supplied: Mapping[str, object],
) -> dict[str, object]:
    """Return a deterministic omission scan before substantive execution.

    Missing discoverable fields must be resolved with read-only checks before
    asking the user. Only unresolved high-impact fields block on user input.
    Low-impact fields may proceed with an explicit reversible default.
    """

    normalized_objective = objective.strip()
    if not normalized_objective:
        raise ValueError("前置复盘必须声明任务目标")

    normalized = [_normalized_requirement(item) for item in requirements]
    keys = [str(item["key"]) for item in normalized]
    if len(keys) != len(set(keys)):
        raise ValueError("前置复盘字段key不得重复")

    resolved: dict[str, object] = {}
    discover_first: list[dict[str, object]] = []
    high_impact_gaps: list[dict[str, object]] = []
    low_impact_assumptions: list[dict[str, object]] = []

    for requirement in normalized:
        key = str(requirement["key"])
        if key in supplied and _has_value(supplied[key]):
            resolved[key] = supplied[key]
            continue
        resolution = str(requirement["resolution"])
        if resolution == "discover":
            discover_first.append(requirement)
        elif str(requirement["impact"]) == "high":
            high_impact_gaps.append(requirement)
        else:
            assumption = {**requirement, "assumed_value": requirement["default"]}
            low_impact_assumptions.append(assumption)
            resolved[key] = requirement["default"]

    if discover_first:
        status = "needs-discovery"
        next_action = "resolve-discoverable-gaps"
    elif high_impact_gaps:
        status = "needs-user-input"
        next_action = "ask-one-minimal-question"
    elif low_impact_assumptions:
        status = "ready-with-assumptions"
        next_action = "state-assumptions-and-proceed"
    else:
        status = "ready"
        next_action = "state-no-high-impact-gap-and-proceed"

    blocking_question = None
    if not discover_first and high_impact_gaps:
        prompts = []
        for item in high_impact_gaps:
            allowed = "、".join(str(value) for value in item["allowed_values"])
            prompts.append(
                f"{item['label']}{f'，可选：{allowed}' if allowed else ''}"
            )
        blocking_question = "开始实质性工作前，请主人一次确认：" + "；".join(prompts) + "。"

    return {
        "schema_version": 1,
        "objective": normalized_objective,
        "status": status,
        "can_start_substantive_work": not discover_first and not high_impact_gaps,
        "resolved": resolved,
        "discover_first": discover_first,
        "high_impact_gaps": high_impact_gaps,
        "low_impact_assumptions": low_impact_assumptions,
        "blocking_question": blocking_question,
        "next_action": next_action,
    }

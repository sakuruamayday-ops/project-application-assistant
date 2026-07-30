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
CONTINUITY_LIST_FIELDS = (
    "confirmed_facts",
    "confirmed_decisions",
    "rejected_options",
    "open_loops",
    "constraints",
    "assumptions",
    "next_actions",
)
CONTINUITY_SIGNAL_TYPES = {
    "decision-conflict",
    "topic-shift-with-open-loops",
    "constraint-omission",
    "rejected-option-reintroduced",
    "assumption-promoted-to-fact",
    "important-decision-unconfirmed",
}
CHECKPOINT_TRIGGERS = {
    "topic-switch",
    "important-decision",
    "open-loop-threshold",
    "pause-marker",
    "before-execution",
    "context-compaction",
    "explicit-request",
}
VALID_PERSISTENCE_SCOPES = {"session", "durable"}


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


def _normalized_text_list(value: object, *, field: str) -> list[str]:
    if value is None:
        return []
    raw_items = [value] if isinstance(value, str) else value
    if not isinstance(raw_items, (list, tuple, set)):
        raise ValueError(f"会话状态字段{field}必须是文本或文本列表")
    normalized = [str(item).strip() for item in raw_items if str(item).strip()]
    return list(dict.fromkeys(normalized))


def _normalized_conversation_state(
    raw: Mapping[str, object],
) -> dict[str, object]:
    state = {
        "current_topic": str(raw.get("current_topic") or "").strip(),
        "objective": str(raw.get("objective") or "").strip(),
    }
    for field in CONTINUITY_LIST_FIELDS:
        state[field] = _normalized_text_list(raw.get(field), field=field)
    return state


def _normalized_continuity_signal(
    raw: Mapping[str, object],
) -> dict[str, str]:
    signal_type = str(raw.get("type") or "").strip()
    summary = str(raw.get("summary") or "").strip()
    impact = str(raw.get("impact") or "low").strip()
    if signal_type not in CONTINUITY_SIGNAL_TYPES:
        raise ValueError(f"未知会话连续性信号：{signal_type}")
    if not summary:
        raise ValueError("会话连续性信号必须包含summary")
    if impact not in VALID_IMPACTS:
        raise ValueError(f"未知影响级别：{impact}")
    return {
        "type": signal_type,
        "summary": summary,
        "impact": impact,
        "source": str(raw.get("source") or "").strip(),
    }


def _normalized_persistence_candidate(
    raw: Mapping[str, object],
) -> dict[str, object]:
    summary = str(raw.get("summary") or "").strip()
    scope = str(raw.get("scope") or "session").strip()
    if not summary:
        raise ValueError("会话持久化候选必须包含summary")
    if scope not in VALID_PERSISTENCE_SCOPES:
        raise ValueError(f"未知会话持久化范围：{scope}")
    return {
        "summary": summary,
        "scope": scope,
        "sensitive": bool(raw.get("sensitive", False)),
        "kind": str(raw.get("kind") or "discussion").strip(),
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


def assess_conversation_continuity(
    *,
    state: Mapping[str, object],
    signals: Sequence[Mapping[str, object]] = (),
    checkpoint_triggers: Sequence[str] = (),
    persistence_candidates: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Enforce continuity without turning every reply into a meeting record.

    Upstream language reasoning extracts structured state and signals. This
    function deterministically decides when to remind, checkpoint, block a
    dependent conclusion, or request permission before durable persistence.
    """

    normalized_state = _normalized_conversation_state(state)
    normalized_signals = [
        _normalized_continuity_signal(signal) for signal in signals
    ]
    normalized_triggers = list(
        dict.fromkeys(str(trigger).strip() for trigger in checkpoint_triggers)
    )
    unknown_triggers = [
        trigger
        for trigger in normalized_triggers
        if trigger not in CHECKPOINT_TRIGGERS
    ]
    if unknown_triggers:
        raise ValueError(
            "未知会话检查点触发器：" + "、".join(unknown_triggers)
        )

    open_loops = list(normalized_state["open_loops"])
    if len(open_loops) >= 3 and "open-loop-threshold" not in normalized_triggers:
        normalized_triggers.append("open-loop-threshold")
    if any(
        signal["type"] == "topic-shift-with-open-loops"
        for signal in normalized_signals
    ) and "topic-switch" not in normalized_triggers:
        normalized_triggers.append("topic-switch")
    if any(
        signal["type"] == "important-decision-unconfirmed"
        for signal in normalized_signals
    ) and "important-decision" not in normalized_triggers:
        normalized_triggers.append("important-decision")

    reminder_required = bool(normalized_signals)
    high_impact_signals = [
        signal
        for signal in normalized_signals
        if signal["impact"] == "high"
    ]
    reminder = None
    if reminder_required:
        reminder = "连续性提醒：" + "；".join(
            signal["summary"] for signal in normalized_signals
        ) + "。"

    blocking_question = None
    if high_impact_signals:
        blocking_question = (
            "继续形成依赖性结论前，请主人一次确认："
            + "；".join(signal["summary"] for signal in high_impact_signals)
            + "。"
        )

    checkpoint = {
        "已确认": [
            *normalized_state["confirmed_facts"],
            *normalized_state["confirmed_decisions"],
        ],
        "尚未确认": [
            *normalized_state["open_loops"],
            *[
                f"假设：{item}"
                for item in normalized_state["assumptions"]
            ],
        ],
        "关键限制": [
            *normalized_state["constraints"],
            *[
                f"已否决：{item}"
                for item in normalized_state["rejected_options"]
            ],
        ],
        "下一步": list(normalized_state["next_actions"]),
    }
    checkpoint_required = bool(normalized_triggers)

    candidates = [
        _normalized_persistence_candidate(candidate)
        for candidate in persistence_candidates
    ]
    durable_candidates = [
        candidate
        for candidate in candidates
        if candidate["scope"] == "durable" and not candidate["sensitive"]
    ]
    blocked_sensitive_candidates = [
        candidate for candidate in candidates if candidate["sensitive"]
    ]
    persistence_action = (
        "ask-before-persisting"
        if durable_candidates
        else "do-not-persist"
    )

    if reminder_required and checkpoint_required:
        status = "reminder-and-checkpoint"
    elif reminder_required:
        status = "reminder"
    elif checkpoint_required:
        status = "checkpoint"
    else:
        status = "silent"

    return {
        "schema_version": 1,
        "status": status,
        "state": normalized_state,
        "reminder_required": reminder_required,
        "reminder": reminder,
        "signals": normalized_signals,
        "requires_user_resolution": bool(high_impact_signals),
        "can_form_dependent_conclusion": not high_impact_signals,
        "blocking_question": blocking_question,
        "checkpoint_required": checkpoint_required,
        "checkpoint_reasons": normalized_triggers,
        "checkpoint": checkpoint,
        "persistence_action": persistence_action,
        "durable_candidates": durable_candidates,
        "blocked_sensitive_candidates": blocked_sensitive_candidates,
        "next_action": (
            "resolve-high-impact-continuity-conflict"
            if high_impact_signals
            else "remind-and-continue"
            if reminder_required
            else "emit-checkpoint"
            if checkpoint_required
            else "continue-silently"
        ),
    }

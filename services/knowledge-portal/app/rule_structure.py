from __future__ import annotations

import re
from typing import Mapping, Sequence


COMPOSITE_TEXT_PATTERN = re.compile(
    r"(?:且|同时|分别|其中|至少|任一|之一|或|分档|分支|对应标准|对应要求|；|、)"
)
ATOMIC_FACT_SEMANTICS = frozenset(
    {
        "atomic-evidence",
        "atomic-policy-assertion",
        "assessment-conclusion",
        "certificate-status",
    }
)


def _rule_leaves(
    rules: Sequence[Mapping[str, object]],
    *,
    path: str,
) -> list[tuple[str, Mapping[str, object]]]:
    leaves: list[tuple[str, Mapping[str, object]]] = []
    for index, rule in enumerate(rules):
        current_path = f"{path}[{index}]"
        children = rule.get("children")
        if isinstance(children, list) and children:
            leaves.extend(
                _rule_leaves(
                    [
                        child
                        for child in children
                        if isinstance(child, Mapping)
                    ],
                    path=f"{current_path}.children",
                )
            )
        else:
            leaves.append((current_path, rule))
    return leaves


def audit_composite_rule_structure(
    pack: Mapping[str, object],
) -> dict[str, object]:
    """Find legacy aggregate booleans still used as rule leaves.

    The suffix is only a signal. A field explicitly declared as an atomic
    certificate, assessment conclusion or evidence assertion is allowed.
    Everything else whose policy quote contains logical branching must be
    represented with native ``all``/``any`` children before formal evaluation.
    """

    fact_specs = {
        str(spec.get("field") or ""): spec
        for spec in pack.get("fact_fields", [])
        if isinstance(spec, Mapping)
    }
    layers = [
        layer
        for layer in pack.get("rule_layers", [])
        if isinstance(layer, Mapping)
    ]
    groups: list[tuple[str, Sequence[Mapping[str, object]]]] = []
    if layers:
        for layer_index, layer in enumerate(layers):
            rules = [
                rule
                for rule in layer.get("rules", [])
                if isinstance(rule, Mapping)
            ]
            groups.append((f"rule_layers[{layer_index}].rules", rules))
    else:
        base_key = (
            "rule_cards"
            if isinstance(pack.get("rule_cards"), list)
            else "rules"
        )
        groups.append(
            (
                base_key,
                [
                    rule
                    for rule in pack.get(base_key, [])
                    if isinstance(rule, Mapping)
                ],
            )
        )
        for overlay_key in ("annual_overlays", "jurisdiction_overlays"):
            overlays = pack.get(overlay_key)
            if not isinstance(overlays, list):
                continue
            for overlay_index, overlay in enumerate(overlays):
                if not isinstance(overlay, Mapping):
                    continue
                rules = overlay.get("rules")
                if not isinstance(rules, list):
                    continue
                groups.append(
                    (
                        f"{overlay_key}[{overlay_index}].rules",
                        [
                            rule
                            for rule in rules
                            if isinstance(rule, Mapping)
                        ],
                    )
                )

    unresolved: list[dict[str, str]] = []
    declared_atomic: list[str] = []
    for base_path, rules in groups:
        for path, rule in _rule_leaves(rules, path=base_path):
            field = str(rule.get("field") or "").strip()
            if not field.endswith("_met"):
                continue
            spec = fact_specs.get(field, {})
            semantics = str(
                rule.get("fact_semantics")
                or spec.get("fact_semantics")
                or ""
            ).strip()
            if semantics in ATOMIC_FACT_SEMANTICS:
                declared_atomic.append(field)
                continue
            quote = str(rule.get("source_quote") or "")
            derivation = " ".join(
                str(item)
                for item in spec.get("derivation_requirements", [])
            ) or str(spec.get("derivation") or "")
            composite_signal = COMPOSITE_TEXT_PATTERN.search(
                f"{quote} {derivation}"
            )
            unresolved.append(
                {
                    "path": path,
                    "rule_id": str(rule.get("rule_id") or ""),
                    "field": field,
                    "reason": (
                        "包含可拆分逻辑但仍依赖综合布尔事实"
                        if composite_signal
                        else "综合布尔字段未声明可审计的原子事实语义"
                    ),
                }
            )

    unique_unresolved = list(
        {
            (item["path"], item["field"]): item
            for item in unresolved
        }.values()
    )
    return {
        "status": "blocked" if unique_unresolved else "passed",
        "formal_decision_allowed": not unique_unresolved,
        "unresolved_composite_leaves": unique_unresolved,
        "unresolved_count": len(unique_unresolved),
        "declared_atomic_fields": sorted(set(declared_atomic)),
        "rule": (
            "综合条件必须拆为原生all/any叶节点；只有证书状态、评价结论或"
            "单一证据断言可显式声明为原子事实"
        ),
    }

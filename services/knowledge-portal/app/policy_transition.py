from __future__ import annotations

from typing import Mapping, Sequence


FUTURE_MODES = frozenset({"forecast", "future-preparation", "prediction"})


def _variants(
    registry: Mapping[str, object],
    family_id: str,
) -> list[dict[str, object]]:
    for family in registry.get("project_families", []):
        if not isinstance(family, Mapping):
            continue
        if str(family.get("family_id") or "") != family_id:
            continue
        return [
            dict(item)
            for item in family.get("city_variants", [])
            if isinstance(item, Mapping)
        ]
    return []


def validate_four_city_policy_registry(
    registry: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []
    cities = {
        str(city)
        for city in registry.get("cities", [])
        if str(city).strip()
    }
    if len(cities) != 4:
        errors.append("四市政策注册表必须且只能登记4个目标城市")
    family_ids: set[str] = set()
    for family in registry.get("project_families", []):
        if not isinstance(family, Mapping):
            errors.append("project_families中的项目族必须为对象")
            continue
        family_id = str(family.get("family_id") or "").strip()
        if not family_id:
            errors.append("项目族缺少family_id")
            continue
        family_ids.add(family_id)
        variants = [
            item
            for item in family.get("city_variants", [])
            if isinstance(item, Mapping)
        ]
        variant_cities = {str(item.get("city") or "") for item in variants}
        missing = sorted(cities - variant_cities)
        extra = sorted(variant_cities - cities)
        if missing:
            errors.append(f"{family_id}缺少城市：{'、'.join(missing)}")
        if extra:
            errors.append(f"{family_id}出现非目标城市：{'、'.join(extra)}")
        for item in variants:
            city = str(item.get("city") or "")
            for key in ("canonical_name", "route_status", "policy_status"):
                if key == "policy_status" and item.get("formal_policy_status"):
                    continue
                if not str(item.get(key) or "").strip():
                    errors.append(f"{family_id}/{city}缺少{key}")
    required_families = {
        "municipal-enterprise-technology-center",
        "municipal-enterprise-rd-platform",
    }
    for family_id in sorted(required_families - family_ids):
        errors.append(f"缺少项目族：{family_id}")
    return errors


def resolve_policy_transition(
    registry: Mapping[str, object],
    *,
    family_id: str,
    city: str,
    evaluation_mode: str = "current-assessment",
) -> dict[str, object]:
    variant = next(
        (
            item
            for item in _variants(registry, family_id)
            if str(item.get("city") or "") == city
        ),
        None,
    )
    if variant is None:
        return {
            "status": "unresolved",
            "family_id": family_id,
            "city": city,
            "evaluation_mode": evaluation_mode,
            "formal_conclusion_allowed": False,
            "reason": "目标项目族或城市未进入政策覆盖注册表",
        }

    prospective = str(variant.get("prospective_policy") or "").strip()
    future_mode = evaluation_mode in FUTURE_MODES
    if prospective and future_mode:
        primary_policy = prospective
        primary_status = str(
            variant.get("prospective_policy_status") or "draft"
        )
        formal_allowed = False
        output_label = "前瞻准备（征求意见稿）"
        reason = (
            "征求意见稿已成为未来准备主基线；"
            "正式文件发布前不得输出正式资格结论"
        )
        old_policy_role = "current-formal-and-historical-only"
    else:
        primary_policy = str(variant.get("formal_policy") or "")
        primary_status = str(
            variant.get("formal_policy_status")
            or variant.get("policy_status")
            or ""
        )
        formal_allowed = not primary_status.startswith(("draft", "invalid"))
        output_label = "查询日正式政策"
        reason = (
            "当前正式判断仍使用现行文件，同时必须披露已发布的征求意见稿"
            if prospective
            else "按目标城市查询日现行政策判断"
        )
        old_policy_role = "current-formal"

    return {
        "status": "resolved",
        "family_id": family_id,
        "city": city,
        "evaluation_mode": evaluation_mode,
        "route_status": variant.get("route_status"),
        "canonical_name": variant.get("canonical_name"),
        "primary_policy": primary_policy,
        "primary_policy_status": primary_status,
        "formal_policy": variant.get("formal_policy"),
        "prospective_policy": variant.get("prospective_policy"),
        "prospective_policy_status": variant.get("prospective_policy_status"),
        "consultation_period": variant.get("consultation_period"),
        "transition": variant.get("transition"),
        "old_policy_role": old_policy_role,
        "output_label": output_label,
        "formal_conclusion_allowed": formal_allowed,
        "mandatory_disclosures": [
            disclosure
            for disclosure in (
                "征求意见稿尚未正式生效" if prospective else "",
                str(variant.get("transition") or ""),
                str(variant.get("exception") or ""),
                str(variant.get("note") or ""),
            )
            if disclosure
        ],
        "reason": reason,
    }


def consultation_change_set(
    before: Sequence[Mapping[str, object]],
    after: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    def index(
        items: Sequence[Mapping[str, object]],
    ) -> dict[tuple[str, str], Mapping[str, object]]:
        return {
            (
                str(item.get("family_id") or ""),
                str(item.get("city") or ""),
            ): item
            for item in items
        }

    before_index = index(before)
    after_index = index(after)
    keys = sorted(set(before_index) | set(after_index))
    changed = [
        {
            "family_id": family_id,
            "city": city,
            "before": dict(before_index.get((family_id, city), {})),
            "after": dict(after_index.get((family_id, city), {})),
            "requires_recompile": True,
            "affected_outputs": [
                "项目匹配",
                "企业差距评估",
                "预测准备",
                "政策来源披露",
            ],
        }
        for family_id, city in keys
        if dict(before_index.get((family_id, city), {}))
        != dict(after_index.get((family_id, city), {}))
    ]
    return {
        "changed_count": len(changed),
        "changes": changed,
    }

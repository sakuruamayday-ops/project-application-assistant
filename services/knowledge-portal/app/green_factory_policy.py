from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "four-city-green-factory-policy-registry.json"
)
EXPECTED_ADMINISTRATIVE_UNITS = {
    "杭州市": (
        "上城区",
        "拱墅区",
        "西湖区",
        "滨江区",
        "萧山区",
        "余杭区",
        "临平区",
        "钱塘区",
        "富阳区",
        "临安区",
        "桐庐县",
        "淳安县",
        "建德市",
    ),
    "宁波市": (
        "海曙区",
        "江北区",
        "镇海区",
        "北仑区",
        "鄞州区",
        "奉化区",
        "余姚市",
        "慈溪市",
        "宁海县",
        "象山县",
    ),
    "绍兴市": (
        "越城区",
        "柯桥区",
        "上虞区",
        "诸暨市",
        "嵊州市",
        "新昌县",
    ),
    "金华市": (
        "婺城区",
        "金东区",
        "兰溪市",
        "义乌市",
        "东阳市",
        "永康市",
        "武义县",
        "浦江县",
        "磐安县",
    ),
}
ALLOWED_ROUTE_STATUSES = frozenset(
    {
        "district-recognition-under-city-rule",
        "district-three-star-recognition",
        "redirect-to-municipal-evaluation",
    }
)


def _is_sha256(value: object) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _official_url(value: object) -> bool:
    host = (urlparse(str(value or "")).hostname or "").lower()
    return host == "gov.cn" or host.endswith(".gov.cn")


@lru_cache(maxsize=1)
def load_four_city_green_factory_registry() -> dict[str, object]:
    try:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def validate_four_city_green_factory_registry(
    registry: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []
    cities = [
        item for item in registry.get("city_registrations", [])
        if isinstance(item, Mapping)
    ]
    city_names = {str(item.get("city") or "") for item in cities}
    expected_cities = set(EXPECTED_ADMINISTRATIVE_UNITS)
    if city_names != expected_cities:
        errors.append("绿色工厂注册表必须完整覆盖杭州、宁波、绍兴、金华四市")

    all_units: list[str] = []
    all_sources: set[str] = set()
    for city in cities:
        city_name = str(city.get("city") or "")
        expected_units = set(EXPECTED_ADMINISTRATIVE_UNITS.get(city_name, ()))
        sources = [
            item for item in city.get("formal_sources", [])
            if isinstance(item, Mapping)
        ]
        source_ids = {
            str(item.get("source_id") or "").strip()
            for item in sources
            if str(item.get("source_id") or "").strip()
        }
        if not sources:
            errors.append(f"{city_name}缺少正式政策来源")
        for source in sources:
            source_id = str(source.get("source_id") or "").strip()
            if not source_id:
                errors.append(f"{city_name}正式来源缺少source_id")
            elif source_id in all_sources:
                errors.append(f"正式来源ID重复：{source_id}")
            all_sources.add(source_id)
            if not (
                _official_url(source.get("official_url"))
                or _is_sha256(source.get("archive_sha256"))
            ):
                errors.append(
                    f"{city_name}/{source_id or '未命名来源'}"
                    "缺少政府官网或已审计原文哈希"
                )

        registrations = [
            item for item in city.get("district_registrations", [])
            if isinstance(item, Mapping)
        ]
        registered_units = {
            str(item.get("district") or "") for item in registrations
        }
        if registered_units != expected_units:
            missing = sorted(expected_units - registered_units)
            extra = sorted(registered_units - expected_units)
            if missing:
                errors.append(f"{city_name}缺少区县：{'、'.join(missing)}")
            if extra:
                errors.append(f"{city_name}出现非行政区县：{'、'.join(extra)}")
        if len(registrations) != len(registered_units):
            errors.append(f"{city_name}存在重复区县登记")

        for registration in registrations:
            district = str(registration.get("district") or "")
            all_units.append(district)
            route_status = str(registration.get("route_status") or "")
            if route_status not in ALLOWED_ROUTE_STATUSES:
                errors.append(f"{city_name}/{district}的route_status无效")
            applied_sources = {
                str(item)
                for item in registration.get("formal_source_ids", [])
                if str(item).strip()
            }
            if not applied_sources:
                errors.append(f"{city_name}/{district}未绑定正式来源")
            elif not applied_sources <= source_ids:
                errors.append(f"{city_name}/{district}引用未注册正式来源")
            if (
                route_status == "redirect-to-municipal-evaluation"
                and str(registration.get("target_project_id") or "")
                != "green-factory-2"
            ):
                errors.append(f"{city_name}/{district}缺少市级项目路由目标")

    if len(all_units) != 38:
        errors.append("四市绿色工厂行政区县登记总数必须为38")
    return errors


def district_parent_city(
    district: object,
    registry: Mapping[str, object] | None = None,
) -> str:
    target = str(district or "").strip()
    if not target:
        return ""
    payload = registry or load_four_city_green_factory_registry()
    for city in payload.get("city_registrations", []):
        if not isinstance(city, Mapping):
            continue
        for registration in city.get("district_registrations", []):
            if (
                isinstance(registration, Mapping)
                and str(registration.get("district") or "") == target
            ):
                return str(city.get("city") or "")
    return ""


def expand_green_factory_context_regions(
    regions: Sequence[object],
    registry: Mapping[str, object] | None = None,
) -> list[str]:
    expanded: list[str] = []
    for raw_region in regions:
        region = str(raw_region or "").strip()
        if not region:
            continue
        if region not in expanded:
            expanded.append(region)
        parent = district_parent_city(region, registry)
        if parent and parent not in expanded:
            expanded.append(parent)
    return expanded


def resolve_green_factory_registration(
    district: str,
    registry: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload = registry or load_four_city_green_factory_registry()
    for city in payload.get("city_registrations", []):
        if not isinstance(city, Mapping):
            continue
        sources = {
            str(item.get("source_id") or ""): dict(item)
            for item in city.get("formal_sources", [])
            if isinstance(item, Mapping)
        }
        for registration in city.get("district_registrations", []):
            if not isinstance(registration, Mapping):
                continue
            if str(registration.get("district") or "") != district:
                continue
            source_ids = [
                str(item)
                for item in registration.get("formal_source_ids", [])
                if str(item).strip()
            ]
            return {
                "status": "resolved",
                "city": str(city.get("city") or ""),
                **dict(registration),
                "formal_sources": [
                    sources[source_id]
                    for source_id in source_ids
                    if source_id in sources
                ],
            }
    return {
        "status": "unresolved",
        "district": district,
        "formal_conclusion_allowed": False,
        "reason": "目标行政区县未进入四市绿色工厂正式政策注册表",
    }

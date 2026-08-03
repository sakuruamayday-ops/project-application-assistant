from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


GENERIC_PRODUCT_HEADS = {
    "产品",
    "材料",
    "设备",
    "装置",
    "系统",
    "软件",
    "平台",
    "组件",
    "部件",
    "制品",
    "仪器",
    "装备",
    "零部",
}

BROAD_INDUSTRY_TERMS = (
    "其他未列明",
    "研究和试验发展",
    "科技推广和应用服务",
    "科技推广服务",
    "技术推广服务",
    "专业技术服务",
    "商务服务",
)

INDUSTRY_CANONICAL_OVERRIDES = {
    "汽车零部件及配件制造": "汽车零部件",
    "阀门和旋塞制造": "阀门",
    "应用软件开发": "应用软件",
    "工业自动控制系统装置制造": "工业自动控制系统",
    "配电开关控制设备制造": "配电开关设备",
}

PRODUCT_MODIFIERS = (
    "数字化",
    "一体化",
    "智能化",
    "智能",
    "高性能",
    "高效",
    "新型",
    "绿色",
    "全自动",
    "多功能",
)


@dataclass(frozen=True)
class DerivedSubject:
    canonical_subject: str
    raw_subject: str
    attributes: tuple[str, ...]
    confidence: str


def _clean(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\s\u3000]+", "", text)
    text = text.strip("|,，;；。:：\"'“”‘’")
    return text


def derive_product_subject(value: object) -> DerivedSubject | None:
    """Derive a searchable Chinese product head without collapsing to generic nouns."""

    raw = _clean(value)
    if len(raw) < 2:
        return None
    attributes: list[str] = []
    candidate = raw

    version_pattern = re.compile(
        r"(?:[-_/]?V(?:ER(?:SION)?)?\s*\d+(?:\.\d+){0,4}[A-Z0-9._-]*|"
        r"[-_/]?版本\d+(?:\.\d+)*)$",
        re.IGNORECASE,
    )
    version_match = version_pattern.search(candidate)
    if version_match:
        attributes.append(version_match.group(0).lstrip("-_/"))
        candidate = candidate[: version_match.start()]

    capacity_pattern = re.compile(
        r"^(\d+(?:\.\d+)?(?:MW|KW|W|GW|KV|V|A|AH|KWH|MWH|T/H|KG|MM|CM))",
        re.IGNORECASE,
    )
    capacity_match = capacity_pattern.match(candidate)
    if capacity_match:
        attributes.append(capacity_match.group(1))
        candidate = candidate[capacity_match.end() :]

    parenthetical = re.findall(r"[（(]([^（）()]{1,40})[）)]", candidate)
    if parenthetical:
        attributes.extend(parenthetical)
        candidate = re.sub(r"[（(][^（）()]{1,40}[）)]", "", candidate)

    for modifier in PRODUCT_MODIFIERS:
        if modifier in candidate:
            stripped = candidate.replace(modifier, "")
            if len(stripped) >= 4 and stripped not in GENERIC_PRODUCT_HEADS:
                attributes.append(modifier)
                candidate = stripped

    purpose_match = re.match(r"^(.{2,24}?)(?:专)?用(.{2,})$", candidate)
    if purpose_match and not purpose_match.group(1).endswith(("应", "使", "采")):
        attributes.append(purpose_match.group(1) + "用")
        candidate = purpose_match.group(2)

    candidate = re.sub(r"(?:系列|产品)$", "", candidate)
    candidate = candidate.strip("-_/·•")
    if len(candidate) < 2 or candidate in GENERIC_PRODUCT_HEADS:
        candidate = re.sub(r"(?:系列|产品)$", "", raw).strip("-_/·•")
    if len(candidate) < 2 or candidate in GENERIC_PRODUCT_HEADS:
        return None
    return DerivedSubject(
        canonical_subject=candidate,
        raw_subject=raw,
        attributes=tuple(dict.fromkeys(item for item in attributes if item)),
        confidence="derived_product_head",
    )


def derive_industry_subject(value: object) -> DerivedSubject | None:
    """Normalize an industryName into a Chinese search topic without inventing 主营业务."""

    raw = _clean(value)
    if (
        len(raw) < 2
        or raw.startswith("其他")
        or any(term in raw for term in BROAD_INDUSTRY_TERMS)
    ):
        return None
    candidate = INDUSTRY_CANONICAL_OVERRIDES.get(raw, raw)
    if candidate == raw:
        candidate = re.sub(r"(?:行业)?(?:制造业|制造|生产|加工|研发|开发)$", "", candidate)
        candidate = candidate.replace("及配件", "").replace("和旋塞", "")
        candidate = re.sub(r"系统装置$", "系统", candidate)
    candidate = candidate.strip("-_/·•")
    if len(candidate) < 2 or candidate in GENERIC_PRODUCT_HEADS:
        return None
    return DerivedSubject(
        canonical_subject=candidate,
        raw_subject=raw,
        attributes=(),
        confidence="source_industry_classification",
    )

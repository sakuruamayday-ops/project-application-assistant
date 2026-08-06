#!/usr/bin/env python3
"""Grounded evidence registry, renderer and market-share verifier.

The module deliberately stays dependency-free so it can be reused by every
host supported by the skill bundle.  It validates provenance structurally; it
does not pretend that lexical checks can prove semantic entailment.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import posixpath
import re
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET


RECORD_TYPES = {"fact", "calculation", "inference", "pending"}
RECORD_STATUSES = {"verified", "unverified", "conflicted", "expired"}
SOURCE_KINDS = {
    "official_web",
    "public_web",
    "research_report",
    "knowledge_base",
    "user_file",
    "enterprise_statement",
    "database",
    "other",
}
SOURCE_ACCESS_STATUSES = {"obtained", "reference_only"}
WEB_SOURCE_KINDS = {"official_web", "public_web", "research_report"}
LOCAL_SOURCE_KINDS = {"knowledge_base", "user_file"}
BASE_REQUIRED = {
    "id",
    "subject",
    "claim",
    "type",
    "source",
    "retrieved_at",
    "location",
    "status",
}
SIX_SAME_KEYS = ("year", "geography", "product", "application", "unit", "tax_basis")
SIX_SAME_STATUSES = {"same", "explained", "mismatch", "unknown"}
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "spm",
}
SKILLS_ROOT = Path(__file__).resolve().parents[2]
DELIVERY_CONFIG_PATH = SKILLS_ROOT / "report-skill-registry.json"
VALIDATOR_ID = "grounded-delivery/v1"
OOXML_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"


def load_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return {"records": [json.loads(line) for line in text.splitlines() if line.strip()]}
    value = json.loads(text)
    if isinstance(value, list):
        return {"records": value}
    if not isinstance(value, dict):
        raise ValueError("台账顶层必须是JSON对象、数组或JSONL")
    return value


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def normalize_url(url: str) -> str:
    """Normalize a URL for deterministic source de-duplication."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower().startswith("utm_") or key.lower() in TRACKING_QUERY_KEYS:
            continue
        query.append((key, value))
    return urlunsplit((scheme, netloc, path, urlencode(sorted(query)), ""))


def _significant_length(text: str) -> int:
    return len(re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE))


def _lexical_units(text: str) -> set[str]:
    lowered = text.lower()
    latin = {token for token in re.findall(r"[a-z0-9][a-z0-9._%-]+", lowered) if len(token) >= 2}
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", lowered)
    cjk = {run[index : index + 2] for run in cjk_runs for index in range(max(0, len(run) - 1))}
    return latin | cjk


def _record_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in payload.get("records", [])
        if isinstance(item, dict) and item.get("id") not in (None, "")
    }


def _source_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in payload.get("sources", [])
        if isinstance(item, dict) and item.get("id") not in (None, "")
    }


def record_source_ids(record: dict[str, Any]) -> list[str]:
    return _as_list(record.get("source"))


def resolve_source_lineage(
    record_id: str,
    records: dict[str, dict[str, Any]],
    trail: tuple[str, ...] = (),
) -> list[str]:
    """Resolve direct and derived sources while preserving first-use order."""
    if record_id in trail or record_id not in records:
        return []
    record = records[record_id]
    ordered = list(record_source_ids(record))
    dependencies = []
    if record.get("type") == "calculation":
        dependencies = _as_list(record.get("inputs"))
    elif record.get("type") == "inference":
        dependencies = _as_list(record.get("supports"))
    for dependency in dependencies:
        ordered.extend(resolve_source_lineage(dependency, records, trail + (record_id,)))
    return list(dict.fromkeys(ordered))


def _validate_sources(payload: dict[str, Any], strict: bool) -> tuple[list[str], list[str]]:
    sources = payload.get("sources", [])
    errors: list[str] = []
    warnings: list[str] = []
    if sources is None:
        sources = []
    if not isinstance(sources, list):
        return ["sources必须是数组"], warnings
    if strict and not sources:
        errors.append("严格溯源模式缺少sources来源登记表")
    seen_ids: set[str] = set()
    seen_urls: dict[str, str] = {}
    declared_sources = _source_map(payload)
    for index, source in enumerate(sources, 1):
        prefix = f"来源{index}"
        if not isinstance(source, dict):
            errors.append(f"{prefix}:必须是对象")
            continue
        source_id = str(source.get("id", ""))
        kind = source.get("kind")
        access_status = source.get("access_status")
        if not source_id:
            errors.append(f"{prefix}:缺少id")
        elif source_id in seen_ids:
            errors.append(f"{prefix}:来源编号重复:{source_id}")
        seen_ids.add(source_id)
        if kind not in SOURCE_KINDS:
            errors.append(f"{prefix}:来源类型不合法:{kind}")
        if strict and access_status not in SOURCE_ACCESS_STATUSES:
            errors.append(f"{prefix}:严格模式缺少或不支持access_status:{access_status}")
        if access_status in (None, "obtained"):
            if not _valid_date(source.get("retrieved_at")):
                errors.append(f"{prefix}:retrieved_at不是有效ISO日期")
        elif access_status == "reference_only":
            if source.get("retrieved_at") not in (None, ""):
                errors.append(f"{prefix}:仅登记来源不得填写retrieved_at暗示已取得原文")
            if not _valid_date(source.get("registered_at")):
                errors.append(f"{prefix}:仅登记来源缺少有效registered_at")
            registered_via = str(source.get("registered_via") or "")
            if not registered_via:
                errors.append(f"{prefix}:仅登记来源缺少registered_via")
            elif registered_via == source_id:
                errors.append(f"{prefix}:registered_via不得引用自身")
            elif registered_via not in declared_sources:
                errors.append(f"{prefix}:registered_via引用未知来源:{registered_via}")
            elif declared_sources[registered_via].get("access_status") == "reference_only":
                errors.append(f"{prefix}:registered_via必须指向已取得的登记载体:{registered_via}")
        if kind in WEB_SOURCE_KINDS:
            for field in ("title", "publisher", "url"):
                if not source.get(field):
                    errors.append(f"{prefix}:网页来源缺少{field}")
            url = source.get("url")
            if isinstance(url, str):
                parts = urlsplit(url)
                if parts.scheme not in {"http", "https"} or not parts.netloc:
                    errors.append(f"{prefix}:url不是HTTP或HTTPS地址")
                else:
                    normalized = normalize_url(url)
                    previous = seen_urls.get(normalized)
                    if previous and previous != source_id:
                        errors.append(f"{prefix}:与{previous}重复登记同一URL")
                    seen_urls[normalized] = source_id
        elif kind in LOCAL_SOURCE_KINDS:
            file_name = source.get("file_name")
            if not file_name:
                errors.append(f"{prefix}:本地或知识库来源缺少file_name")
            elif Path(str(file_name)).name != str(file_name):
                errors.append(f"{prefix}:file_name只能是文件名，内部路径应放入internal")
        elif kind == "enterprise_statement" and not (source.get("title") or source.get("file_name")):
            errors.append(f"{prefix}:企业陈述来源缺少title或file_name")
        if kind == "knowledge_base" and source.get("url"):
            warnings.append(f"{prefix}:知识库URL只供内部登记，对外渲染将隐藏")
    return errors, warnings


def _validate_records(payload: dict[str, Any], strict: bool) -> tuple[list[str], list[str]]:
    raw_records = payload.get("records", [])
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw_records, list):
        return ["records必须是数组"], warnings
    records = _record_map(payload)
    sources = _source_map(payload)
    seen: set[str] = set()
    for index, record in enumerate(raw_records, 1):
        prefix = f"记录{index}"
        if not isinstance(record, dict):
            errors.append(f"{prefix}:必须是对象")
            continue
        missing = sorted(BASE_REQUIRED - set(record))
        if missing:
            errors.append(f"{prefix}:缺少{','.join(missing)}")
        record_id = str(record.get("id", ""))
        if not record_id:
            errors.append(f"{prefix}:证据编号为空")
        elif record_id in seen:
            errors.append(f"{prefix}:证据编号重复:{record_id}")
        seen.add(record_id)
        record_type = record.get("type")
        status = record.get("status")
        if record_type not in RECORD_TYPES:
            errors.append(f"{prefix}:类型不合法:{record_type}")
        if status not in RECORD_STATUSES:
            errors.append(f"{prefix}:状态不合法:{status}")
        if not _valid_date(record.get("retrieved_at")):
            errors.append(f"{prefix}:retrieved_at不是有效ISO日期")
        source_ids = record_source_ids(record)
        if record_type in {"fact", "pending"} and not source_ids:
            errors.append(f"{prefix}:事实或待核验项缺少来源")
        if sources:
            for source_id in source_ids:
                if source_id not in sources:
                    errors.append(f"{prefix}:引用未知来源:{source_id}")
                elif status == "verified" and sources[source_id].get("access_status") == "reference_only":
                    errors.append(f"{prefix}:已核验记录不得直接依赖仅登记、未取得原文的来源:{source_id}")
        elif strict and source_ids:
            errors.append(f"{prefix}:严格模式下来源必须引用sources登记编号")
        if record_type == "calculation":
            inputs = _as_list(record.get("inputs"))
            if not record.get("formula") or not inputs:
                errors.append(f"{prefix}:计算项缺少公式或输入")
            for input_id in inputs:
                target = records.get(input_id)
                if not target:
                    errors.append(f"{prefix}:引用未知计算输入:{input_id}")
                elif strict and target.get("status") != "verified":
                    if status == "verified":
                        errors.append(f"{prefix}:已核验计算不得引用未核验输入:{input_id}")
                    else:
                        warnings.append(f"{prefix}:复算使用未核验输入，仅可作为受限复现:{input_id}")
        if record_type == "inference":
            supports = _as_list(record.get("supports"))
            if not supports:
                errors.append(f"{prefix}:推断项缺少支撑证据")
            for support_id in supports:
                target = records.get(support_id)
                if not target:
                    errors.append(f"{prefix}:引用未知支撑证据:{support_id}")
                elif strict and (
                    target.get("status") != "verified" or target.get("type") not in {"fact", "calculation"}
                ):
                    errors.append(f"{prefix}:支撑证据不是已核验事实或计算:{support_id}")
            if strict and not record.get("limits"):
                errors.append(f"{prefix}:严格模式下推断项缺少limits边界")
        if status == "conflicted" and strict and not record.get("conflict_group"):
            errors.append(f"{prefix}:冲突记录缺少conflict_group")
        if strict and record_type == "fact":
            excerpt = record.get("evidence_excerpt")
            if not isinstance(excerpt, str) or _significant_length(excerpt) < 6:
                errors.append(f"{prefix}:事实缺少至少6个有效字符的证据摘录")
            else:
                claim_units = _lexical_units(str(record.get("claim", "")))
                excerpt_units = _lexical_units(excerpt)
                if claim_units and excerpt_units and not claim_units.intersection(excerpt_units):
                    warnings.append(f"{prefix}:主张与摘录缺少明显词面重合，需人工复核语义支持")
    return errors, warnings


def _validate_document(payload: dict[str, Any], strict: bool) -> tuple[list[str], list[str]]:
    document = payload.get("document")
    if document is None:
        return [], []
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(document, dict):
        return ["document必须是对象"], warnings
    blocks = document.get("blocks", [])
    if not isinstance(blocks, list) or not blocks:
        return ["document.blocks必须是非空数组"], warnings
    records = _record_map(payload)
    for index, block in enumerate(blocks, 1):
        prefix = f"文档块{index}"
        if not isinstance(block, dict) or not isinstance(block.get("text"), str) or not block.get("text").strip():
            errors.append(f"{prefix}:缺少正文text")
            continue
        claim_ids = _as_list(block.get("claim_ids"))
        if not claim_ids:
            errors.append(f"{prefix}:缺少claim_ids")
        for claim_id in claim_ids:
            if claim_id not in records:
                errors.append(f"{prefix}:引用未知证据:{claim_id}")
        if strict and re.search(r"https?://", block["text"]):
            errors.append(f"{prefix}:正文含裸URL，应由渲染器放入来源区")
        has_macos_home = "/" + "Users/" in block["text"]
        has_windows_drive = bool(re.search(r"[A-Za-z]:\\\\", block["text"]))
        if strict and (has_macos_home or has_windows_drive):
            errors.append(f"{prefix}:正文含内部绝对路径")
        market_share = payload.get("market_share")
        if strict and isinstance(market_share, dict) and isinstance(market_share.get("rank_claim"), dict):
            rank_text = str(market_share["rank_claim"].get("text", "")).strip()
            if rank_text and rank_text in block["text"]:
                rank_records = _as_list(market_share["rank_claim"].get("source_records"))
                if not rank_records or any(
                    item not in records or records[item].get("status") != "verified" for item in rank_records
                ):
                    errors.append(f"{prefix}:正文保留了无独立已核验来源的排名")
    return errors, warnings


def _decimal(value: Any) -> Decimal | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _six_same_status(value: Any) -> str:
    if value is True:
        return "same"
    if value is False:
        return "mismatch"
    return str(value)


def evaluate_market_share(payload: dict[str, Any]) -> dict[str, Any]:
    spec = payload.get("market_share")
    if not isinstance(spec, dict):
        return {
            "status": "fail",
            "grade": "D",
            "errors": ["缺少market_share测算合同"],
            "warnings": [],
            "use_restriction": "不得对外使用精确占有率或排名",
        }
    records = _record_map(payload)
    sources = _source_map(payload)
    errors: list[str] = []
    warnings: list[str] = []
    required_fields = {
        "product",
        "geography",
        "period",
        "metric",
        "unit",
        "tax_basis",
        "numerator_record",
        "base_market_record",
        "coefficients",
        "six_same",
    }
    missing = sorted(required_fields - set(spec))
    if missing:
        errors.append("市场占有率合同缺少:" + ",".join(missing))
    numerator_id = str(spec.get("numerator_record", ""))
    base_id = str(spec.get("base_market_record", ""))
    coefficient_ids = _as_list(spec.get("coefficients"))
    if not coefficient_ids:
        warnings.append("未使用拆分系数，按上位市场规模直接作为分母")

    source_lineage: dict[str, list[str]] = {}
    component_ids = [numerator_id, base_id, *coefficient_ids]
    for role, record_id in zip(
        ["numerator", "base_market", *[f"coefficient:{item}" for item in coefficient_ids]],
        component_ids,
    ):
        record = records.get(record_id)
        if not record:
            errors.append(f"{role}引用未知记录:{record_id}")
            continue
        if record.get("status") != "verified":
            errors.append(f"{role}记录未核验:{record_id}")
        direct_sources = record_source_ids(record)
        if not direct_sources:
            errors.append(f"{role}记录缺少独立来源:{record_id}")
        for source_id in direct_sources:
            if source_id not in sources:
                errors.append(f"{role}引用未知来源:{source_id}")
        source_lineage[role] = resolve_source_lineage(record_id, records)

    numerator = _decimal(records.get(numerator_id, {}).get("value"))
    base_market = _decimal(records.get(base_id, {}).get("value"))
    if numerator is None or numerator < 0:
        errors.append("分子必须是大于等于0的可复算数值")
    if base_market is None or base_market <= 0:
        errors.append("上位市场规模必须是大于0的可复算数值")
    market_unit = str(spec.get("unit", ""))
    if numerator_id in records and str(records[numerator_id].get("unit", "")) != market_unit:
        errors.append("分子单位与市场占有率合同不一致")
    if base_id in records and str(records[base_id].get("unit", "")) != market_unit:
        errors.append("上位市场规模单位与市场占有率合同不一致")

    coefficient_values: list[Decimal] = []
    estimated_coefficients = 0
    for coefficient_id in coefficient_ids:
        record = records.get(coefficient_id, {})
        value = _decimal(record.get("value"))
        if value is None or value <= 0 or value > 1:
            errors.append(f"拆分系数必须在0到1之间:{coefficient_id}")
            continue
        coefficient_values.append(value)
        if record.get("basis_type") == "enterprise_estimate":
            estimated_coefficients += 1

    six_same = spec.get("six_same", {})
    if not isinstance(six_same, dict):
        errors.append("six_same必须是对象")
        six_same = {}
    explanations = spec.get("six_same_explanations", {})
    unknown_count = 0
    for key in SIX_SAME_KEYS:
        status = _six_same_status(six_same.get(key, "unknown"))
        if status not in SIX_SAME_STATUSES:
            errors.append(f"六同状态不合法:{key}={status}")
        elif status == "mismatch":
            errors.append(f"六同不一致且未转换:{key}")
        elif status == "unknown":
            unknown_count += 1
        elif status == "explained":
            explanation = explanations.get(key, {}) if isinstance(explanations, dict) else {}
            if not isinstance(explanation, dict) or not str(explanation.get("text", "")).strip():
                errors.append(f"六同差异缺少转换说明:{key}")
                continue
            evidence_ids = _as_list(explanation.get("source_records"))
            if not evidence_ids:
                errors.append(f"六同转换说明缺少来源记录:{key}")
            for evidence_id in evidence_ids:
                evidence = records.get(evidence_id)
                if not evidence or evidence.get("status") != "verified":
                    errors.append(f"六同转换说明引用未核验记录:{key}:{evidence_id}")

    denominator: Decimal | None = None
    calculated_value: Decimal | None = None
    if base_market is not None and base_market > 0 and len(coefficient_values) == len(coefficient_ids):
        denominator = base_market
        for coefficient in coefficient_values:
            denominator *= coefficient
        if denominator <= 0:
            errors.append("最终分母必须大于0")
        elif numerator is not None and numerator >= 0:
            calculated_value = numerator / denominator * Decimal("100")

    claimed_value = _decimal(spec.get("claimed_value"))
    tolerance = _decimal(spec.get("tolerance_percentage_points", "0.01")) or Decimal("0.01")
    if claimed_value is not None and calculated_value is not None and abs(claimed_value - calculated_value) > tolerance:
        errors.append("申报值与复算值超出允许误差")

    assumption_risk = str(spec.get("assumption_risk", "low"))
    if assumption_risk not in {"low", "medium", "high"}:
        errors.append("assumption_risk只能是low、medium或high")

    if errors:
        grade = "D"
        restriction = "不得对外使用精确占有率或排名；先修正来源、公式或边界"
    elif assumption_risk == "high" or estimated_coefficients >= 3:
        grade = "C"
        restriction = "仅作内部参考；对外弱化精确值和排名表述"
    elif unknown_count or assumption_risk == "medium":
        grade = "B"
        restriction = "补充企业说明后使用精确值，未补齐前优先使用区间"
    else:
        grade = "A"
        restriction = "可按当前申报测算口径使用精确复算值"

    rank_claim = spec.get("rank_claim")
    rank_usable = False
    if rank_claim:
        if not isinstance(rank_claim, dict):
            warnings.append("排名主张格式不合法，不得对外使用")
        else:
            rank_records = _as_list(rank_claim.get("source_records"))
            rank_usable = bool(rank_records) and all(
                item in records and records[item].get("status") == "verified" for item in rank_records
            )
            if not rank_usable:
                warnings.append("排名缺少独立已核验来源，不得对外使用排名")
    if grade == "D":
        rank_usable = False

    def decimal_text(value: Decimal | None) -> str | None:
        if value is None:
            return None
        return format(value.quantize(Decimal("0.0001")), "f").rstrip("0").rstrip(".")

    return {
        "status": "pass" if grade != "D" else "fail",
        "grade": grade,
        "calculated_value_percent": decimal_text(calculated_value),
        "verified_value_percent": decimal_text(calculated_value) if grade != "D" else None,
        "reproduced_value_percent": decimal_text(calculated_value) if grade == "D" else None,
        "claimed_value_percent": decimal_text(claimed_value),
        "denominator": decimal_text(denominator),
        "source_lineage": source_lineage,
        "six_same": {key: _six_same_status(six_same.get(key, "unknown")) for key in SIX_SAME_KEYS},
        "estimated_coefficient_count": estimated_coefficients,
        "rank_usable": rank_usable,
        "errors": errors,
        "warnings": warnings,
        "use_restriction": restriction,
    }


def _restricted_market_share_disclosure_errors(payload: dict[str, Any]) -> list[str]:
    """Require an explicit, machine-checkable disclosure before rendering D-grade math."""
    document = payload.get("document")
    blocks = document.get("blocks", []) if isinstance(document, dict) else []
    text = "\n".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict)
    )
    errors: list[str] = []
    if not re.search(r"D\s*级", text, re.IGNORECASE):
        errors.append("D级受限报告必须在正文明确披露证据等级")
    precise_restriction = (
        "仅作内部参考" in text
        or (("不得对外使用" in text or "禁止对外使用" in text) and "精确" in text)
    )
    if not precise_restriction:
        errors.append("D级受限报告必须明确精确占有率不得对外使用")
    if "排名" not in text or not any(marker in text for marker in ("不作", "不得", "未核验", "不可", "不能")):
        errors.append("D级受限报告必须明确排名边界")
    return errors


def validate_payload(
    payload: dict[str, Any],
    *,
    strict_grounded: bool = False,
    require_market_share: bool = False,
    allow_restricted_market_share: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    source_errors, source_warnings = _validate_sources(payload, strict_grounded)
    record_errors, record_warnings = _validate_records(payload, strict_grounded)
    document_errors, document_warnings = _validate_document(payload, strict_grounded)
    errors.extend(source_errors + record_errors + document_errors)
    warnings.extend(source_warnings + record_warnings + document_warnings)
    market_share = None
    if require_market_share or "market_share" in payload:
        market_share = evaluate_market_share(payload)
        if (require_market_share or strict_grounded) and market_share.get("grade") == "D":
            if allow_restricted_market_share:
                errors.extend(
                    f"市场占有率:{item}"
                    for item in _restricted_market_share_disclosure_errors(payload)
                )
                warnings.extend(
                    f"市场占有率:受限复现:{item}"
                    for item in market_share.get("errors", [])
                )
            else:
                errors.extend(f"市场占有率:{item}" for item in market_share.get("errors", []))
        warnings.extend(f"市场占有率:{item}" for item in market_share.get("warnings", []))
    return {
        "status": "pass" if not errors else "fail",
        "schema_version": payload.get("schema_version", "legacy"),
        "records": len(payload.get("records", [])) if isinstance(payload.get("records", []), list) else 0,
        "sources": len(payload.get("sources", [])) if isinstance(payload.get("sources", []), list) else 0,
        "errors": errors,
        "warnings": warnings,
        "market_share": market_share,
    }


def _display_name(source: dict[str, Any]) -> str:
    kind = source.get("kind")
    if kind in LOCAL_SOURCE_KINDS:
        return Path(str(source.get("file_name", "未命名文件"))).name
    if kind == "enterprise_statement":
        return Path(str(source.get("file_name"))).name if source.get("file_name") else str(source.get("title"))
    return str(source.get("title") or source.get("name") or source.get("id"))


def _source_entry(
    number: int,
    source: dict[str, Any],
    sources: dict[str, dict[str, Any]] | None = None,
) -> str:
    kind = source.get("kind")
    name = _display_name(source)
    if source.get("access_status") == "reference_only":
        registered_via = str(source.get("registered_via") or "")
        via = (sources or {}).get(registered_via, {})
        via_name = _display_name(via) if via else registered_via or "未标明登记载体"
        suffix = f"（原件未取得；登记来源《{via_name}》）"
        if kind in WEB_SOURCE_KINDS:
            parts = [f"工作簿登记链接：{source.get('publisher')}", f"《{name}》", str(source.get("url"))]
            return f"[{number}] " + "；".join(parts) + f"（未访问，原文未取得；登记来源《{via_name}》）"
        if kind in LOCAL_SOURCE_KINDS:
            return f"[{number}] 工作簿登记文件名：{name}{suffix}"
        if kind == "enterprise_statement":
            return f"[{number}] 工作簿登记企业陈述：{name}{suffix}"
        return f"[{number}] 工作簿登记来源：{name}{suffix}"
    if kind == "knowledge_base":
        return f"[{number}] {name}"
    if kind == "user_file":
        return f"[{number}] 用户文件：{name}"
    if kind == "enterprise_statement":
        return f"[{number}] 企业陈述：{name}"
    if kind in WEB_SOURCE_KINDS:
        parts = [str(source.get("publisher")), f"《{name}》"]
        if source.get("published_at"):
            parts.append(str(source["published_at"]))
        parts.append(str(source.get("url")))
        parts.append(f"检索日期 {source.get('retrieved_at')}")
        return f"[{number}] " + "；".join(parts)
    return f"[{number}] {name}；检索日期 {source.get('retrieved_at')}"


def _inline_source(
    source: dict[str, Any],
    sources: dict[str, dict[str, Any]] | None = None,
) -> str:
    name = _display_name(source)
    if source.get("access_status") == "reference_only":
        registered_via = str(source.get("registered_via") or "")
        via = (sources or {}).get(registered_via, {})
        via_name = _display_name(via) if via else registered_via or "未标明登记载体"
        if source.get("kind") in WEB_SOURCE_KINDS:
            return f"登记链接《{name}》（未访问，原文未取得；见《{via_name}》）"
        return f"登记来源《{name}》（原件未取得；见《{via_name}》）"
    if source.get("kind") in WEB_SOURCE_KINDS:
        return f"[{name}]({source.get('url')})"
    if source.get("kind") == "enterprise_statement":
        return f"企业陈述《{name}》"
    return f"《{name}》"


def _document_source_order(payload: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    document = payload.get("document", {})
    blocks = document.get("blocks", []) if isinstance(document, dict) else []
    records = _record_map(payload)
    order: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for claim_id in _as_list(block.get("claim_ids")):
            order.extend(resolve_source_lineage(claim_id, records))
    return list(dict.fromkeys(order)), blocks


def load_delivery_config(path: Path = DELIVERY_CONFIG_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("profiles"), dict):
        raise ValueError("grounded-citations配置版本不受支持")
    return value


def _block_sources(
    block: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> list[str]:
    ordered: list[str] = []
    for claim_id in _as_list(block.get("claim_ids")):
        ordered.extend(resolve_source_lineage(claim_id, records))
    return list(dict.fromkeys(ordered))


def _numbered_blocks(
    payload: dict[str, Any],
    numbers: dict[str, int],
) -> list[dict[str, Any]]:
    _, blocks = _document_source_order(payload)
    records = _record_map(payload)
    result: list[dict[str, Any]] = []
    for block in blocks:
        source_ids = _block_sources(block, records)
        result.append(
            {
                "heading": block.get("heading"),
                "text": block["text"].strip(),
                "claim_ids": _as_list(block.get("claim_ids")),
                "source_ids": source_ids,
                "source_numbers": [numbers[source_id] for source_id in source_ids],
            }
        )
    return result


def _plain_primary(blocks: list[dict[str, Any]], *, markers: bool) -> str:
    lines: list[str] = []
    for block in blocks:
        if block.get("heading"):
            lines.extend([f"### {block['heading']}", ""])
        suffix = "".join(f"[{number}]" for number in block["source_numbers"]) if markers else ""
        lines.extend([f"{block['text']}{suffix}", ""])
    return "\n".join(lines).rstrip() + "\n"


def _source_memo(
    title: str,
    blocks: list[dict[str, Any]],
    source_entries: list[str],
) -> str:
    lines = [f"# {title}", "", "## 主张与来源映射", ""]
    for index, block in enumerate(blocks, 1):
        label = str(block.get("heading") or f"正文块{index}")
        markers = "".join(f"[{number}]" for number in block["source_numbers"])
        lines.append(f"- {label}：{block['text']} {markers}".rstrip())
    lines.extend(["", "## 来源登记", "", *source_entries, ""])
    return "\n".join(lines)


def render_profile_bundle(
    payload: dict[str, Any],
    *,
    profile: str,
    artifact: str,
    source_position: str = "inline",
    config_path: Path = DELIVERY_CONFIG_PATH,
) -> dict[str, Any]:
    """Render a host-neutral contract without imposing one page layout.

    Binary DOCX/PDF/XLSX/PPTX adapters consume this deterministic bundle.  The
    standard-native profile deliberately keeps all source sections and markers
    out of the standard body and emits a separate source memo.
    """
    validation = validate_payload(
        payload,
        strict_grounded=True,
        allow_restricted_market_share=True,
    )
    if validation["status"] != "pass":
        raise ValueError("严格溯源校验失败:" + " | ".join(validation["errors"]))
    config = load_delivery_config(config_path)
    profiles = config["profiles"]
    if profile not in profiles:
        raise ValueError(f"未知文档配置:{profile}")
    selected = dict(profiles[profile])
    if artifact not in selected.get("artifacts", []):
        override = config.get("artifact_profile_overrides", {}).get(artifact)
        if profile == "analysis-report" and override in profiles:
            profile = str(override)
            selected = dict(profiles[profile])
        else:
            raise ValueError(f"文档配置{profile}不支持{artifact}")

    if profile == "chat":
        text = render_document(payload, mode="chat", source_position=source_position)
        return {
            "schema_version": "grounded-render/v1",
            "profile": profile,
            "artifact": artifact,
            "source_placement": source_position,
            "primary": text,
            "sidecars": [],
        }

    sources = _source_map(payload)
    source_order, raw_blocks = _document_source_order(payload)
    numbers = {source_id: index for index, source_id in enumerate(source_order, 1)}
    blocks = _numbered_blocks(payload, numbers)
    source_entries = [_source_entry(numbers[source_id], sources[source_id], sources) for source_id in source_order]
    forbidden = set(selected.get("forbidden_primary_headings", []))
    conflicts = sorted(
        {
            str(block.get("heading"))
            for block in raw_blocks
            if block.get("heading") in forbidden
        }
    )
    if conflicts:
        raise ValueError("主文件包含文档配置禁止章节:" + ",".join(conflicts))

    placement = selected["source_placement"]
    primary = _plain_primary(blocks, markers=selected["body_citations"] == "numeric-markers")
    sidecars: list[dict[str, str]] = []
    if placement == "end-section":
        primary += f"\n## {selected['source_title']}\n\n" + "\n".join(source_entries) + "\n"
    elif placement in {"separate-source-memo", "template-aware"}:
        sidecars.append(
            {
                "kind": "source-memo",
                "suggested_suffix": "-来源说明",
                "content": _source_memo(selected["source_title"], blocks, source_entries),
            }
        )

    return {
        "schema_version": "grounded-render/v1",
        "profile": profile,
        "artifact": artifact,
        "body_citations": selected["body_citations"],
        "source_placement": placement,
        "primary": primary,
        "blocks": blocks,
        "source_entries": source_entries,
        "sidecars": sidecars,
    }


def render_document(payload: dict[str, Any], *, mode: str, source_position: str = "inline") -> str:
    if mode not in {"chat", "report"}:
        raise ValueError("mode只能是chat或report")
    if mode == "report" and source_position != "end":
        source_position = "end"
    if mode == "chat" and source_position not in {"inline", "before"}:
        raise ValueError("chat的source_position只能是inline或before")
    validation = validate_payload(
        payload,
        strict_grounded=True,
        allow_restricted_market_share=True,
    )
    if validation["status"] != "pass":
        raise ValueError("严格溯源校验失败:" + " | ".join(validation["errors"]))
    sources = _source_map(payload)
    source_order, blocks = _document_source_order(payload)
    missing_sources = [source_id for source_id in source_order if source_id not in sources]
    if missing_sources:
        raise ValueError("文档引用未知来源:" + ",".join(missing_sources))
    numbers = {source_id: index for index, source_id in enumerate(source_order, 1)}

    body_lines: list[str] = []
    for block in blocks:
        if block.get("heading"):
            body_lines.append(f"### {block['heading']}")
            body_lines.append("")
        block_sources: list[str] = []
        for claim_id in _as_list(block.get("claim_ids")):
            block_sources.extend(resolve_source_lineage(claim_id, _record_map(payload)))
        block_sources = list(dict.fromkeys(block_sources))
        text = block["text"].strip()
        if mode == "chat" and source_position == "inline":
            citations = "、".join(_inline_source(sources[source_id], sources) for source_id in block_sources)
            body_lines.append(f"{text}（来源：{citations}）")
        else:
            markers = "".join(f"[{numbers[source_id]}]" for source_id in block_sources)
            body_lines.append(f"{text}{markers}")
        body_lines.append("")
    body = "\n".join(body_lines).rstrip()
    source_lines = [_source_entry(numbers[source_id], sources[source_id], sources) for source_id in source_order]
    source_section = "\n".join(source_lines)
    if mode == "report":
        return f"{body}\n\n## 数据来源\n\n{source_section}\n"
    if source_position == "before":
        return f"### 数据来源范围\n\n{source_section}\n\n{body}\n"
    return body + "\n"


def _write_or_print(content: str, output: str | None) -> None:
    if output:
        Path(output).write_text(content, encoding="utf-8")
    else:
        print(content, end="" if content.endswith("\n") else "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _xml_root(archive: zipfile.ZipFile, member: str) -> ET.Element:
    try:
        return ET.fromstring(archive.read(member))
    except KeyError as exc:
        raise ValueError(f"OOXML缺少必要部件:{member}") from exc
    except ET.ParseError as exc:
        raise ValueError(f"OOXML部件不是有效XML:{member}") from exc


def _internal_path_findings(text: str) -> list[str]:
    findings: list[str] = []
    if re.search(r"(?:^|[\s>\"'])/[Uu]sers/[^\s<\"']+", text):
        findings.append("包含macOS内部绝对路径")
    if re.search(r"(?:^|[\s>\"'])[A-Za-z]:\\[^\s<\"']+", text):
        findings.append("包含Windows内部绝对路径")
    return findings


def _validate_docx(path: Path, profile: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks = ["docx-zip", "docx-structure", "docx-metadata", "docx-no-internal-path"]
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for required in ("[Content_Types].xml", "word/document.xml", "docProps/core.xml"):
            if required not in names:
                errors.append(f"DOCX缺少必要部件:{required}")
        if errors:
            return {"errors": errors, "warnings": warnings, "checks": checks}
        document = _xml_root(archive, "word/document.xml")
        core = _xml_root(archive, "docProps/core.xml")
        xml_text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.endswith((".xml", ".rels"))
        )
        errors.extend(_internal_path_findings(xml_text))

        paragraphs: list[tuple[str, str]] = []
        for paragraph in document.findall(f".//{{{WORD_NS}}}p"):
            text = "".join(node.text or "" for node in paragraph.findall(f".//{{{WORD_NS}}}t")).strip()
            style_node = paragraph.find(f"./{{{WORD_NS}}}pPr/{{{WORD_NS}}}pStyle")
            style = style_node.get(f"{{{WORD_NS}}}val", "") if style_node is not None else ""
            if text:
                paragraphs.append((text, style))
        combined = "\n".join(text for text, _ in paragraphs)
        if not combined:
            errors.append("DOCX正文为空")
        has_heading = any(
            style.casefold().startswith("heading") or style.startswith("标题")
            for _, style in paragraphs
        )
        if profile != "standard-native" and not has_heading:
            errors.append("DOCX未使用真实标题样式")

        if profile == "analysis-report":
            source_indexes = [
                index
                for index, (text, _) in enumerate(paragraphs)
                if text in {"数据来源", "Data Sources"}
            ]
            if not source_indexes:
                errors.append("分析报告末尾缺少数据来源章节")
            else:
                source_index = source_indexes[-1]
                if source_index < max(1, len(paragraphs) // 2) or source_index == len(paragraphs) - 1:
                    errors.append("数据来源章节不是有效的文末来源区")
            if not re.search(r"\[\d+\]", combined):
                errors.append("分析报告缺少正文或来源数字编号")
        elif profile == "standard-native":
            forbidden = {"数据来源", "参考资料", "标准数据来源说明"}
            if any(text in forbidden for text, _ in paragraphs):
                errors.append("标准正文不得内置报告式数据来源章节")

        for table_index, table in enumerate(document.findall(f".//{{{WORD_NS}}}tbl"), 1):
            first_row = table.find(f"./{{{WORD_NS}}}tr")
            header = (
                first_row.find(f"./{{{WORD_NS}}}trPr/{{{WORD_NS}}}tblHeader")
                if first_row is not None
                else None
            )
            if header is None:
                errors.append(f"DOCX表格{table_index}首行未声明重复表头")

        creator = (core.findtext(f"{{{DC_NS}}}creator") or "").strip()
        last_modified_by = (core.findtext(f"{{{CORE_NS}}}lastModifiedBy") or "").strip()
        created = (core.findtext(f"{{{DCTERMS_NS}}}created") or "").strip()
        modified = (core.findtext(f"{{{DCTERMS_NS}}}modified") or "").strip()
        metadata_text = "\n".join(
            (core.findtext(tag) or "").strip()
            for tag in (
                f"{{{DC_NS}}}title",
                f"{{{DC_NS}}}subject",
                f"{{{DC_NS}}}description",
                f"{{{CORE_NS}}}keywords",
                f"{{{CORE_NS}}}category",
            )
        )
        if not creator or creator.casefold() in {"python-docx", "python"}:
            errors.append("DOCX作者元数据缺失或暴露生成库")
        if not last_modified_by or last_modified_by.casefold() in {"python-docx", "python"}:
            errors.append("DOCX最后修改者元数据缺失或暴露生成库")
        if not created or created.startswith("2013-12-23"):
            errors.append("DOCX创建时间缺失或仍为模板默认时间")
        if not modified or modified.startswith("2013-12-23"):
            errors.append("DOCX修改时间缺失或仍为模板默认时间")
        elif _valid_date(created) and _valid_date(modified):
            created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            modified_at = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            if modified_at < created_at:
                errors.append("DOCX修改时间早于创建时间")
        if re.search(r"(?:generated\s+by|python-docx)", metadata_text, flags=re.IGNORECASE):
            errors.append("DOCX核心元数据暴露文档生成器")
        east_asia_fonts = [
            node.get(f"{{{WORD_NS}}}eastAsia", "").strip()
            for name in names
            if name.startswith("word/") and name.endswith(".xml")
            for node in _xml_root(archive, name).findall(f".//{{{WORD_NS}}}rFonts")
        ]
        if not any(east_asia_fonts):
            errors.append("DOCX未声明东亚字体")
    return {"errors": errors, "warnings": warnings, "checks": checks}


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _xml_root(archive, "xl/sharedStrings.xml")
    return [
        "".join(node.text or "" for node in item.findall(f".//{{{SPREADSHEET_NS}}}t"))
        for item in root.findall(f"{{{SPREADSHEET_NS}}}si")
    ]


def _xlsx_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = _xml_root(archive, "xl/workbook.xml")
    relationships = _xml_root(archive, "xl/_rels/workbook.xml.rels")
    targets = {
        rel.get("Id", ""): rel.get("Target", "")
        for rel in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    }
    result: list[tuple[str, str]] = []
    for sheet in workbook.findall(f".//{{{SPREADSHEET_NS}}}sheet"):
        rel_id = sheet.get(f"{{{OOXML_REL_NS}}}id", "")
        target = targets.get(rel_id, "")
        member = posixpath.normpath(posixpath.join("xl", target.lstrip("/")))
        if target.startswith("/xl/"):
            member = target.lstrip("/")
        result.append((sheet.get("name", ""), member))
    return result


def dump_xlsx(path: Path) -> dict[str, Any]:
    """Read ordinary XLSX values and formulas without installing third-party packages."""
    with zipfile.ZipFile(path) as archive:
        shared = _xlsx_shared_strings(archive)
        sheets: list[dict[str, Any]] = []
        for name, member in _xlsx_sheets(archive):
            root = _xml_root(archive, member)
            rows: list[list[dict[str, Any]]] = []
            for row in root.findall(f".//{{{SPREADSHEET_NS}}}row"):
                cells: list[dict[str, Any]] = []
                for cell in row.findall(f"{{{SPREADSHEET_NS}}}c"):
                    cell_type = cell.get("t", "")
                    raw = cell.findtext(f"{{{SPREADSHEET_NS}}}v")
                    inline = "".join(
                        node.text or ""
                        for node in cell.findall(f".//{{{SPREADSHEET_NS}}}is/{{{SPREADSHEET_NS}}}t")
                    )
                    value: Any = inline if cell_type == "inlineStr" else raw
                    if cell_type == "s" and raw is not None:
                        try:
                            value = shared[int(raw)]
                        except (IndexError, ValueError):
                            value = raw
                    cells.append(
                        {
                            "cell": cell.get("r", ""),
                            "value": value,
                            "formula": cell.findtext(f"{{{SPREADSHEET_NS}}}f"),
                        }
                    )
                if cells:
                    rows.append(cells)
            sheets.append({"name": name, "rows": rows})
    return {"schema_version": "xlsx-dump/v1", "file_name": path.name, "sheets": sheets}


def _validate_xlsx(path: Path, profile: str) -> dict[str, Any]:
    errors: list[str] = []
    checks = ["xlsx-zip", "xlsx-sheet-order", "xlsx-no-internal-path"]
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for required in ("[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"):
            if required not in names:
                errors.append(f"XLSX缺少必要部件:{required}")
        if not errors:
            sheets = _xlsx_sheets(archive)
            if profile == "spreadsheet-native" and (not sheets or sheets[-1][0] != "数据来源"):
                errors.append("工作簿最后一个工作表必须为数据来源")
            xml_text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.endswith((".xml", ".rels"))
            )
            errors.extend(_internal_path_findings(xml_text))
    return {"errors": errors, "warnings": [], "checks": checks}


def _validate_pptx(path: Path, profile: str) -> dict[str, Any]:
    errors: list[str] = []
    checks = ["pptx-zip", "pptx-slide-order", "pptx-no-internal-path"]
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        slides = sorted(
            (name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=lambda name: int(re.search(r"\d+", Path(name).stem).group()),
        )
        if not slides:
            errors.append("PPTX不含幻灯片")
        else:
            last = _xml_root(archive, slides[-1])
            last_text = "".join(node.text or "" for node in last.findall(f".//{{{DRAWING_NS}}}t"))
            if profile == "presentation-native" and "数据来源" not in last_text:
                errors.append("演示文稿最后一页必须为数据来源")
        xml_text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.endswith((".xml", ".rels"))
        )
        errors.extend(_internal_path_findings(xml_text))
    return {"errors": errors, "warnings": [], "checks": checks}


def validate_artifact(path: Path, profile: str) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "fail", "errors": ["交付文件不存在"], "warnings": [], "checks": []}
    suffix = path.suffix.casefold().lstrip(".")
    try:
        if suffix == "docx":
            result = _validate_docx(path, profile)
        elif suffix == "xlsx":
            result = _validate_xlsx(path, profile)
        elif suffix == "pptx":
            result = _validate_pptx(path, profile)
        elif suffix == "pdf":
            data = path.read_bytes()
            errors = [] if data.startswith(b"%PDF-") and len(data) >= 1024 else ["PDF文件头或大小异常"]
            result = {"errors": errors, "warnings": [], "checks": ["pdf-signature", "pdf-nonempty"]}
        else:
            result = {"errors": [f"不支持的交付文件类型:{suffix}"], "warnings": [], "checks": []}
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        result = {"errors": [str(exc)], "warnings": [], "checks": []}
    result["status"] = "pass" if not result["errors"] else "fail"
    result["artifact_type"] = suffix
    return result


def _artifact_text_units(path: Path) -> list[str]:
    suffix = path.suffix.casefold().lstrip(".")
    if suffix == "docx":
        with zipfile.ZipFile(path) as archive:
            document = _xml_root(archive, "word/document.xml")
            return [
                "".join(node.text or "" for node in paragraph.findall(f".//{{{WORD_NS}}}t")).strip()
                for paragraph in document.findall(f".//{{{WORD_NS}}}p")
                if "".join(node.text or "" for node in paragraph.findall(f".//{{{WORD_NS}}}t")).strip()
            ]
    if suffix == "xlsx":
        workbook = dump_xlsx(path)
        return [
            " ".join(str(cell.get("value") or "") for cell in row).strip()
            for sheet in workbook["sheets"]
            for row in sheet["rows"]
            if " ".join(str(cell.get("value") or "") for cell in row).strip()
        ]
    if suffix == "pptx":
        with zipfile.ZipFile(path) as archive:
            slides = sorted(
                (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                key=lambda name: int(re.search(r"\d+", Path(name).stem).group()),
            )
            return [
                " ".join(node.text or "" for node in _xml_root(archive, slide).findall(f".//{{{DRAWING_NS}}}t")).strip()
                for slide in slides
            ]
    return []


def validate_source_disclosure(
    payload: dict[str, Any],
    artifact_path: Path,
    profile: str,
) -> dict[str, Any]:
    """Cross-check source access semantics against the delivered artifact.

    Structure validation alone cannot distinguish an actually opened source
    from a filename or URL merely copied out of another workbook.  This gate
    requires the latter to remain visibly qualified in the final artifact.
    """
    errors: list[str] = []
    warnings: list[str] = []
    checks = ["source-disclosure-access-status"]
    reference_sources = {
        source_id: source
        for source_id, source in _source_map(payload).items()
        if source.get("access_status") == "reference_only"
    }
    if not reference_sources:
        return {"errors": errors, "warnings": warnings, "checks": checks}
    units = _artifact_text_units(artifact_path)
    if not units:
        warnings.append(f"{artifact_path.suffix.casefold()}暂不能执行来源访问状态文本交叉校验")
        return {"errors": errors, "warnings": warnings, "checks": checks}
    source_order, _ = _document_source_order(payload)
    sources = _source_map(payload)
    for source_id in source_order:
        source = reference_sources.get(source_id)
        if not source:
            continue
        name = _display_name(source)
        url = str(source.get("url") or "")
        candidates = [unit for unit in units if name in unit or (url and url in unit)]
        if not candidates:
            errors.append(f"仅登记来源未在成品来源区披露:{source_id}:{name}")
            continue
        disclosure = " ".join(candidates)
        registered_via = str(source.get("registered_via") or "")
        via_name = _display_name(sources.get(registered_via, {})) if registered_via else ""
        if "工作簿登记" not in disclosure:
            errors.append(f"仅登记来源未标明工作簿登记属性:{source_id}")
        if via_name and via_name not in disclosure:
            errors.append(f"仅登记来源未披露登记载体:{source_id}:{via_name}")
        if source.get("kind") in WEB_SOURCE_KINDS:
            if "未访问" not in disclosure or "原文未取得" not in disclosure:
                errors.append(f"仅登记网页来源未标明未访问与原文未取得:{source_id}")
            if "检索日期" in disclosure:
                errors.append(f"仅登记网页来源不得声称检索日期:{source_id}")
        elif "原件未取得" not in disclosure:
            errors.append(f"仅登记本地或陈述来源未标明原件未取得:{source_id}")
    return {"errors": errors, "warnings": warnings, "checks": checks}


def _default_state_root() -> Path:
    explicit = os.environ.get("JIAOTANG_BEHAVIOR_STATE_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    plugin_data = os.environ.get("CODEBUDDY_PLUGIN_DATA", "").strip()
    if plugin_data and not plugin_data.startswith("${"):
        return Path(plugin_data).expanduser().resolve() / "behavior-hook"
    windows_root = Path.home() / ".workbuddy" / "state" / "jiaotang-behavior"
    if os.name == "nt" or windows_root.exists():
        return windows_root
    plugin_root = os.environ.get("CODEBUDDY_PLUGIN_ROOT", "").strip()
    if plugin_root and not plugin_root.startswith("${"):
        return Path(plugin_root).expanduser().resolve() / ".behavior-data"
    raise ValueError("无法定位WorkBuddy行为状态目录，请传入--state-root")


def write_delivery_receipt(
    ledger_path: Path,
    artifact_path: Path,
    *,
    profile: str,
    source_memo_path: Path | None = None,
    state_root: Path | None = None,
    visual_status: str = "pending-device-acceptance",
) -> dict[str, Any]:
    payload = load_payload(ledger_path)
    ledger_validation = validate_payload(
        payload,
        strict_grounded=True,
        allow_restricted_market_share=True,
    )
    artifact_validation = validate_artifact(artifact_path, profile)
    disclosure_validation = (
        {"errors": [], "warnings": [], "checks": []}
        if profile == "standard-native"
        else validate_source_disclosure(payload, artifact_path, profile)
    )
    sidecars: list[dict[str, str]] = []
    sidecar_errors: list[str] = []
    sidecar_warnings: list[str] = []
    sidecar_checks: list[str] = []
    if profile == "standard-native":
        if source_memo_path is None:
            sidecar_errors.append("标准正式交付缺少独立《标准数据来源说明》")
        else:
            memo_validation = validate_artifact(source_memo_path, "source-memo")
            sidecar_errors.extend(memo_validation["errors"])
            sidecar_warnings.extend(memo_validation["warnings"])
            sidecar_checks.extend(f"source-memo:{item}" for item in memo_validation["checks"])
            memo_disclosure = validate_source_disclosure(payload, source_memo_path, "source-memo")
            sidecar_errors.extend(memo_disclosure["errors"])
            sidecar_warnings.extend(memo_disclosure["warnings"])
            sidecar_checks.extend(f"source-memo:{item}" for item in memo_disclosure["checks"])
            if source_memo_path.is_file():
                sidecars.append(
                    {
                        "name": source_memo_path.name,
                        "type": source_memo_path.suffix.casefold().lstrip("."),
                        "path": str(source_memo_path.resolve()),
                        "sha256": sha256_file(source_memo_path),
                    }
                )
    root = (state_root or _default_state_root()).expanduser().resolve()
    current = json.loads((root / "current-turn.json").read_text(encoding="utf-8"))
    turn_id = str(current.get("turn_id", "")).strip()
    if not turn_id:
        raise ValueError("current-turn.json缺少turn_id")
    errors = [
        *ledger_validation["errors"],
        *artifact_validation["errors"],
        *disclosure_validation["errors"],
        *sidecar_errors,
    ]
    artifact_hash = sha256_file(artifact_path)
    receipt = {
        "schema_version": 1,
        "validator_id": VALIDATOR_ID,
        "status": "pass" if not errors else "fail",
        "turn_id": turn_id,
        "profile": profile,
        "artifact": {
            "name": artifact_path.name,
            "type": artifact_validation["artifact_type"],
            "path": str(artifact_path.resolve()),
            "sha256": artifact_hash,
        },
        "sidecars": sidecars,
        "ledger": {
            "name": ledger_path.name,
            "sha256": sha256_file(ledger_path),
            "schema_version": ledger_validation["schema_version"],
        },
        "checks": [*artifact_validation["checks"], *disclosure_validation["checks"], *sidecar_checks],
        "errors": errors,
        "warnings": [
            *ledger_validation["warnings"],
            *artifact_validation["warnings"],
            *disclosure_validation["warnings"],
            *sidecar_warnings,
        ],
        "visual_status": visual_status,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    receipt_dir = root / "validator-receipts" / turn_id
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"grounded-delivery-v1-{artifact_hash[:16]}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**receipt, "receipt_path": str(receipt_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Grounded证据台账、来源渲染与市场占有率复核")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="校验证据台账")
    validate_parser.add_argument("ledger")
    validate_parser.add_argument("--strict-grounded", action="store_true")
    validate_parser.add_argument("--market-share", action="store_true")
    validate_parser.add_argument("--allow-restricted-market-share", action="store_true")

    render_parser = subparsers.add_parser("render", help="渲染对话或报告来源")
    render_parser.add_argument("ledger")
    render_parser.add_argument("--mode", choices=("chat", "report"), required=True)
    render_parser.add_argument("--source-position", choices=("inline", "before", "end"), default="inline")
    render_parser.add_argument("--output")

    market_parser = subparsers.add_parser("market-share", help="复算并分级市场占有率")
    market_parser.add_argument("ledger")

    profile_parser = subparsers.add_parser("render-profile", help="按文档配置渲染宿主无关合同")
    profile_parser.add_argument("ledger")
    profile_parser.add_argument("--profile", required=True)
    profile_parser.add_argument("--artifact", required=True)
    profile_parser.add_argument("--source-position", choices=("inline", "before"), default="inline")
    profile_parser.add_argument("--output")

    xlsx_parser = subparsers.add_parser("xlsx-dump", help="无第三方依赖读取XLSX单元格与公式")
    xlsx_parser.add_argument("workbook")
    xlsx_parser.add_argument("--output")

    delivery_parser = subparsers.add_parser("validate-delivery", help="校验台账与交付文件并写入当前turn回执")
    delivery_parser.add_argument("ledger")
    delivery_parser.add_argument("artifact")
    delivery_parser.add_argument("--profile", required=True)
    delivery_parser.add_argument("--source-memo")
    delivery_parser.add_argument("--state-root")
    delivery_parser.add_argument(
        "--visual-status",
        choices=("passed-host-render", "pending-device-acceptance", "not-applicable"),
        default="pending-device-acceptance",
    )

    args = parser.parse_args()
    try:
        if args.command == "xlsx-dump":
            result = dump_xlsx(Path(args.workbook))
            _write_or_print(json.dumps(result, ensure_ascii=False, indent=2) + "\n", args.output)
            return 0
        if args.command == "validate-delivery":
            result = write_delivery_receipt(
                Path(args.ledger),
                Path(args.artifact),
                profile=args.profile,
                source_memo_path=Path(args.source_memo) if args.source_memo else None,
                state_root=Path(args.state_root) if args.state_root else None,
                visual_status=args.visual_status,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "pass" else 2
        payload = load_payload(Path(args.ledger))
        if args.command == "validate":
            result = validate_payload(
                payload,
                strict_grounded=args.strict_grounded,
                require_market_share=args.market_share,
                allow_restricted_market_share=args.allow_restricted_market_share,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "pass" else 2
        if args.command == "market-share":
            result = evaluate_market_share(payload)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "pass" else 2
        if args.command == "render-profile":
            result = render_profile_bundle(
                payload,
                profile=args.profile,
                artifact=args.artifact,
                source_position=args.source_position,
            )
            _write_or_print(json.dumps(result, ensure_ascii=False, indent=2) + "\n", args.output)
            return 0
        rendered = render_document(payload, mode=args.mode, source_position=args.source_position)
        _write_or_print(rendered, args.output)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

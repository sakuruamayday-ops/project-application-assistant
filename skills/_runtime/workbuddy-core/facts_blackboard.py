#!/usr/bin/env python3
"""Subject-isolated workspace blackboard (.facts/<subject>.facts.json) with data lineage."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "workbuddy-facts-blackboard/v1"
VALID_ORIGINS = {"enterprise_source", "ai_design_target", "public_registry", "mcp_verified"}
VALID_BUSINESS_TYPES = {"equipment_or_mold_maker", "product_or_material_maker", "ambiguous"}


def normalize_company_name(name: str) -> str:
    compact = re.sub(r"[\s\u3000（）()·\-_]+", "", (name or "").strip())
    return compact


def subject_filename(company_name: str, credit_code: str = "") -> str:
    clean_name = re.sub(r"[^\w\u4e00-\u9fff]+", "", (company_name or "").strip())[:16] or "enterprise"
    code = re.sub(r"[^A-Za-z0-9]", "", (credit_code or "").strip()).upper()
    if len(code) >= 6:
        suffix = code[-6:]
    else:
        digest = hashlib.sha256(normalize_company_name(company_name).encode("utf-8")).hexdigest()[:6]
        suffix = digest
    return f"{clean_name}_{suffix}.facts.json"


def blackboard_path(workspace: Path, company_name: str, credit_code: str = "") -> Path:
    return workspace / ".facts" / subject_filename(company_name, credit_code)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def empty_blackboard(company_name: str, credit_code: str = "") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "company_name": company_name.strip(),
        "credit_code": credit_code.strip().upper(),
        "updated_at": _now_iso(),
        "lockedProduct": {
            "rawAnchor": "",
            "formalDeclarationName": "",
            "businessType": "ambiguous",
            "sixBasesAlignment": "",
            "unpatentedProcessTags": [],
            "revision": 0,
        },
        "patentTierReport": {
            "direct_support": [],
            "production_support": [],
            "weak_or_unrelated": [],
        },
        "estimatedMetrics": [],
        "financialFacts": {},
        "checkupSnapshots": {},
    }


def _subject_matches(payload: dict[str, Any], company_name: str, credit_code: str = "") -> bool:
    stored_code = re.sub(r"[^A-Za-z0-9]", "", str(payload.get("credit_code", ""))).upper()
    target_code = re.sub(r"[^A-Za-z0-9]", "", (credit_code or "")).upper()
    if stored_code and target_code:
        return stored_code == target_code
    stored_name = normalize_company_name(str(payload.get("company_name", "")))
    target_name = normalize_company_name(company_name)
    return bool(stored_name and target_name and stored_name == target_name)


def load_blackboard(
    workspace: Path,
    company_name: str,
    credit_code: str = "",
    *,
    strict: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Load subject-matched blackboard. Never cross-contaminates across different companies."""
    warnings: list[str] = []
    facts_dir = workspace / ".facts"
    target = blackboard_path(workspace, company_name, credit_code)
    candidates: list[Path] = []
    if target.is_file():
        candidates.append(target)
    elif facts_dir.is_dir():
        candidates.extend(sorted(facts_dir.glob("*.facts.json")))

    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"黑板文件读取失败已跳过：{candidate.name} ({exc})")
            continue
        if not isinstance(payload, dict):
            continue
        if _subject_matches(payload, company_name, credit_code):
            return payload, warnings
        if candidate == target:
            msg = (
                f"主体不匹配，已拒绝加载防串户：期望「{company_name}」，"
                f"文件记录为「{payload.get('company_name', '')}」"
            )
            if strict:
                raise ValueError(msg)
            warnings.append(msg)

    # Backward-compatible read of legacy enterprise-financial-facts/v1 if present in workspace.
    for legacy_name in ("enterprise-financial-facts.json", "financial-facts.json"):
        legacy = workspace / legacy_name
        if not legacy.is_file():
            continue
        try:
            legacy_data = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(legacy_data, dict):
            legacy_company = str(legacy_data.get("company_name") or legacy_data.get("enterprise_name") or "")
            if legacy_company and normalize_company_name(legacy_company) == normalize_company_name(company_name):
                bb = empty_blackboard(company_name, credit_code)
                bb["financialFacts"] = {
                    "origin": "enterprise_source",
                    "legacy_import": legacy_name,
                    "data": legacy_data,
                }
                warnings.append(f"已向下兼容导入旧财务底稿：{legacy_name}")
                return bb, warnings

    return None, warnings


def save_blackboard(
    workspace: Path,
    payload: dict[str, Any],
    *,
    strict: bool = False,
) -> Path:
    company_name = str(payload.get("company_name", "")).strip()
    if not company_name:
        raise ValueError("company_name 不能为空，必须显式绑定企业主体")
    credit_code = str(payload.get("credit_code", "")).strip().upper()
    lp = payload.get("lockedProduct")
    if isinstance(lp, dict):
        btype = lp.get("businessType", "ambiguous")
        if strict and btype not in VALID_BUSINESS_TYPES:
            raise ValueError(f"无效的 businessType：{btype}")
    for metric in payload.get("estimatedMetrics", []):
        if isinstance(metric, dict):
            origin = metric.setdefault("origin", "ai_design_target")
            if strict and origin not in VALID_ORIGINS:
                raise ValueError(f"无效的指标来源血统：{origin}")
            metric.setdefault("status", "pending")

    payload["schema_version"] = SCHEMA_VERSION
    payload["company_name"] = company_name
    payload["credit_code"] = credit_code
    payload["updated_at"] = _now_iso()

    target = blackboard_path(workspace, company_name, credit_code)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def reconcile_text_against_estimates(
    blackboard: dict[str, Any],
    latest_text: str,
) -> dict[str, Any]:
    """Check latest draft/DOCX text against AI design targets to auto-resolve edited metrics
    and prevent AI self-certification pollution during checkups."""
    compact_text = re.sub(r"\s+", "", latest_text or "")
    pending: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    for item in blackboard.get("estimatedMetrics", []):
        if not isinstance(item, dict):
            continue
        if item.get("origin", "ai_design_target") != "ai_design_target":
            continue
        snippet = re.sub(r"\s+", "", str(item.get("snippet", "")))
        suggested = re.sub(r"\s+", "", str(item.get("suggestedValue", "")))
        still_present = False
        if snippet and snippet in compact_text:
            still_present = True
        elif suggested and suggested in compact_text:
            still_present = True

        entry = dict(item)
        if still_present:
            entry["status"] = "pending"
            entry["checkup_note"] = "该数值源自初稿行业设计目标，尚未见企业实测原件，提交前请核对工艺单或检测报告。"
            pending.append(entry)
        else:
            entry["status"] = "resolved"
            resolved.append(entry)
    return {
        "pending_count": len(pending),
        "resolved_count": len(resolved),
        "pending_estimates": pending,
        "resolved_estimates": resolved,
    }


def validate_blackboard(payload: dict[str, Any]) -> list[str]:
    """Validate that a blackboard dictionary strictly conforms to workbuddy-facts-blackboard/v1."""
    errors: list[str] = []
    required_keys = (
        "schema_version",
        "company_name",
        "credit_code",
        "updated_at",
        "lockedProduct",
        "patentTierReport",
        "estimatedMetrics",
        "financialFacts",
        "checkupSnapshots",
    )
    if not isinstance(payload, dict):
        return ["黑板根节点必须为 JSON 对象"]
    for key in required_keys:
        if key not in payload:
            errors.append(f"缺少必需顶层字段：{key}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}，实际为 {payload.get('schema_version')!r}")
    if not str(payload.get("company_name", "")).strip():
        errors.append("company_name 不能为空")
    lp = payload.get("lockedProduct")
    if isinstance(lp, dict):
        btype = lp.get("businessType", "ambiguous")
        if btype not in VALID_BUSINESS_TYPES:
            errors.append(f"无效的 businessType：{btype}")
    else:
        errors.append("lockedProduct 必须为对象")
    for idx, metric in enumerate(payload.get("estimatedMetrics", [])):
        if not isinstance(metric, dict):
            errors.append(f"estimatedMetrics[{idx}] 必须为对象")
            continue
        origin = metric.get("origin", "ai_design_target")
        if origin not in VALID_ORIGINS:
            errors.append(f"estimatedMetrics[{idx}] 无效来源血统：{origin}")
    return errors


def upsert_blackboard(
    workspace: Path,
    company_name: str,
    credit_code: str = "",
    *,
    financial_facts: dict[str, Any] | None = None,
    locked_product: dict[str, Any] | None = None,
    patent_tier_report: dict[str, Any] | None = None,
    estimated_metrics: list[dict[str, Any]] | None = None,
    snapshot_key: str = "",
    snapshot_data: dict[str, Any] | None = None,
    strict: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """Safely create or merge fields into a subject-matched blackboard using the canonical v1 schema."""
    existing, _ = load_blackboard(workspace, company_name, credit_code, strict=strict)
    bb = existing if existing is not None else empty_blackboard(company_name, credit_code)
    if credit_code and not bb.get("credit_code"):
        bb["credit_code"] = credit_code.strip().upper()
    if isinstance(financial_facts, dict):
        bb.setdefault("financialFacts", {}).update(financial_facts)
    if isinstance(locked_product, dict):
        lp = bb.setdefault("lockedProduct", empty_blackboard(company_name, credit_code)["lockedProduct"])
        lp.update(locked_product)
        lp["revision"] = int(lp.get("revision", 0)) + 1
    if isinstance(patent_tier_report, dict):
        ptr = bb.setdefault("patentTierReport", {"direct_support": [], "production_support": [], "weak_or_unrelated": []})
        for tier_key in ("direct_support", "production_support", "weak_or_unrelated"):
            if tier_key in patent_tier_report and isinstance(patent_tier_report[tier_key], list):
                ptr[tier_key] = patent_tier_report[tier_key]
    if isinstance(estimated_metrics, list):
        existing_list = bb.setdefault("estimatedMetrics", [])
        for item in estimated_metrics:
            if isinstance(item, dict):
                item.setdefault("origin", "ai_design_target")
                item.setdefault("status", "pending")
                existing_list.append(item)
    if snapshot_key and isinstance(snapshot_data, dict):
        bb.setdefault("checkupSnapshots", {})[snapshot_key] = snapshot_data
    path = save_blackboard(workspace, bb, strict=strict)
    return path, bb


def main() -> int:
    parser = argparse.ArgumentParser(description="主体隔离企业事实黑板工具 (.facts/<主体>.facts.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="初始化企业事实黑板")
    p_init.add_argument("--workspace", type=Path, default=Path("."))
    p_init.add_argument("--company", required=True)
    p_init.add_argument("--credit-code", default="")

    p_upsert = sub.add_parser("upsert", help="按标准 v1 Schema 安全合并写入企业事实黑板（防串户与防字段漂移）")
    p_upsert.add_argument("--workspace", type=Path, default=Path("."))
    p_upsert.add_argument("--company", required=True)
    p_upsert.add_argument("--credit-code", default="")
    p_upsert.add_argument("--financials-json", default="", help="JSON 对象字符串，合并到 financialFacts")
    p_upsert.add_argument("--product-json", default="", help="JSON 对象字符串，更新 lockedProduct")
    p_upsert.add_argument("--patents-json", default="", help="JSON 对象字符串，更新 patentTierReport")
    p_upsert.add_argument("--estimated-metrics-json", default="", help="JSON 数组字符串，追加到 estimatedMetrics")
    p_upsert.add_argument("--snapshot-key", default="", help="体检或核验快照键名（如 hightech_checkup / sme_checkup）")
    p_upsert.add_argument("--snapshot-json", default="", help="JSON 对象字符串，写入 checkupSnapshots[snapshot_key]")

    p_read = sub.add_parser("read", help="按主体安全读取黑板（防串户）")
    p_read.add_argument("--workspace", type=Path, default=Path("."))
    p_read.add_argument("--company", required=True)
    p_read.add_argument("--credit-code", default="")
    p_read.add_argument("--strict", action="store_true")

    p_reconcile = sub.add_parser("reconcile", help="用最新正文回查估算指标并自动销项")
    p_reconcile.add_argument("--workspace", type=Path, default=Path("."))
    p_reconcile.add_argument("--company", required=True)
    p_reconcile.add_argument("--credit-code", default="")
    p_reconcile.add_argument("--text-file", type=Path, required=True)

    p_val = sub.add_parser("validate", help="校验黑板 JSON 是否严格符合 workbuddy-facts-blackboard/v1 规范")
    p_val.add_argument("file", type=Path)

    args = parser.parse_args()
    if args.command == "init":
        bb = empty_blackboard(args.company, args.credit_code)
        path = save_blackboard(args.workspace, bb, strict=True)
        print(json.dumps({"status": "ok", "path": str(path), "company_name": bb["company_name"]}, ensure_ascii=False))
        return 0
    if args.command == "upsert":
        path, bb = upsert_blackboard(
            args.workspace,
            args.company,
            args.credit_code,
            financial_facts=json.loads(args.financials_json) if args.financials_json else None,
            locked_product=json.loads(args.product_json) if args.product_json else None,
            patent_tier_report=json.loads(args.patents_json) if args.patents_json else None,
            estimated_metrics=json.loads(args.estimated_metrics_json) if args.estimated_metrics_json else None,
            snapshot_key=args.snapshot_key,
            snapshot_data=json.loads(args.snapshot_json) if args.snapshot_json else None,
            strict=True,
        )
        print(json.dumps({"status": "ok", "path": str(path), "schema_version": bb["schema_version"], "company_name": bb["company_name"]}, ensure_ascii=False))
        return 0
    if args.command == "read":
        bb, warnings = load_blackboard(args.workspace, args.company, args.credit_code, strict=args.strict)
        print(json.dumps({"found": bb is not None, "warnings": warnings, "blackboard": bb}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "reconcile":
        bb, warnings = load_blackboard(args.workspace, args.company, args.credit_code)
        if bb is None:
            print(json.dumps({"found": False, "warnings": warnings, "pending_count": 0, "resolved_count": 0}, ensure_ascii=False))
            return 0
        latest = args.text_file.read_text(encoding="utf-8")
        result = reconcile_text_against_estimates(bb, latest)
        print(json.dumps({"found": True, "warnings": warnings, **result}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        try:
            payload = json.loads(args.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"valid": False, "errors": [f"JSON 读取失败：{exc}"]}, ensure_ascii=False))
            return 1
        errs = validate_blackboard(payload)
        print(json.dumps({"valid": len(errs) == 0, "errors": errs}, ensure_ascii=False))
        return 0 if not errs else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

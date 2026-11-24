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


def main() -> int:
    parser = argparse.ArgumentParser(description="主体隔离企业事实黑板工具 (.facts/<主体>.facts.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="初始化企业事实黑板")
    p_init.add_argument("--workspace", type=Path, default=Path("."))
    p_init.add_argument("--company", required=True)
    p_init.add_argument("--credit-code", default="")

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

    args = parser.parse_args()
    if args.command == "init":
        bb = empty_blackboard(args.company, args.credit_code)
        path = save_blackboard(args.workspace, bb, strict=True)
        print(json.dumps({"status": "ok", "path": str(path), "company_name": bb["company_name"]}, ensure_ascii=False))
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

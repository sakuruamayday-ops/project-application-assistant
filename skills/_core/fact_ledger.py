#!/usr/bin/env python3
"""
Unified Subject-Isolated Fact Blackboard & Deterministic Financial/IP Verifier.
Backward-compatible with workbuddy-facts-blackboard/v1 while adding:
  - Pre-write sensitive secret/PII detection (tokens, API keys, phone numbers, ID cards)
  - GB 32100 18-digit Unified Social Credit Code checksum verification
  - Accounting balance sheet equation enforcement (assets == liabilities + equity)
  - Deterministic R&D ratio & 2-year CAGR / high-tech growth calculation
  - Patent 5th-digit type check, statutory expiry check (10y utility / 20y invention), and 1-year transfer check
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]

SCHEMA_VERSION = "workbuddy-facts-blackboard/v1"
VALID_ORIGINS = {"enterprise_source", "ai_design_target", "public_registry", "mcp_verified", "local_kb_verified"}
VALID_BUSINESS_TYPES = {"equipment_or_mold_maker", "product_or_material_maker", "pure_software", "ambiguous"}

USCC_CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)

SENSITIVE_PATTERNS = [
    ("api_key_or_token", re.compile(r"(?:sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,}|(?:token|api[_-]?key|password|secret)\s*[:=]\s*[^\s,\"'}]{6,})", re.I)),
    ("china_mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("china_id_card", re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")),
]


def detect_sensitive_text(text: str) -> list[dict[str, str]]:
    hits = []
    for label, pattern in SENSITIVE_PATTERNS:
        for m in pattern.finditer(text or ""):
            val = m.group(0)
            masked = val[:4] + "***" + val[-2:] if len(val) > 6 else "***"
            hits.append({"type": label, "masked_sample": masked})
    return hits


def validate_uscc(code: str) -> tuple[bool, str]:
    """Validate GB 32100 18-character Unified Social Credit Code (format + mod-31 check digit)."""
    s = (code or "").strip().upper()
    if len(s) != 18:
        return False, f"长度须为18位，实际为{len(s)}位"
    if any(ch not in USCC_CHARSET for ch in s):
        return False, "包含GB 32100禁止字符（如I/O/Z/S/V或非字母数字）"
    total = sum(USCC_CHARSET.index(s[i]) * USCC_WEIGHTS[i] for i in range(17))
    rem = 31 - (total % 31)
    expected = USCC_CHARSET[0] if rem == 31 else USCC_CHARSET[rem]
    if s[17] != expected:
        return False, f"第18位校验码错误：期望{expected}，实际{s[17]}"
    return True, "ok"


def _dec(val: Any) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val).replace(",", "").strip())
    except InvalidOperation:
        return None


def validate_balance_sheet(
    total_assets: Any,
    total_liabilities: Any,
    total_equity: Any,
    *,
    tolerance: Decimal = Decimal("0.05"),
) -> tuple[bool, str]:
    """Verify accounting identity: Assets == Liabilities + Equity within rounding tolerance."""
    a, l, e = _dec(total_assets), _dec(total_liabilities), _dec(total_equity)
    if a is None or l is None or e is None:
        return False, "资产总额、负债总额或所有者权益存在空值或非数字"
    diff = abs(a - (l + e))
    if diff > tolerance:
        return False, f"资产负债表不平：资产({a}) != 负债({l}) + 权益({e})，差额 {diff}"
    return True, "ok"


def calc_rd_ratio(rd_expense: Any, revenue: Any) -> dict[str, Any]:
    r, rev = _dec(rd_expense), _dec(revenue)
    if r is None or rev is None or rev <= 0:
        return {"ok": False, "error": "研发费用或营业收入无效"}
    ratio = (r / rev) * Decimal("100")
    warnings = []
    if ratio > Decimal("100"):
        warnings.append(f"研发费用率 {ratio:.2f}% 超过 100%（可能处于研发初创/样机期或单位有误，请核对审计口径）")
    return {
        "ok": True,
        "rd_expense": float(r),
        "revenue": float(rev),
        "ratio_pct": round(float(ratio), 2),
        "warnings": warnings,
    }


def calc_growth_metrics(y1_val: Any, y2_val: Any, y3_val: Any) -> dict[str, Any]:
    """Compute both 2-year CAGR (MIIT Little Giant) and High-Tech 2-year average growth rate."""
    v1, v2, v3 = _dec(y1_val), _dec(y2_val), _dec(y3_val)
    if v1 is None or v2 is None or v3 is None or v1 <= 0 or v2 <= 0:
        return {"ok": False, "error": "需提供连续三个正数年度值"}
    hightech_avg = ((v2 / v1 + v3 / v2) / Decimal("2") - Decimal("1")) * Decimal("100")
    cagr = ((float(v3) / float(v1)) ** 0.5 - 1.0) * 100.0
    yoy_latest = ((v3 - v2) / v2) * Decimal("100")
    return {
        "ok": True,
        "hightech_avg_growth_pct": round(float(hightech_avg), 2),
        "cagr_2y_pct": round(cagr, 2),
        "yoy_latest_pct": round(float(yoy_latest), 2),
    }


def validate_patent_item(
    item: dict[str, Any],
    as_of: date | None = None,
    *,
    require_valid_no: bool = True,
    require_transfer_holding_1y: bool = True,
) -> list[str]:
    """Verify patent number format, 5th-digit type consistency, statutory expiry (20y inv / 10y util / 10y or 15y design per 2021-06-01 Patent Law Art.42), and optional 1-year transfer holding period."""
    issues: list[str] = []
    ref_date = as_of or date.today()
    pno = re.sub(r"\s+", "", str(item.get("patent_no") or item.get("no") or "")).upper()
    declared_type = str(item.get("type") or "")
    # Chinese application/ZL number format: (ZL|CN)? YYYY T NNNNNNN(.X)
    m = re.search(r"(?:ZL|CN)?((?:19|20)\d{2})(\d)\d{7}(?:\.[\dX])?", pno)
    if not m:
        if require_valid_no:
            issues.append(f"专利号缺失或不符合中国专利号规范（须含12/13位申请号或ZL号）：「{pno or '空'}」")
        return issues
    filing_year = int(m.group(1))
    type_digit = m.group(2)
    digit_map = {"1": "发明", "2": "实用新型", "3": "外观设计", "8": "PCT发明", "9": "PCT实用新型"}
    expected_type = digit_map.get(type_digit)
    if expected_type and declared_type:
        if (
            ("发明" in expected_type and ("实用" in declared_type or "外观" in declared_type))
            or ("实用" in expected_type and ("发明" in declared_type or "外观" in declared_type))
            or ("外观" in expected_type and ("发明" in declared_type or "实用" in declared_type))
        ):
            issues.append(f"专利号第5位类型倒挂：{pno} 第5位为{type_digit}({expected_type})，但填报类型为「{declared_type}」")
    filing_date_str = str(item.get("filing_date") or "")
    try:
        fdate = date.fromisoformat(filing_date_str[:10]) if filing_date_str else date(filing_year, 12, 31)
    except ValueError:
        issues.append(f"专利 {pno} filing_date 日期格式无效：{filing_date_str}")
        fdate = date(filing_year, 12, 31)
    # Patent Law Art. 42: Invention 20y; Utility Model 10y; Design 15y if filed on/after 2021-06-01 else 10y
    if type_digit in {"1", "8"}:
        term_years = 20
    elif type_digit == "3":
        term_years = 15 if fdate >= date(2021, 6, 1) else 10
    else:
        term_years = 10
    try:
        expiry = date(fdate.year + term_years, fdate.month, fdate.day)
    except ValueError:
        expiry = date(fdate.year + term_years, fdate.month, 28)
    if expiry < ref_date:
        issues.append(f"专利法定保护期已届满：{pno} 申请日 {fdate.isoformat()}（{term_years}年期满于 {expiry.isoformat()}），不得计入有效知识产权")
    # Transfer holding period: required (>= 12 months) only when policy explicitly mandates it (NOT required by High-Tech 国科发火〔2016〕32号/195号)
    acq = str(item.get("acquisition") or "")
    if any(k in acq for k in ("受让", "转让", "并购")):
        tdate_str = str(item.get("transfer_date") or "").strip()
        if require_transfer_holding_1y:
            if not tdate_str:
                issues.append(f"受让专利 {pno} 缺少转让登记生效日（transfer_date），无法核验是否满1年")
            else:
                try:
                    td = date.fromisoformat(tdate_str[:10])
                    if (ref_date - td).days < 365:
                        issues.append(f"受让专利 {pno} 转让日 {td.isoformat()} 距今不足1年，不满足满1年门槛")
                except ValueError:
                    issues.append(f"受让专利 {pno} transfer_date 日期格式无效：{tdate_str}")
        elif tdate_str:
            try:
                td = date.fromisoformat(tdate_str[:10])
                if td > ref_date:
                    issues.append(f"受让专利 {pno} 转让登记生效日 {td.isoformat()} 晚于核验日 {ref_date.isoformat()}")
            except ValueError:
                issues.append(f"受让专利 {pno} transfer_date 日期格式无效：{tdate_str}")
    return issues


def normalize_patent_key(item: dict[str, Any]) -> str:
    """Canonicalize Chinese patent/application number by stripping ZL/CN prefix and trailing check digit (.X / 13th char)."""
    raw_str = re.sub(r"\s+", "", str(item.get("patent_no") or item.get("no") or "")).upper()
    m = re.search(r"(?:ZL|CN)?((?:19|20)\d{10})(?:\.?[\dX])?", raw_str)
    if m:
        return m.group(1)
    raw = re.sub(r"[^A-Za-z0-9]", "", raw_str)
    return re.sub(r"^(?:ZL|CN)", "", raw)


def normalize_company_name(name: str) -> str:
    return re.sub(r"[\s\u3000（）()·\-_]+", "", (name or "").strip())


def subject_filename(company_name: str, credit_code: str = "") -> str:
    clean_name = re.sub(r"[^\w\u4e00-\u9fff]+", "", (company_name or "").strip())[:16] or "enterprise"
    code = re.sub(r"[^A-Za-z0-9]", "", (credit_code or "").strip()).upper()
    suffix = code[-6:] if len(code) >= 6 else hashlib.sha256(normalize_company_name(company_name).encode("utf-8")).hexdigest()[:6]
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
    return bool(
        normalize_company_name(str(payload.get("company_name", "")))
        and normalize_company_name(str(payload.get("company_name", ""))) == normalize_company_name(company_name)
    )


SENSITIVE_KEY_RE = re.compile(
    r"(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|id[_-]?token|session[_-]?token|bearer[_-]?token|private[_-]?key|client[_-]?secret)",
    re.I,
)


def detect_sensitive_obj(obj: Any, path: str = "$") -> list[dict[str, str]]:
    """Recursively scan dict keys and scalar string values for secrets/PII."""
    hits: list[dict[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if SENSITIVE_KEY_RE.search(ks) and v not in (None, "", []):
                hits.append({"type": "sensitive_key", "path": f"{path}.{ks}"})
            hits.extend(detect_sensitive_obj(v, f"{path}.{ks}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            hits.extend(detect_sensitive_obj(item, f"{path}[{i}]"))
    elif isinstance(obj, str):
        for h in detect_sensitive_text(obj):
            hits.append({**h, "path": path})
    return hits


def validate_blackboard(payload: dict[str, Any], *, check_uscc: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["黑板根节点必须为 JSON 对象"]
    required = ("schema_version", "company_name", "credit_code", "updated_at", "lockedProduct", "patentTierReport", "estimatedMetrics", "financialFacts", "checkupSnapshots")
    for k in required:
        if k not in payload:
            errors.append(f"缺少必需顶层字段：{k}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}")
    if not str(payload.get("company_name", "")).strip():
        errors.append("company_name 不能为空")
    if check_uscc and payload.get("credit_code"):
        ok, msg = validate_uscc(str(payload["credit_code"]))
        if not ok:
            errors.append(f"credit_code 无效：{msg}")
    # Deep nested schema validation (reject null and wrong nested field types on BOTH read & write)
    lp = payload.get("lockedProduct")
    if not isinstance(lp, dict):
        errors.append("lockedProduct 必须为非空 JSON 对象")
    else:
        bt = lp.get("businessType", "ambiguous")
        if bt not in VALID_BUSINESS_TYPES:
            errors.append(f"lockedProduct.businessType 无效：{bt}")
        if "revision" in lp:
            rev = lp["revision"]
            if isinstance(rev, bool) or not isinstance(rev, int) or rev < 0:
                errors.append(f"lockedProduct.revision 必须为非负整数：{rev!r}")
        for str_key in ("rawAnchor", "formalDeclarationName", "sixBasesAlignment"):
            if str_key in lp and not isinstance(lp[str_key], str):
                errors.append(f"lockedProduct.{str_key} 必须为字符串")
        if "unpatentedProcessTags" in lp:
            tags = lp["unpatentedProcessTags"]
            if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
                errors.append("lockedProduct.unpatentedProcessTags 必须为字符串数组")
    pt = payload.get("patentTierReport")
    if not isinstance(pt, dict):
        errors.append("patentTierReport 必须为非空 JSON 对象")
    else:
        for tk in ("direct_support", "production_support", "weak_or_unrelated"):
            if tk in pt and not isinstance(pt[tk], list):
                errors.append(f"patentTierReport.{tk} 必须为数组")
    em = payload.get("estimatedMetrics")
    if not isinstance(em, list):
        errors.append("estimatedMetrics 必须为非空数组（不可为 null）")
    else:
        for idx, m_item in enumerate(em):
            if not isinstance(m_item, dict):
                errors.append(f"estimatedMetrics[{idx}] 必须为对象")
            elif m_item.get("origin", "ai_design_target") not in VALID_ORIGINS:
                errors.append(f"estimatedMetrics[{idx}].origin 无效：{m_item.get('origin')}")
    for dkey in ("financialFacts", "checkupSnapshots"):
        if not isinstance(payload.get(dkey), dict):
            errors.append(f"{dkey} 必须为非空 JSON 对象")
    # Recursive sensitive key & value guard
    sens = detect_sensitive_obj(payload)
    if sens:
        errors.append(f"检测到敏感凭据或个人隐私信息，禁止写入黑板：{sens[:3]}")
    return errors


def _assert_inside_workspace(workspace: Path, target: Path) -> None:
    ws_resolved = workspace.resolve()
    facts_dir = ws_resolved / ".facts"
    if facts_dir.is_symlink():
        raise ValueError(f"安全拦截：.facts 目录不得为符号链接：{facts_dir}")
    if target.is_symlink():
        raise ValueError(f"安全拦截：黑板目标不得为符号链接：{target}")
    try:
        target.resolve().relative_to(ws_resolved)
    except ValueError as exc:
        raise ValueError(f"安全拦截：黑板路径越出工作区边界：{target}") from exc


@contextmanager
def blackboard_lock(workspace: Path, company_name: str, credit_code: str = ""):
    """Exclusive per-subject advisory file lock protecting read-modify-write cycles against concurrent clobber."""
    target = blackboard_path(workspace, company_name, credit_code)
    _assert_inside_workspace(workspace, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    _assert_inside_workspace(workspace, lock_path)
    with lock_path.open("a+", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield target
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def load_blackboard(workspace: Path, company_name: str, credit_code: str = "", *, strict: bool = False) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    target = blackboard_path(workspace, company_name, credit_code)
    _assert_inside_workspace(workspace, target)
    candidates = [target] if target.is_file() else (sorted((workspace / ".facts").glob("*.facts.json")) if (workspace / ".facts").is_dir() else [])
    for c in candidates:
        if c.is_symlink():
            warnings.append(f"跳过符号链接黑板：{c.name}")
            continue
        try:
            payload = json.loads(c.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if strict and c == target:
                raise ValueError(f"黑板文件损坏或无法解析：{c.name}: {exc}") from exc
            warnings.append(f"跳过无效黑板 {c.name}: {exc}")
            continue
        if isinstance(payload, dict) and _subject_matches(payload, company_name, credit_code):
            if strict:
                errs = validate_blackboard(payload, check_uscc=bool(payload.get("credit_code")))
                if errs:
                    raise ValueError("严格模式读取黑板校验失败：" + "；".join(errs))
            return payload, warnings
        if c == target:
            msg = f"主体不匹配防串户：期望「{company_name}」，文件为「{payload.get('company_name', '')}」"
            if strict:
                raise ValueError(msg)
            warnings.append(msg)
    return None, warnings


def _atomic_write_blackboard(target: Path, payload: dict[str, Any]) -> None:
    import tempfile

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=target.parent, prefix=".facts_", suffix=".tmp", delete=False, encoding="utf-8") as fh:
            tmp = Path(fh.name)
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(target)
    except Exception:
        if tmp is not None and tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def save_blackboard(workspace: Path, payload: dict[str, Any], *, strict: bool = True, allow_sensitive: bool = False) -> Path:
    company_name = str(payload.get("company_name", "")).strip()
    if not company_name:
        raise ValueError("company_name 不能为空")
    credit_code = str(payload.get("credit_code", "")).strip().upper()
    payload["schema_version"] = SCHEMA_VERSION
    payload["company_name"] = company_name
    payload["credit_code"] = credit_code
    payload["updated_at"] = _now_iso()
    if not allow_sensitive:
        sens = detect_sensitive_obj(payload)
        if sens:
            raise ValueError(f"拒绝写入敏感凭据或个人隐私信息：{sens[:3]}")
    if strict:
        errs = validate_blackboard(payload, check_uscc=bool(credit_code))
        if errs:
            raise ValueError("严格模式黑板校验失败：" + "；".join(errs))
    target = blackboard_path(workspace, company_name, credit_code)
    _assert_inside_workspace(workspace, target)
    _atomic_write_blackboard(target, payload)
    return target


def update_blackboard(
    workspace: Path,
    company_name: str,
    credit_code: str,
    mutator: Callable[[dict[str, Any]], None],
    *,
    strict: bool = True,
) -> Path:
    """Atomic locked read-modify-write for a subject blackboard."""
    with blackboard_lock(workspace, company_name, credit_code):
        existing, _ = load_blackboard(workspace, company_name, credit_code, strict=strict)
        bb = existing if existing is not None else empty_blackboard(company_name, credit_code)
        mutator(bb)
        return save_blackboard(workspace, bb, strict=strict)


def reconcile_text_against_estimates(blackboard: dict[str, Any], latest_text: str) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", latest_text or "")
    pending, resolved = [], []
    for item in blackboard.get("estimatedMetrics", []):
        if not isinstance(item, dict) or item.get("origin", "ai_design_target") != "ai_design_target":
            continue
        snip = re.sub(r"\s+", "", str(item.get("snippet", "")))
        val = re.sub(r"\s+", "", str(item.get("suggestedValue", "")))
        present = bool((snip and snip in compact) or (val and val in compact))
        entry = dict(item)
        entry["status"] = "pending" if present else "resolved"
        if present:
            entry["checkup_note"] = "源自初稿行业设计目标，尚未见企业实测原件，提交前请核对检测报告或工艺单。"
            pending.append(entry)
        else:
            resolved.append(entry)
    return {"pending_count": len(pending), "resolved_count": len(resolved), "pending_estimates": pending, "resolved_estimates": resolved}


def main() -> int:
    parser = argparse.ArgumentParser(description="统一主体隔离事实黑板与财务/知产核验 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_u = sub.add_parser("upsert", help="合并写入标准黑板（自动拦截凭据与手机号）")
    p_u.add_argument("--workspace", type=Path, default=Path("."))
    p_u.add_argument("--company", required=True)
    p_u.add_argument("--credit-code", default="")
    p_u.add_argument("--financials-json", default="")
    p_u.add_argument("--product-json", default="")
    p_u.add_argument("--patents-json", default="")
    p_u.add_argument("--estimated-metrics-json", default="")
    p_u.add_argument("--snapshot-key", default="")
    p_u.add_argument("--snapshot-json", default="")

    p_r = sub.add_parser("read", help="安全读取主体黑板")
    p_r.add_argument("--workspace", type=Path, default=Path("."))
    p_r.add_argument("--company", required=True)
    p_r.add_argument("--credit-code", default="")
    p_r.add_argument("--strict", action="store_true")

    p_v = sub.add_parser("validate", help="校验黑板 Schema、信用代码与敏感信息")
    p_v.add_argument("file", type=Path)
    p_v.add_argument("--check-uscc", action="store_true")

    p_rec = sub.add_parser("reconcile", help="回查正文并自动销项外置待核估算项")
    p_rec.add_argument("--workspace", type=Path, default=Path("."))
    p_rec.add_argument("--company", required=True)
    p_rec.add_argument("--credit-code", default="")
    p_rec.add_argument("--text-file", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "upsert":
        def _apply(bb: dict[str, Any]) -> None:
            if args.financials_json:
                bb.setdefault("financialFacts", {}).update(json.loads(args.financials_json))
            if args.product_json:
                bb.setdefault("lockedProduct", {}).update(json.loads(args.product_json))
            if args.patents_json:
                bb.setdefault("patentTierReport", {}).update(json.loads(args.patents_json))
            if args.estimated_metrics_json:
                bb.setdefault("estimatedMetrics", []).extend(json.loads(args.estimated_metrics_json))
            if args.snapshot_key and args.snapshot_json:
                bb.setdefault("checkupSnapshots", {})[args.snapshot_key] = json.loads(args.snapshot_json)

        path = update_blackboard(args.workspace, args.company, args.credit_code, _apply, strict=True)
        print(json.dumps({"status": "ok", "path": str(path), "schema_version": SCHEMA_VERSION}, ensure_ascii=False))
        return 0
    if args.cmd == "read":
        bb, warnings = load_blackboard(args.workspace, args.company, args.credit_code, strict=args.strict)
        print(json.dumps({"found": bb is not None, "warnings": warnings, "blackboard": bb}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "validate":
        payload = json.loads(args.file.read_text(encoding="utf-8"))
        errs = validate_blackboard(payload, check_uscc=args.check_uscc)
        print(json.dumps({"valid": not errs, "errors": errs}, ensure_ascii=False))
        return 0 if not errs else 2
    if args.cmd == "reconcile":
        bb, warnings = load_blackboard(args.workspace, args.company, args.credit_code)
        if bb is None:
            print(json.dumps({"found": False, "warnings": warnings, "pending_count": 0, "resolved_count": 0}, ensure_ascii=False))
            return 0
        res = reconcile_text_against_estimates(bb, args.text_file.read_text(encoding="utf-8"))
        print(json.dumps({"found": True, "warnings": warnings, **res}, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

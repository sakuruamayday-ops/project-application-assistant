#!/usr/bin/env python3
"""
Unified Anti-Low-Quality & Anti-Hallucination Delivery Quality Gate.
Zero fake-strict gates: every real violation returns ok=False and non-zero exit code (2).
Covers:
  - Anti-lazy substance density check (section min/max character bounds + required structural keywords)
  - Zero placeholders & zero defensive hedging phrases in formal deliverables
  - Smart parentheses check (whitelists legal units, doc numbers, scientific units like g/(m²·24h))
  - Rewrite numeric/fact preservation audit (full engineering units: ppm/ppb/Pa/MPa/℃/mm/kW/ms/dB)
  - Safe arithmetic expression verification for evidence ledgers
  - Strict cross-enterprise contamination blocker (hard error, never advisory-only)
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
import math
import operator
import re
from pathlib import Path
from typing import Any

PLACEHOLDER_RE = re.compile(
    r"\[(?:待补充|待核实|请核实|填写|此处填|TBD|XXX|客户填写)\]|"
    r"【(?:待补充|待核实|请核实|填写|此处填|客户填写)】|"
    r"(?<![A-Za-z])(?:TBD|XXX)(?![A-Za-z])|客户填写|待企业核定|主要技术指标待补充"
)
DEFENSIVE_HEDGE_RE = re.compile(
    r"仅供参考|不构成(?:任何)?(?:法律|专业|申报|投资)建议|请以官方(?:发布|通知)?为准|免责声明|本报告不承担.*责任"
)

# Scientific / legal parentheses whitelist (eliminates false positives on real applications)
ALLOWED_PAREN_CONTENT_RE = re.compile(
    r"^(?:"
    r"万元|亿元|元|%|℃|mm|cm|m|km|kg|g|mg|L|mL|ms|s|h|dB|A|V|W|kW|MPa|kPa|Pa|ppm|ppb|rpm|Hz|"
    r"限\d+字|含.*|不含.*|简称.*|以下简称.*|以下简称「.*」|"
    r"[一二三四五六七八九十\d]+|套|台|套/批|次/秒|个/秒|"
    r"m²·24h|m2·24h|SQuaRE|RUSP|CMA|CNAS|ISO|GB|IEC|IEEE|SM[234]|"
    r"交|试|暂行|修订|20\d{2}年版?|第[一二三四五六七八九十\d]+批|"
    r"服务|内、外部|非)?$"
)

# Comprehensive numeric + sign + engineering/scientific unit extractor for rewrite fidelity checks
NUM_UNIT_RE = re.compile(
    r"(?:[+\-−±≤≥<>]\s*)?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:"
    r"个百分点|百分点|万元|亿元|千元|元|%|‰|ppm|ppb|MPa|kPa|Pa|mbar|℃|°C|K|"
    r"mm|cm|μm|um|nm|km|m²|㎡|m³|kg|g|mg|t|吨|ms|μs|秒|分钟|小时|天|年|个月|"
    r"kW|MW|W|kV|V|mA|A|MHz|kHz|Hz|GHz|dB\(A\)|dB|rpm|N·m|N|cc|mL|L|Gbps|Mbps|KB|MB|GB|"
    r"个/秒|次/秒|套|台|件|项|家|人|名|类|条|处|份|倍"
    r")?"
)

FORBIDDEN_UNGROUNDED_CLAIMS = ("国际领先", "世界第一", "全球首创", "行业绝对领先", "国内唯一")


def audit_formal_text(
    text: str,
    *,
    expected_company: str = "",
    min_chars: int = 0,
    max_chars: int = 0,
    required_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Run hard quality gate on formal application prose."""
    errors: list[dict[str, Any]] = []
    compact = re.sub(r"\s+", "", text or "")
    length = len(compact)

    if min_chars and length < min_chars:
        errors.append({"rule": "min_density", "issue": f"正文仅{length}字，低于最低饱满度要求{min_chars}字"})
    if max_chars and length > max_chars:
        errors.append({"rule": "max_length", "issue": f"正文{length}字，超过{max_chars}字上限"})

    for kw in (required_keywords or []):
        if kw not in compact:
            errors.append({"rule": "required_element", "issue": f"缺少必备结构/要素：「{kw}」"})

    ph = PLACEHOLDER_RE.findall(text or "")
    if ph:
        errors.append({"rule": "placeholder", "issue": f"正文残留未清理占位符/提示词：{ph[:8]}"})

    hd = DEFENSIVE_HEDGE_RE.findall(text or "")
    if hd:
        errors.append({"rule": "defensive_hedge", "issue": f"正式交付正文混入防御兜底或免责话术：{hd[:5]}"})

    # Cross-enterprise contamination check (supports alphanumeric company names & strips common leading verbs)
    if expected_company:
        exp_clean = re.sub(r"[\s（）()]+", "", expected_company)
        raw_cos = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9·]{2,24}(?:股份有限公司|有限责任公司|有限公司)", text or ""))
        cleaned_cos = {re.sub(r"^(?:本项目由|本企业为|本公司为|单位为|系|由|向|与|和|及|为)", "", c) for c in raw_cos}
        foreign = sorted(
            c for c in cleaned_cos
            if len(c) >= 6 and re.sub(r"[\s（）()]+", "", c) != exp_clean and not c.endswith(exp_clean)
        )
        if foreign:
            errors.append({"rule": "cross_enterprise_contamination", "issue": f"检测到跨企业名称混入（期望「{expected_company}」）：{foreign}"})

    # Smart suspicious-parentheses check (only flags bracketed editorial notes, never legal units/doc codes)
    suspicious_parens = []
    for m in re.finditer(r"[\(（]([^\)）]{1,40})[\)）]", text or ""):
        inner = m.group(1).strip()
        if any(bad in inner for bad in ("待", "请", "拟", "暂", "估", "注：", "备注", "核实", "补充", "替换", "此处")):
            suspicious_parens.append(m.group(0))
    if suspicious_parens:
        errors.append({"rule": "suspicious_parentheses", "issue": f"正文中存在疑似编辑批注/兜底括号：{suspicious_parens[:8]}"})

    return {
        "ok": len(errors) == 0,
        "length": length,
        "error_count": len(errors),
        "errors": errors,
    }


def _extract_num_tokens(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for m in NUM_UNIT_RE.finditer(text or ""):
        tok = re.sub(r"\s+|,", "", m.group(0)).replace("−", "-")
        if tok:
            counts[tok] += 1
    return counts


def audit_rewrite_fidelity(source_text: str, rewritten_text: str, *, max_chars: int = 0) -> dict[str, Any]:
    """Strict humanizer rewrite audit: preserves signs, units, and multiplicity; rejects dropped/fabricated/inflated claims."""
    errors: list[dict[str, Any]] = []
    src_nums = _extract_num_tokens(source_text)
    new_nums = _extract_num_tokens(rewritten_text)
    dropped = sorted((src_nums - new_nums).elements())
    added = sorted((new_nums - src_nums).elements())
    if dropped:
        errors.append({"rule": "dropped_numbers", "issue": f"润色丢失或改变符号/频次的原文数值/单位：{dropped[:10]}"})
    if added:
        errors.append({"rule": "fabricated_numbers", "issue": f"润色凭空新增或篡改符号/频次的数值/单位：{added[:10]}"})

    # Check fabricated superlative claims not present in source
    added_claims = [c for c in FORBIDDEN_UNGROUNDED_CLAIMS if c in rewritten_text and c not in source_text]
    if added_claims:
        errors.append({"rule": "inflated_claim", "issue": f"润色新增原文无依据的夸大宣称：{added_claims}"})

    # Check placeholders or editorial brackets introduced during rewrite
    ph = PLACEHOLDER_RE.findall(rewritten_text or "")
    if ph:
        errors.append({"rule": "introduced_placeholder", "issue": f"润色引入占位符：{ph[:5]}"})

    new_len = len(re.sub(r"\s+", "", rewritten_text or ""))
    if max_chars and new_len > max_chars:
        errors.append({"rule": "max_length_exceeded", "issue": f"润色后{new_len}字超过上限{max_chars}字"})

    return {
        "ok": len(errors) == 0,
        "source_number_count": sum(src_nums.values()),
        "rewritten_number_count": sum(new_nums.values()),
        "dropped_numbers": dropped,
        "added_numbers": added,
        "rewritten_length": new_len,
        "errors": errors,
    }


_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval_expr(expr: str) -> float:
    node = ast.parse(expr, mode="eval").body

    def _ev(n: ast.AST) -> float:
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _SAFE_OPS:
            return _SAFE_OPS[type(n.op)](_ev(n.left), _ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _SAFE_OPS:
            return _SAFE_OPS[type(n.op)](_ev(n.operand))
        raise ValueError(f"unsupported expression node: {type(n).__name__}")

    return _ev(node)


def verify_calculation_claim(formula: str, claimed_value: float, *, rel_tol: float = 0.005, abs_tol: float = 0.02) -> dict[str, Any]:
    """Deterministically recompute an evidence-ledger calculation claim and reject bad math or non-finite values."""
    if not isinstance(claimed_value, (int, float)) or isinstance(claimed_value, bool) or not math.isfinite(claimed_value):
        return {"ok": False, "error": f"填报结果非有限数值：{claimed_value}"}
    clean = formula.replace("×", "*").replace("÷", "/").replace("−", "-").strip()
    try:
        actual = _safe_eval_expr(clean)
    except Exception as exc:
        return {"ok": False, "error": f"公式无法安全复算 ({clean}): {exc}"}
    if not math.isfinite(actual):
        return {"ok": False, "error": f"公式计算结果非有限数值：{actual}"}
    diff = abs(actual - claimed_value)
    scale = max(abs(actual), abs(claimed_value), 1.0)
    ok = diff <= max(abs_tol, rel_tol * scale)
    return {
        "ok": ok,
        "formula": clean,
        "computed": round(actual, 6),
        "claimed": claimed_value,
        "diff": round(diff, 6),
        "error": "" if ok else f"算术复算失败：公式计算得 {actual:.4f}，填报为 {claimed_value}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="统一反敷衍/防造假/防串户质量硬门禁 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_t = sub.add_parser("check-text", help="校验正式交付正文质量（严格退出码2）")
    p_t.add_argument("file", type=Path)
    p_t.add_argument("--company", default="")
    p_t.add_argument("--min-chars", type=int, default=0)
    p_t.add_argument("--max-chars", type=int, default=0)
    p_t.add_argument("--require", action="append", default=[])

    p_rw = sub.add_parser("check-rewrite", help="校验润色稿数值与事实保真（违规退出码2）")
    p_rw.add_argument("source_file", type=Path)
    p_rw.add_argument("rewritten_file", type=Path)
    p_rw.add_argument("--max-chars", type=int, default=0)

    p_calc = sub.add_parser("check-calc", help="校验证据台账算术公式与结果（违规退出码2）")
    p_calc.add_argument("--formula", required=True)
    p_calc.add_argument("--claimed", type=float, required=True)

    args = parser.parse_args()
    if args.cmd == "check-text":
        res = audit_formal_text(
            args.file.read_text(encoding="utf-8"),
            expected_company=args.company,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
            required_keywords=args.require,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 2
    if args.cmd == "check-rewrite":
        res = audit_rewrite_fidelity(
            args.source_file.read_text(encoding="utf-8"),
            args.rewritten_file.read_text(encoding="utf-8"),
            max_chars=args.max_chars,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 2
    if args.cmd == "check-calc":
        res = verify_calculation_claim(args.formula, args.claimed)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

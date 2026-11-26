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
META_TALK_RE = re.compile(
    r"本(?:节|段|栏)(?:用|以|采用|按|从|将|仅)|"
    r"本细分市场的分母应限定为|"
    r"分母口径与[^。；\n]{0,8}一致|"
    r"占有率(?:数值)?(?:按|以)[^。；\n]{0,24}(?:直接除算|不作估算)|"
    r"(?:需|须)?待[^。；\n]{0,20}(?:核定|确认|提供|补充)后(?:再)?(?:填入|计算|更新|补充|测算)|"
    r"精确[^。；\n]{0,6}待[^。；\n]{0,4}(?:核|补|定)|"
    r"以下(?:内容)?(?:为|是)(?:根据|基于)(?:素材|材料|资料)(?:生成|撰写)"
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

# Comprehensive numeric + sign (including Chinese 负 and full-width －) + engineering/scientific unit extractor
NUM_UNIT_RE = re.compile(
    r"(?:(?:[+\-−－±≤≥<>]|负)\s*)?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:"
    r"个百分点|百分点|万元|亿元|千元|元|%|‰|ppm|ppb|MPa|kPa|Pa|mbar|℃|°C|K|"
    r"mm|cm|μm|um|nm|km|m²|㎡|m³|kg|g|mg|t|吨|ms|μs|秒|分钟|小时|天|年|个月|"
    r"kW|MW|W|kV|V|mA|A|MHz|kHz|Hz|GHz|dB\(A\)|dB|rpm|N·m|N|cc|mL|L|Gbps|Mbps|KB|MB|GB|"
    r"个/秒|次/秒|套|台|件|项|家|人|名|类|条|处|份|倍"
    r")?"
)

FORBIDDEN_UNGROUNDED_CLAIMS = ("国际领先", "世界第一", "全球首创", "行业绝对领先", "国内唯一")

DECLARANT_FIELD_RE = re.compile(
    r"(?:申报单位|申请单位|申请企业|申报企业|申请人|企业名称|依托单位|填报单位|本项目由|本企业为|本公司为)\s*(?:[（(](?:盖章|公章)[）)])?\s*(?:[:：|｜\t为是])?\s*([\u4e00-\u9fffA-Za-z0-9·（）()]{2,32}?(?:股份有限公司|有限责任公司|有限公司))"
)
USCC_FIELD_RE = re.compile(
    r"(?:统一社会信用代码|社会信用代码|信用代码)\s*[:：|｜\t]?\s*([0-9A-HJ-NPQRTUWXY]{18})",
    re.I,
)
COMPANY_ENTITY_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9·]{2,24}(?:股份有限公司|有限责任公司|有限公司)"
)
COMPANY_PREFIX_STRIP_RE = re.compile(
    r"^(?:本项目由|本企业为|本公司为|申报单位为|申请单位为|单位为|采购自|购自|委托|系|由|向|与|和|及|为|如|对|给|被|在)"
)
EXTERNAL_PREFIX_RE = re.compile(
    r"(?:购自|采购自|向|委托|对标|客户(?:为|是|包括|涵盖)?|供应商(?:为|是|包括)?|配套|服务于|合作(?:单位|伙伴|方)?(?:为|是)?|检验(?:机构)?(?:为|是)?|检测(?:机构)?(?:为|是)?|审计(?:机构)?(?:为|是)?|母公司|子公司|控股股东|实际控制人|(?:[A-Za-z]?股)?上市公司|兄弟(?:企业|公司)|合资方|技术许可方|关联(?:方|企业|公司)?|同行业?|竞品|标杆|例如|如)\s*$"
)
EXTERNAL_SUFFIX_RE = re.compile(
    r"^\s*(?:等(?:客户|供应商|企业|同行|竞品|单位)|供应|提供|出具|检测|检验|审计|合作|配套|客户|供应商)"
)


def extract_declared_subject(text: str) -> dict[str, str]:
    """Extract explicit declarant company name and USCC from cover / registration table / declaration header."""
    company = ""
    credit_code = ""
    m_co = DECLARANT_FIELD_RE.search(text or "")
    if m_co:
        company = COMPANY_PREFIX_STRIP_RE.sub("", m_co.group(1).strip())
    m_cc = USCC_FIELD_RE.search(text or "")
    if m_cc:
        credit_code = m_cc.group(1).strip().upper()
    return {"company": company, "credit_code": credit_code}


def audit_formal_text(
    text: str,
    *,
    expected_company: str = "",
    expected_credit_code: str = "",
    allowed_companies: list[str] | None = None,
    min_chars: int = 0,
    max_chars: int = 0,
    required_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Run hard quality gate on formal application prose.
    Checks explicit declarant/cover subject & credit_code FIRST, then classifies remaining mentions by local role context.
    """
    errors: list[dict[str, Any]] = []
    external_mentions: list[str] = []
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

    mt = [m.group(0) for m in META_TALK_RE.finditer(text or "")]
    if mt:
        errors.append({"rule": "meta_self_talk", "issue": f"正文混入写作说明或自言自语句（应删除或移到正文外）：{mt[:5]}"})

    hd = DEFENSIVE_HEDGE_RE.findall(text or "")
    if hd:
        errors.append({"rule": "defensive_hedge", "issue": f"正式交付正文混入防御兜底或免责话术：{hd[:5]}"})

    raw_text = text or ""
    if expected_credit_code:
        exp_cc = expected_credit_code.strip().upper()
        for m_cc in USCC_FIELD_RE.finditer(raw_text):
            found_cc = m_cc.group(1).strip().upper()
            if found_cc != exp_cc:
                errors.append({"rule": "credit_code_mismatch", "issue": f"申报主体信用代码不一致：正文为「{found_cc}」，期望「{exp_cc}」"})

    if expected_company:
        exp_clean = re.sub(r"[\s（）()]+", "", expected_company)
        allow_clean = {exp_clean} | {re.sub(r"[\s（）()]+", "", c) for c in (allowed_companies or []) if c}
        foreign_block: set[str] = set()

        # Pass 1: Explicit declarant / cover / registration fields ALWAYS represent the filing subject (never excused by same-sentence client mentions!)
        declarant_spans: list[tuple[int, int]] = []
        for m_decl in DECLARANT_FIELD_RE.finditer(raw_text):
            decl_co = COMPANY_PREFIX_STRIP_RE.sub("", m_decl.group(1).strip())
            norm_decl = re.sub(r"[\s（）()]+", "", decl_co)
            declarant_spans.append((m_decl.start(1), m_decl.end(1)))
            if len(decl_co) >= 6 and norm_decl not in allow_clean:
                foreign_block.add(decl_co)

        # Pass 2: Remaining entity mentions evaluated strictly by immediate local role prefix/suffix (e.g., "购自乙方有限公司")
        for m in COMPANY_ENTITY_RE.finditer(raw_text):
            if any(not (m.end() <= s or m.start() >= e) for s, e in declarant_spans):
                continue
            raw_co = m.group(0)
            cleaned = COMPANY_PREFIX_STRIP_RE.sub("", raw_co)
            strip_len = len(raw_co) - len(cleaned)
            entity_start = m.start() + strip_len
            norm_co = re.sub(r"[\s（）()]+", "", cleaned)
            if len(cleaned) < 6 or any(norm_co == a or norm_co.endswith(a) for a in allow_clean):
                continue
            # Also peel off common leading verbs/role descriptors glued to the regex match (e.g. "设备购自乙方有限公司", "领军企业某标杆公司...")
            m_glue = re.search(
                r"(购自|采购自|采购|委托|向|对标|同行业?领军企业|领军企业|标杆企业|龙头企业|同行企业|竞争对手|合作伙伴|客户为?|供应商为?|配套客户|配套|服务于|(?:[A-Za-z]?股)?上市公司|关联(?:方|企业|公司)|兄弟(?:企业|公司)|母公司|子公司|控股股东|实际控制人|合资方|技术许可方|与|和|及|如)([\u4e00-\u9fffA-Za-z0-9·]{2,20}(?:股份有限公司|有限责任公司|有限公司))$",
                cleaned,
            )
            if m_glue:
                cleaned = m_glue.group(2)
                norm_co = re.sub(r"[\s（）()]+", "", cleaned)
                if len(cleaned) < 6 or any(norm_co == a or norm_co.endswith(a) for a in allow_clean):
                    continue
                if cleaned not in external_mentions:
                    external_mentions.append(cleaned)
                continue
            before = raw_text[max(0, entity_start - 16):entity_start]
            after = raw_text[m.end():min(len(raw_text), m.end() + 14)]
            # Do not cross sentence/clause boundaries when checking immediate role context
            before_clause = re.split(r"[。；;！？\n]", before)[-1]
            after_clause = re.split(r"[。；;！？\n]", after)[0]
            if EXTERNAL_PREFIX_RE.search(before_clause) or EXTERNAL_SUFFIX_RE.search(after_clause):
                if cleaned not in external_mentions:
                    external_mentions.append(cleaned)
            else:
                foreign_block.add(cleaned)

        if foreign_block:
            errors.append({"rule": "cross_enterprise_contamination", "issue": f"检测到跨企业名称混入（期望「{expected_company}」）：{sorted(foreign_block)}"})

    # Smart suspicious-parentheses check (only flags bracketed editorial notes, never legal units/doc codes)
    suspicious_parens = []
    for m in re.finditer(r"[\(（]([^\)）]{1,40})[\)）]", text or ""):
        inner = m.group(1).strip()
        if any(bad in inner for bad in ("待", "请", "拟", "暂", "估", "注：", "备注", "核实", "补充", "替换", "此处")):
            suspicious_parens.append(m.group(0))
    if suspicious_parens:
        errors.append({"rule": "suspicious_parentheses", "issue": f"正文中存在疑似编辑批注/兜底括号：{suspicious_parens[:8]}"})

    out: dict[str, Any] = {
        "ok": len(errors) == 0,
        "length": length,
        "error_count": len(errors),
        "errors": errors,
    }
    if external_mentions:
        out["external_entity_mentions"] = external_mentions
    return out


def _normalize_num_token(raw: str) -> str:
    tok = re.sub(r"\s+|,", "", raw).replace("−", "-").replace("－", "-")
    if tok.startswith("负"):
        tok = "-" + tok[1:]
    return tok


def _extract_num_tokens(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for m in NUM_UNIT_RE.finditer(text or ""):
        tok = _normalize_num_token(m.group(0))
        if tok:
            counts[tok] += 1
    return counts


METRIC_BIND_RE = re.compile(
    r"(研发费用?|研发投入|设备费用?|材料费用?|营业收入|主营业务收入|营收|净利润|利润总额|资产总额|负债总额|净资产|毛利率|研发强度|高新收入|科技人员|专利数?量?)\s*(?:为|达|达到|约|共|共计|合计|占|占比|[:：=])?\s*"
    r"((?:(?:[+\-−－±≤≥<>]|负)\s*)?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万元|亿元|千元|元|%|‰|个百分点|人|名|项|件)?)"
)


def _extract_metric_bindings(text: str) -> dict[str, Counter[str]]:
    bindings: dict[str, Counter[str]] = {}
    for m in METRIC_BIND_RE.finditer(text or ""):
        label = m.group(1).rstrip("用")
        if label == "研发投入":
            label = "研发费"
        val = _normalize_num_token(m.group(2))
        bindings.setdefault(label, Counter())[val] += 1
    return bindings


YEAR_METRIC_BIND_RE = re.compile(
    r"(20\d{2})\s*年[^。；\n]{0,20}?"
    r"(研发费用?|研发投入|设备费用?|材料费用?|营业收入|主营业务收入|营收|净利润|利润总额|资产总额|负债总额|净资产|高新收入|科技人员)\s*(?:为|达|达到|约|共|共计|合计|[:：=])?\s*"
    r"((?:(?:[+\-−－±≤≥<>]|负)\s*)?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万元|亿元|千元|元|%|‰|人|名)?)"
)


def _extract_year_metric_bindings(text: str) -> dict[tuple[str, str], Counter[str]]:
    bindings: dict[tuple[str, str], Counter[str]] = {}
    for m in YEAR_METRIC_BIND_RE.finditer(text or ""):
        year = m.group(1)
        label = m.group(2).rstrip("用")
        if label == "研发投入":
            label = "研发费"
        val = _normalize_num_token(m.group(3))
        bindings.setdefault((year, label), Counter())[val] += 1
    return bindings


def audit_rewrite_fidelity(source_text: str, rewritten_text: str, *, max_chars: int = 0) -> dict[str, Any]:
    """Strict humanizer rewrite audit: preserves signs (incl. Chinese 负), units, multiplicity, and metric/year-to-value bindings."""
    errors: list[dict[str, Any]] = []
    src_nums = _extract_num_tokens(source_text)
    new_nums = _extract_num_tokens(rewritten_text)
    dropped = sorted((src_nums - new_nums).elements())
    added = sorted((new_nums - src_nums).elements())
    if dropped:
        errors.append({"rule": "dropped_numbers", "issue": f"润色丢失或改变符号/频次的原文数值/单位：{dropped[:10]}"})
    if added:
        errors.append({"rule": "fabricated_numbers", "issue": f"润色凭空新增或篡改符号/频次的数值/单位：{added[:10]}"})

    # Detect metric-value swaps (e.g., swapping 研发费 and 设备费 amounts when both labels appear in source & rewrite)
    src_bind = _extract_metric_bindings(source_text)
    new_bind = _extract_metric_bindings(rewritten_text)
    swapped = []
    for label in sorted(set(src_bind) & set(new_bind)):
        if src_bind[label] != new_bind[label]:
            swapped.append(f"{label}: 原{list(src_bind[label].elements())} -> 改{list(new_bind[label].elements())}")
    if swapped:
        errors.append({"rule": "metric_value_swap", "issue": f"润色篡改或对调了指标对应数值：{swapped[:6]}"})

    # Detect cross-year swaps (e.g., swapping 2024 and 2025 R&D expense amounts)
    src_ybind = _extract_year_metric_bindings(source_text)
    new_ybind = _extract_year_metric_bindings(rewritten_text)
    year_swapped = []
    for key in sorted(set(src_ybind) & set(new_ybind)):
        if src_ybind[key] != new_ybind[key]:
            year_swapped.append(f"{key[0]}年{key[1]}: 原{list(src_ybind[key].elements())} -> 改{list(new_ybind[key].elements())}")
    if year_swapped:
        errors.append({"rule": "year_value_swap", "issue": f"润色跨年对调了指标对应数值：{year_swapped[:6]}"})

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
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            val = float(n.value)
            if not math.isfinite(val):
                raise ValueError(f"non-finite literal operand: {n.value}")
            return val
        if isinstance(n, ast.BinOp) and type(n.op) in _SAFE_OPS:
            left = _ev(n.left)
            right = _ev(n.right)
            if not (math.isfinite(left) and math.isfinite(right)):
                raise ValueError("non-finite operand in binary expression")
            res = float(_SAFE_OPS[type(n.op)](left, right))
            if not math.isfinite(res):
                raise ValueError(f"non-finite intermediate result: {res}")
            return res
        if isinstance(n, ast.UnaryOp) and type(n.op) in _SAFE_OPS:
            op_val = _ev(n.operand)
            if not math.isfinite(op_val):
                raise ValueError("non-finite operand in unary expression")
            res = float(_SAFE_OPS[type(n.op)](op_val))
            if not math.isfinite(res):
                raise ValueError(f"non-finite intermediate result: {res}")
            return res
        raise ValueError(f"unsupported expression node: {type(n).__name__}")

    out = _ev(node)
    if not math.isfinite(out):
        raise ValueError(f"non-finite result: {out}")
    return out


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

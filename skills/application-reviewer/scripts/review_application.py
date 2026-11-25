#!/usr/bin/env python3
"""
Unified Application Reviewer CLI (Consistency Check + Native DOCX Version Diff + Evidence Ledger Math Check + Strict Rewrite Fidelity).
Zero fake-strict gates: every real violation returns ok=False and exit code 2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
for cand in (SCRIPT_DIR, SKILL_ROOT.parent / "_core", SKILL_ROOT / "scripts" / "_core"):
    if cand.is_dir() and str(cand) not in sys.path:
        sys.path.insert(0, str(cand))

import doc_io  # noqa: E402
import fact_ledger  # noqa: E402
import quality_gate  # noqa: E402


def _read_doc_or_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        st = doc_io.extract_docx_structure(path)
        parts = [p["text"] for p in st["paragraphs"]]
        for tbl in st["tables"]:
            for row in tbl["rows"]:
                parts.append(row["joined"])
        return "\n".join(parts)
    return path.read_text(encoding="utf-8")


def verify_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    """Verify every computed claim arithmetically, check USCC/balance-sheet if present, and enforce source provenance."""
    errors: list[dict[str, Any]] = []
    checked_calcs = 0
    for idx, entry in enumerate(ledger.get("entries", [])):
        if not isinstance(entry, dict):
            errors.append({"index": idx, "rule": "schema", "issue": "台账条目必须为对象"})
            continue
        kind = str(entry.get("kind") or "fact").strip()
        if not entry.get("claim"):
            errors.append({"index": idx, "rule": "missing_claim", "issue": "缺少主张描述 claim"})
        if kind in {"fact", "computed"} and not entry.get("source"):
            errors.append({"index": idx, "rule": "missing_source", "issue": f"条目 {idx} ({kind}) 缺少可追溯来源 source"})
        if kind == "computed":
            formula = str(entry.get("formula") or "").strip()
            claimed = entry.get("claimed_value")
            if not formula or claimed is None:
                errors.append({"index": idx, "rule": "missing_formula", "issue": f"计算类条目 {idx} 缺少 formula 或 claimed_value"})
            else:
                checked_calcs += 1
                vc = quality_gate.verify_calculation_claim(formula, float(claimed))
                if not vc["ok"]:
                    errors.append({"index": idx, "rule": "calculation_mismatch", "issue": vc["error"], "detail": vc})
    if ledger.get("credit_code"):
        ok_u, msg_u = fact_ledger.validate_uscc(str(ledger["credit_code"]))
        if not ok_u:
            errors.append({"rule": "uscc", "issue": msg_u})
    bs = ledger.get("balance_sheet")
    if isinstance(bs, dict):
        ok_bs, msg_bs = fact_ledger.validate_balance_sheet(
            bs.get("total_assets"), bs.get("total_liabilities"), bs.get("total_equity")
        )
        if not ok_bs:
            errors.append({"rule": "balance_sheet", "issue": msg_bs})
    return {
        "ok": len(errors) == 0,
        "entry_count": len(ledger.get("entries", [])),
        "checked_calculations": checked_calcs,
        "error_count": len(errors),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="申报材料体检、原生DOCX版本对比、证据台账复算与润色保真硬门禁 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_c = sub.add_parser("check-consistency", help="检查申报材料（DOCX/MD/TXT）占位符、兜底词、串户、括号与密度")
    p_c.add_argument("file", type=Path)
    p_c.add_argument("--company", default="")
    p_c.add_argument("--min-chars", type=int, default=0)
    p_c.add_argument("--max-chars", type=int, default=0)
    p_c.add_argument("--require", action="append", default=[])
    p_c.add_argument("--blackboard", type=Path, default=None)

    p_d = sub.add_parser("diff-versions", help="原生对比两版 DOCX，识别章节/表格行移动与数字变化")
    p_d.add_argument("old_docx", type=Path)
    p_d.add_argument("new_docx", type=Path)

    p_l = sub.add_parser("verify-ledger", help="复算证据台账所有计算项、核验来源与信用代码/资产负债平衡")
    p_l.add_argument("ledger_json", type=Path)

    p_r = sub.add_parser("audit-rewrite", help="严格审计中文自然化润色稿（数值/工程单位/夸大宣称违规直接退出码2）")
    p_r.add_argument("source_file", type=Path)
    p_r.add_argument("rewritten_file", type=Path)
    p_r.add_argument("--max-chars", type=int, default=0)

    args = parser.parse_args()

    if args.cmd == "check-consistency":
        text = _read_doc_or_text(args.file)
        res = quality_gate.audit_formal_text(
            text,
            expected_company=args.company,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
            required_keywords=args.require,
        )
        if args.blackboard:
            bb = json.loads(args.blackboard.read_text(encoding="utf-8"))
            res["blackboard_reconciliation"] = fact_ledger.reconcile_text_against_estimates(bb, text)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 2

    if args.cmd == "diff-versions":
        res = doc_io.diff_docx_versions(args.old_docx, args.new_docx)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "verify-ledger":
        ledger = json.loads(args.ledger_json.read_text(encoding="utf-8"))
        res = verify_ledger(ledger)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 2

    if args.cmd == "audit-rewrite":
        src = _read_doc_or_text(args.source_file)
        new = _read_doc_or_text(args.rewritten_file)
        res = quality_gate.audit_rewrite_fidelity(src, new, max_chars=args.max_chars)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

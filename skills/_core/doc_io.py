#!/usr/bin/env python3
"""
Unified Document I/O, Tolerant Financial Workbook Reader, and Native DOCX Version Diff Engine.
Solves:
  - application-version-diff: native DOCX reading + SequenceMatcher moved-section & moved-table-row detection
  - financial-verification: tolerant synonym matching for real enterprise balance-sheet / income-statement Excel files
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

FINANCIAL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "revenue": ("营业收入", "营业总收入", "主营业务收入", "销售收入", "收入总额"),
    "rd_expense": ("研发费用", "研究开发费用", "研发投入", "研究与开发费用", "研发支出"),
    "net_profit": ("净利润", "归母净利润", "归属于母公司所有者的净利润"),
    "total_profit": ("利润总额",),
    "total_assets": ("资产总计", "资产总额", "总资产"),
    "total_liabilities": ("负债合计", "负债总额", "总负债"),
    "total_equity": ("所有者权益合计", "股东权益合计", "净资产", "所有者权益总额"),
    "tax_paid": ("实缴税费", "纳税总额", "缴纳税费", "实缴税金", "支付的各项税费"),
}

HEADING_PREFIX_RE = re.compile(r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、）)]|\(\d+\)|第[一二三四五六七八九十\d]+[章节条])\s*")


def extract_docx_structure(docx_path: Path) -> dict[str, Any]:
    """Extract ordered paragraphs and table rows directly from a DOCX file using stdlib zipfile+xml."""
    with zipfile.ZipFile(docx_path, "r") as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find(W_NS + "body")
    paragraphs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    p_idx = 0
    t_idx = 0
    if body is None:
        return {"file": str(docx_path), "paragraphs": [], "tables": []}

    for child in body:
        if child.tag == W_NS + "p":
            txt = "".join(t.text or "" for t in child.iter(W_NS + "t")).strip()
            if txt:
                p_idx += 1
                paragraphs.append({"index": p_idx, "text": txt, "core_text": HEADING_PREFIX_RE.sub("", txt).strip()})
        elif child.tag == W_NS + "tbl":
            t_idx += 1
            rows = []
            for r_i, tr in enumerate(child.findall(W_NS + "tr"), 1):
                cells = ["".join(t.text or "" for t in tc.iter(W_NS + "t")).strip() for tc in tr.findall(W_NS + "tc")]
                if any(cells):
                    rows.append({"row_index": r_i, "cells": cells, "joined": " | ".join(cells)})
            if rows:
                tables.append({"table_index": t_idx, "rows": rows})
    return {"file": str(docx_path), "paragraphs": paragraphs, "tables": tables}


def _strip_num_prefix(s: str) -> str:
    return re.sub(r"\s+", "", HEADING_PREFIX_RE.sub("", s or ""))


def _extract_numbers(s: str) -> list[str]:
    """Extract signed numbers (including minus, full-width －, and Chinese 负) so -120 -> 120 is detected."""
    raw = re.findall(r"(?:(?:[+\-−－]|负)\s*)?\d+(?:,\d{3})*(?:\.\d+)?%?", s or "")
    out = []
    for tok in raw:
        t = re.sub(r"\s+|,", "", tok).replace("−", "-").replace("－", "-")
        if t.startswith("负"):
            t = "-" + t[1:]
        out.append(t)
    return out


def diff_docx_versions(old_docx: Path, new_docx: Path, *, move_threshold: float = 0.78) -> dict[str, Any]:
    """Compare two DOCX versions natively, accurately detecting moved/reordered paragraphs & table rows."""
    old = extract_docx_structure(old_docx)
    new = extract_docx_structure(new_docx)

    old_paras = old["paragraphs"]
    new_paras = new["paragraphs"]
    matched_new: set[int] = set()
    unchanged = 0
    moved: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []

    # Pass 1: exact text match (detect unchanged vs pure move)
    new_by_text: dict[str, list[int]] = {}
    for i, np in enumerate(new_paras):
        new_by_text.setdefault(np["text"], []).append(i)

    unmatched_old: list[int] = []
    for oi, op in enumerate(old_paras):
        cands = [ni for ni in new_by_text.get(op["text"], []) if ni not in matched_new]
        if cands:
            ni = cands[0]
            matched_new.add(ni)
            if abs(oi - ni) >= 2:
                moved.append({"old_index": op["index"], "new_index": new_paras[ni]["index"], "text": op["text"][:120], "kind": "moved_exact"})
            else:
                unchanged += 1
        else:
            unmatched_old.append(oi)

    # Pass 2: fuzzy similarity match (detect renumbered/moved headings & modified paragraphs)
    for oi in unmatched_old:
        op = old_paras[oi]
        op_core = _strip_num_prefix(op["text"])
        best_ni = -1
        best_ratio = 0.0
        for ni, np in enumerate(new_paras):
            if ni in matched_new:
                continue
            np_core = _strip_num_prefix(np["text"])
            if not op_core or not np_core:
                continue
            # Fast length prefilter
            if min(len(op_core), len(np_core)) / max(len(op_core), len(np_core)) < 0.45:
                continue
            ratio = SequenceMatcher(None, op_core, np_core).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_ni = ni
        if best_ni >= 0 and best_ratio >= move_threshold:
            matched_new.add(best_ni)
            np = new_paras[best_ni]
            nums_old, nums_new = _extract_numbers(op["text"]), _extract_numbers(np["text"])
            is_moved = abs(oi - best_ni) >= 2 or (op["text"] != np["text"] and op_core == _strip_num_prefix(np["text"]))
            rec = {
                "old_index": op["index"],
                "new_index": np["index"],
                "similarity": round(best_ratio, 3),
                "old_text": op["text"][:140],
                "new_text": np["text"][:140],
                "number_changed": nums_old != nums_new,
                "old_numbers": nums_old[:6],
                "new_numbers": nums_new[:6],
            }
            if is_moved:
                rec["kind"] = "moved_and_renumbered" if op_core == _strip_num_prefix(np["text"]) else "moved_and_modified"
                moved.append(rec)
            else:
                modified.append(rec)
        else:
            deleted.append({"old_index": op["index"], "text": op["text"][:140]})

    added = [{"new_index": np["index"], "text": np["text"][:140]} for ni, np in enumerate(new_paras) if ni not in matched_new]

    # Table row reorder, in-place modification, AND unmatched added/deleted row & table detection
    table_row_moves: list[dict[str, Any]] = []
    table_row_changes: list[dict[str, Any]] = []
    table_rows_added: list[dict[str, Any]] = []
    table_rows_deleted: list[dict[str, Any]] = []
    table_numeric_changes = 0

    def _row_sig(cells: list[str]) -> str:
        body = cells[1:] if len(cells) >= 2 and re.fullmatch(r"\d+", cells[0].strip()) else cells
        return re.sub(r"\s+", "", "|".join(body))

    max_tables = max(len(old["tables"]), len(new["tables"]))
    for t_i in range(max_tables):
        orows = old["tables"][t_i]["rows"] if t_i < len(old["tables"]) else []
        nrows = new["tables"][t_i]["rows"] if t_i < len(new["tables"]) else []

        # Exact signature matching first (handles moved rows without misclassifying them as added/deleted)
        new_sig_buckets: dict[str, list[int]] = {}
        for ni, nr in enumerate(nrows):
            s = _row_sig(nr["cells"])
            if s:
                new_sig_buckets.setdefault(s, []).append(ni)

        matched_old_rows: set[int] = set()
        matched_new_rows: set[int] = set()
        for oi, orow in enumerate(orows):
            s = _row_sig(orow["cells"])
            cands = [ni for ni in new_sig_buckets.get(s, []) if ni not in matched_new_rows]
            if cands:
                ni = cands[0]
                matched_old_rows.add(oi)
                matched_new_rows.add(ni)
                if nrows[ni]["row_index"] != orow["row_index"]:
                    table_row_moves.append({
                        "table_index": t_i + 1,
                        "old_row": orow["row_index"],
                        "new_row": nrows[ni]["row_index"],
                        "preview": orow["joined"][:120],
                    })

        # Pair unmatched rows at identical row positions (in-place edits) vs unmatched tail/extra rows (added/deleted)
        unmatched_o = [oi for oi in range(len(orows)) if oi not in matched_old_rows]
        unmatched_n = [ni for ni in range(len(nrows)) if ni not in matched_new_rows]
        paired_o: set[int] = set()
        paired_n: set[int] = set()

        for oi in unmatched_o:
            if oi in unmatched_n and oi not in paired_n:
                paired_o.add(oi)
                paired_n.add(oi)
                oc, nc = orows[oi]["cells"], nrows[oi]["cells"]
                onums, nnums = _extract_numbers(" ".join(oc)), _extract_numbers(" ".join(nc))
                num_changed = onums != nnums
                if num_changed:
                    table_numeric_changes += 1
                table_row_changes.append({
                    "table_index": t_i + 1,
                    "row_index": oi + 1,
                    "old_row": orows[oi]["joined"][:140],
                    "new_row": nrows[oi]["joined"][:140],
                    "number_changed": num_changed,
                    "old_numbers": onums[:6],
                    "new_numbers": nnums[:6],
                })

        for oi in unmatched_o:
            if oi not in paired_o:
                onums = _extract_numbers(" ".join(orows[oi]["cells"]))
                if onums:
                    table_numeric_changes += 1
                table_rows_deleted.append({
                    "table_index": t_i + 1,
                    "old_row": orows[oi]["row_index"],
                    "row": orows[oi]["joined"][:140],
                    "number_changed": bool(onums),
                    "old_numbers": onums[:6],
                })

        for ni in unmatched_n:
            if ni not in paired_n:
                nnums = _extract_numbers(" ".join(nrows[ni]["cells"]))
                if nnums:
                    table_numeric_changes += 1
                table_rows_added.append({
                    "table_index": t_i + 1,
                    "new_row": nrows[ni]["row_index"],
                    "row": nrows[ni]["joined"][:140],
                    "number_changed": bool(nnums),
                    "new_numbers": nnums[:6],
                })

    para_added_nums = sum(1 for a in added if _extract_numbers(a["text"]))
    para_deleted_nums = sum(1 for d in deleted if _extract_numbers(d["text"]))

    return {
        "old_file": str(old_docx),
        "new_file": str(new_docx),
        "summary": {
            "unchanged_paragraphs": unchanged,
            "moved_paragraphs": len(moved),
            "modified_paragraphs": len(modified),
            "deleted_paragraphs": len(deleted),
            "added_paragraphs": len(added),
            "moved_table_rows": len(table_row_moves),
            "modified_table_rows": len(table_row_changes),
            "added_table_rows": len(table_rows_added),
            "deleted_table_rows": len(table_rows_deleted),
            "numeric_changes": sum(1 for m in modified + moved if m.get("number_changed")) + para_added_nums + para_deleted_nums + table_numeric_changes,
        },
        "moved": moved[:50],
        "modified": modified[:50],
        "deleted": deleted[:50],
        "added": added[:50],
        "table_row_moves": table_row_moves[:50],
        "table_row_changes": table_row_changes[:50],
        "table_rows_added": table_rows_added[:50],
        "table_rows_deleted": table_rows_deleted[:50],
    }


SKIP_HEADER_LABELS = {"行次", "序号", "编号", "附注", "栏次", "代码", "科目代码"}
AMOUNT_HEADER_HINTS = ("金额", "余额", "发生额", "期末", "期初", "年初", "年末", "本期", "上期", "本年", "上年", "数额")


def _is_financial_data_row(row: list[Any], skip_cols: set[int]) -> bool:
    first_text = "".join(str(c or "") for c in row[:2] if isinstance(c, str)).strip()
    compact = re.sub(r"[\s（）()：:、]", "", first_text)
    if compact and any(any(s in compact for s in syns) for syns in FINANCIAL_SYNONYMS.values()):
        return True
    has_num = any(
        isinstance(c, (int, float)) and not isinstance(c, bool)
        for ci, c in enumerate(row[1:], 1)
        if ci not in skip_cols
    )
    return has_num


def read_financial_excel_tolerant(xlsx_path: Path) -> dict[str, Any]:
    """Read financial metrics from real-world Excel workbooks using actual header row detection (up to row 30) and strict skip_cols."""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    extracted: list[dict[str, Any]] = []
    for sname in wb.sheetnames:
        ws = wb[sname]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        # Scan up to top 30 rows to locate actual header row(s), stopping once financial data rows begin
        year_cols: dict[int, int] = {}
        skip_cols: set[int] = set()
        amount_cols: set[int] = set()
        header_row_idx = -1
        for ri, r in enumerate(rows[:30]):
            if _is_financial_data_row(r, skip_cols):
                break
            row_has_header_cue = False
            for ci, cell in enumerate(r):
                s = re.sub(r"\s+", "", str(cell or ""))
                if not s:
                    continue
                if s in SKIP_HEADER_LABELS:
                    skip_cols.add(ci)
                    row_has_header_cue = True
                m = re.search(r"(20\d{2})", s)
                if m:
                    year_cols.setdefault(ci, int(m.group(1)))
                    amount_cols.add(ci)
                    row_has_header_cue = True
                if any(h in s for h in AMOUNT_HEADER_HINTS):
                    amount_cols.add(ci)
                    row_has_header_cue = True
            if row_has_header_cue:
                header_row_idx = ri
        amount_cols -= skip_cols
        for ri, r in enumerate(rows, 1):
            if header_row_idx >= 0 and (ri - 1) <= header_row_idx:
                continue
            # Build row label from text columns (excluding numeric-only cells and skip_cols)
            label_parts = []
            for ci, c in enumerate(r[:3]):
                if ci in skip_cols:
                    continue
                if isinstance(c, str) and c.strip():
                    label_parts.append(c.strip())
            row_label = "".join(label_parts).strip()
            compact_label = re.sub(r"[\s（）()：:、]", "", row_label)
            if not compact_label:
                continue
            for metric, syns in FINANCIAL_SYNONYMS.items():
                if any(s in compact_label for s in syns):
                    for ci, cell in enumerate(r[1:], 1):
                        if ci in skip_cols:
                            continue
                        if amount_cols and ci not in amount_cols:
                            continue
                        if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                            extracted.append({
                                "sheet": sname,
                                "row": ri,
                                "label": row_label[:40],
                                "metric": metric,
                                "year": year_cols.get(ci),
                                "value": round(float(cell), 4),
                            })
                    break
    return {"file": str(xlsx_path), "count": len(extracted), "items": extracted}


def main() -> int:
    parser = argparse.ArgumentParser(description="统一文档抽取与原生 DOCX 版本对比工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_diff = sub.add_parser("diff-docx", help="原生对比两版 DOCX，精准识别章节/表格行移动与数字变化")
    p_diff.add_argument("old_docx", type=Path)
    p_diff.add_argument("new_docx", type=Path)

    p_fin = sub.add_parser("read-excel", help="宽容提取真实企业财务 Excel 核心科目")
    p_fin.add_argument("xlsx", type=Path)

    args = parser.parse_args()
    if args.cmd == "diff-docx":
        print(json.dumps(diff_docx_versions(args.old_docx, args.new_docx), ensure_ascii=False, indent=2))
    elif args.cmd == "read-excel":
        print(json.dumps(read_financial_excel_tolerant(args.xlsx), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

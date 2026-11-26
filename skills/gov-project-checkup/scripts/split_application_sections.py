#!/usr/bin/env python3
"""Split an uploaded application (docx/doc/wps/pdf/md/txt) into the standard 10 chapters,
detect the base year (Y/Y-1/Y-2), and measure the four key narrative boxes.

Output is a JSON dict consumed by the six-chapter material checkup flow.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

# Order matters: later headings bound the previous chapter.
SECTIONS: list[tuple[str, str]] = [
    ("basic_info", r"一\s*、\s*企\s*业\s*基\s*本\s*情\s*况"),
    ("economic_benefits", r"二\s*、\s*经\s*济\s*效\s*益"),
    ("professionalism", r"三\s*、\s*专\s*业\s*化"),
    ("refinement", r"四\s*、\s*精\s*细\s*化"),
    ("specialization", r"五\s*、\s*特\s*色\s*化"),
    ("innovation", r"六\s*、\s*创\s*新\s*能\s*力"),
    ("industry_chain", r"七\s*、\s*产\s*业\s*链\s*配\s*套"),
    ("product_field", r"八\s*、\s*主\s*导\s*产\s*品\s*所\s*属\s*领\s*域"),
    ("others", r"九\s*、\s*其\s*他"),
    ("summary_intro", r"企\s*业\s*总\s*体\s*情\s*况\s*简\s*要\s*介\s*绍"),
]
SECTION_LABELS = {
    "basic_info": "一、企业基本情况",
    "economic_benefits": "二、经济效益和经营情况",
    "professionalism": "三、专业化",
    "refinement": "四、精细化",
    "specialization": "五、特色化",
    "innovation": "六、创新能力",
    "industry_chain": "七、产业链配套",
    "product_field": "八、主导产品所属领域",
    "others": "九、其他",
    "summary_intro": "企业总体情况简要介绍",
}

# Narrative boxes: (key, start anchor, end anchors, char limit, must be anonymous)
NARRATIVE_BOXES: list[tuple[str, str, list[str], int, bool]] = [
    ("market_share_note", r"细分市场占有率情况介绍|占有率情况说明|占有率情况介绍", [r"主导产品出口额", r"企业自有品牌", r"六\s*、\s*创\s*新"], 1000, False),
    ("research_results", r"研究领域已获得成果及应用情况", [r"相关指标", r"研发费用总额"], 300, False),
    ("gap_filling_note", r"说明[（(]是否在细分领域实现关键技术首创等情况", [r"主导产品是否为国内外知名大企业", r"行业领军企业"], 300, True),
    ("summary_intro", r"请勿另附页[）)]?", [r"真实性声明", r"十\s*、\s*初核推荐"], 2000, True),
]


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    raw = path.read_bytes()
    if suffix == ".docx" or (zipfile.is_zipfile(path) and suffix in {".docx", ".wps"}):
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"</w:tc>", " | ", xml)
        return re.sub(r"<[^>]+>", "", xml)
    if suffix in {".wps", ".xml"} and (raw[:5] == b"<?xml" or b"<w:wordDocument" in raw[:4000]):
        xml = raw.decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"</w:tc>", " | ", xml)
        return re.sub(r"<[^>]+>", "", xml)
    if suffix == ".pdf":
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if suffix in {".doc", ".wps", ".rtf"}:
        with tempfile.NamedTemporaryFile(suffix=".txt") as tf:
            subprocess.run(["textutil", "-convert", "txt", "-output", tf.name, str(path)], check=False, capture_output=True)
            return Path(tf.name).read_text(encoding="utf-8", errors="ignore")
    return raw.decode("utf-8", errors="ignore")


def _clean(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\u2028", "\n")
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def detect_base_year(text: str) -> dict[str, Any]:
    """Y = rightmost (latest) full year appearing in the economic table header region."""
    region = text
    m = re.search(SECTIONS[1][1], text)
    if m:
        region = text[m.start(): m.start() + 3000]
    years = [int(y) for y in re.findall(r"(20[1-3]\d)\s*年", region)]
    if not years:
        return {"Y": None, "Y-1": None, "Y-2": None, "detected_from": "none"}
    y = max(years)
    return {"Y": y, "Y-1": y - 1, "Y-2": y - 2, "detected_from": "economic_table" if m else "full_text"}


def split_sections(text: str) -> dict[str, dict[str, Any]]:
    hits: list[tuple[int, str]] = []
    for key, pattern in SECTIONS:
        found = None
        for mm in re.finditer(pattern, text):
            found = mm  # keep last real heading occurrence after cover/notes
            if key != "summary_intro":
                break
        if found:
            hits.append((found.start(), key))
    hits.sort()
    out: dict[str, dict[str, Any]] = {}
    for idx, (pos, key) in enumerate(hits):
        end = hits[idx + 1][0] if idx + 1 < len(hits) else len(text)
        body = text[pos:end].strip()
        out[key] = {"label": SECTION_LABELS[key], "chars": len(re.sub(r"\s+", "", body)), "text": body}
    for key, _ in SECTIONS:
        out.setdefault(key, {"label": SECTION_LABELS[key], "chars": 0, "text": "", "missing": True})
    return out


def extract_boxes(text: str, company: str = "", aliases: list[str] | None = None) -> dict[str, Any]:
    names = [n for n in [company, *(aliases or [])] if n]
    short = []
    for n in names:
        core = re.sub(r"(股份)?有限(责任)?公司$", "", n)
        core = re.sub(r"^(浙江|杭州|江苏|上海|宁波|温州|嘉兴|湖州|绍兴|金华|衢州|舟山|台州|丽水|盐城|苏州|无锡|南京)(省|市)?", "", core)
        if len(core) >= 2:
            short.append(core[:4])
            short.append(core[:2] if len(core) >= 4 else core)
    leak_terms = sorted({t for t in names + short if t and len(t) >= 2}, key=len, reverse=True)
    boxes: dict[str, Any] = {}
    for key, start, ends, limit, anon in NARRATIVE_BOXES:
        sm = None
        for mm in re.finditer(start, text):
            sm = mm
        if not sm:
            boxes[key] = {"found": False, "limit": limit, "anonymous_required": anon}
            continue
        tail = text[sm.end():]
        cut = len(tail)
        for e in ends:
            em = re.search(e, tail)
            if em:
                cut = min(cut, em.start())
        body = tail[:cut].strip(" ：:）)\n")
        chars = len(re.sub(r"\s+", "", body))
        leaks = [t for t in leak_terms if t in body] if anon else []
        boxes[key] = {
            "found": True,
            "limit": limit,
            "chars": chars,
            "over_limit": chars > limit,
            "anonymous_required": anon,
            "name_leaks": leaks,
            "text": body,
        }
    return boxes


def run(path: Path, company: str = "", aliases: list[str] | None = None) -> dict[str, Any]:
    text = _clean(_read_text(path))
    sections = split_sections(text)
    return {
        "file": str(path),
        "total_chars": len(re.sub(r"\s+", "", text)),
        "base_year": detect_base_year(text),
        "sections": sections,
        "missing_sections": [SECTION_LABELS[k] for k, v in sections.items() if v.get("missing")],
        "narrative_boxes": extract_boxes(text, company, aliases),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="将已填申报书切分为十大章节并测量四大叙事栏位")
    ap.add_argument("file", type=Path)
    ap.add_argument("--company", default="", help="企业全称，用于匿名栏泄露检查")
    ap.add_argument("--alias", action="append", default=[], help="曾用名或简称，可重复")
    ap.add_argument("--no-text", action="store_true", help="输出时省略正文，只保留统计")
    args = ap.parse_args()
    if not args.file.exists():
        print(json.dumps({"ok": False, "error": f"文件不存在：{args.file}"}, ensure_ascii=False))
        return 2
    res = run(args.file, args.company, args.alias)
    if args.no_text:
        for v in res["sections"].values():
            v.pop("text", None)
        for v in res["narrative_boxes"].values():
            v.pop("text", None)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

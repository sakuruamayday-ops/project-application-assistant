#!/usr/bin/env python3
import argparse
import json
import re
import zipfile
from pathlib import Path

TOKENS = {
    "tables": "<w:tbl>",
    "textboxes": "txbxContent",
    "omath": "<m:oMath>",
    "drawings": "<w:drawing",
    "vml_pict": "<w:pict",
    "comment_start": "commentRangeStart",
    "comment_end": "commentRangeEnd",
    "comment_ref": "commentReference",
}

def inspect(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        xml = "".join(z.read(x).decode("utf-8", "ignore") for x in names if x.endswith(".xml"))
        document_xml = z.read("word/document.xml").decode("utf-8", "ignore")
        comments_xml = (
            z.read("word/comments.xml").decode("utf-8", "ignore")
            if "word/comments.xml" in names else ""
        )
        comment_ids = sorted(set(re.findall(r'<w:comment\b[^>]*\bw:id="(-?\d+)"', comments_xml)))
        start_ids = sorted(set(re.findall(r'<w:commentRangeStart\b[^>]*\bw:id="(-?\d+)"', document_xml)))
        end_ids = sorted(set(re.findall(r'<w:commentRangeEnd\b[^>]*\bw:id="(-?\d+)"', document_xml)))
        ref_ids = sorted(set(re.findall(r'<w:commentReference\b[^>]*\bw:id="(-?\d+)"', document_xml)))
        result = {
            "path": str(Path(path).resolve()),
            "parts": len(names),
            "part_names": names,
            "media": sum(x.startswith("word/media/") for x in names),
            "comments_part": "word/comments.xml" in names,
            "footnotes_part": "word/footnotes.xml" in names,
            "endnotes_part": "word/endnotes.xml" in names,
            "comment_id_sets": {
                "comments": comment_ids,
                "range_start": start_ids,
                "range_end": end_ids,
                "reference": ref_ids,
            },
            "comments_wired": (
                bool(comment_ids)
                and comment_ids == start_ids == end_ids == ref_ids
            ) if comments_xml else True,
        }
        result.update({k: xml.count(v) for k, v in TOKENS.items()})
        return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("--compare")
    p.add_argument("--out")
    a = p.parse_args()
    current = inspect(a.input)
    payload = {"current": current}
    if a.compare:
        base = inspect(a.compare)
        payload["base"] = base
        payload["missing_parts"] = sorted(set(base["part_names"]) - set(current["part_names"]))
        payload["preservation"] = {
            key: current[key] >= base[key]
            for key in ("media", "tables", "textboxes", "drawings", "vml_pict")
        }
        payload["pass"] = not payload["missing_parts"] and all(payload["preservation"].values())
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    if a.compare and not payload["pass"]:
        raise SystemExit(4)

if __name__ == "__main__":
    main()

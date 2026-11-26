#!/usr/bin/env python3
import argparse
import json
from datetime import date

ROUTES = {
    "comprehensive": ("patent-strategy-assistant", ["P1", "P2", "P3"]),
    "search": ("patent-strategy-assistant", ["P1"]),
    "patentability": ("patent-strategy-assistant", ["P1"]),
    "claims": ("patent-strategy-assistant", ["P1"]),
    "fto": ("patent-strategy-assistant", ["P1"]),
    "layout": ("patent-strategy-assistant", ["P2"]),
    "mining": ("patent-strategy-assistant", ["P2"]),
    "disclosure": ("patent-strategy-assistant", ["P2"]),
    "ai_patent": ("patent-strategy-assistant", ["TECHNICAL_FEATURE_MAP", "P1", "P2"]),
    "preexam": ("patent-strategy-assistant", ["P3"]),
    "review": ("patent-docx-reviewer", ["DOCUMENT_REVIEW"]),
    "project": ("patent-strategy-assistant", ["PROJECT_LINK"]),
}

PREEXAM_CENTER_POOL = [
    {
        "official_name": "浙江省知识产权保护中心",
        "dataset_key": "浙江省知识产权保护中心",
    },
    {
        "official_name": "杭州市知识产权保护中心",
        "dataset_key": "中国（杭州）知识产权保护中心",
    },
]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--intent", required=True, choices=ROUTES)
    p.add_argument("--jurisdiction", default="中国")
    p.add_argument("--cutoff", default=date.today().isoformat())
    p.add_argument("--source", action="append", default=[])
    p.add_argument("--confidentiality", default="内部")
    p.add_argument("--target-center")
    p.add_argument("--out")
    a = p.parse_args()
    missing = []
    if not str(a.jurisdiction or "").strip():
        missing.append("jurisdiction")
    if not a.cutoff:
        missing.append("cutoff_date")
    else:
        try:
            date.fromisoformat(str(a.cutoff)[:10])
        except ValueError:
            missing.append(f"invalid_cutoff_date:{a.cutoff}")
    if not a.source:
        missing.append("evidence_sources")
    skill, phases = ROUTES[a.intent]
    record = {
        "schema_version": "1.0",
        "status": "BLOCKED" if missing else "READY",
        "missing": missing,
        "primary_intent": a.intent,
        "active_phases": phases,
        "active_skill": skill,
        "jurisdiction": a.jurisdiction,
        "target_center": a.target_center,
        "configured_preexam_center_pool": PREEXAM_CENTER_POOL,
        "cutoff_date": a.cutoff,
        "evidence_sources": a.source,
        "confidentiality": a.confidentiality,
        "mutual_exclusion": "integrated_analysis_or_document_review",
        "out_of_scope": ["software_copyright_registration_materials"],
        "target_center_required_when": "formal_preexam_submission_check; recommendation may compare candidate pool first",
    }
    payload = json.dumps(record, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
    print(payload)
    raise SystemExit(2 if missing else 0)

if __name__ == "__main__":
    main()

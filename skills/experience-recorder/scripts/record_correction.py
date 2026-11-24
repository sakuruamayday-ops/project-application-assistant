#!/usr/bin/env python3
"""Append a normalized, non-sensitive correction signal to a local JSONL ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="记录脱敏纠正信号")
    parser.add_argument("--skill", required=True)
    parser.add_argument("--rule-key", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--category", default="quality")
    parser.add_argument("--severity", choices=("low", "medium", "high", "critical"), default="medium")
    parser.add_argument("--source", default="user-correction")
    parser.add_argument("--verified", action="store_true")
    parser.add_argument("--output", type=Path, default=Path.home() / ".config" / "project-assistant" / "evolution" / "corrections.jsonl")
    args = parser.parse_args()

    summary = " ".join(args.summary.split())
    payload = "|".join((args.task_id, args.skill, args.rule_key, summary))
    record = {
        "id": hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "task_id": args.task_id,
        "skill": args.skill,
        "rule_key": args.rule_key,
        "category": args.category,
        "severity": args.severity,
        "summary": summary,
        "source": args.source,
        "verified": args.verified,
        "sensitive": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    if args.output.is_file():
        for raw in args.output.read_text(encoding="utf-8").splitlines():
            try:
                existing_ids.add(str(json.loads(raw).get("id") or ""))
            except json.JSONDecodeError:
                continue
    if record["id"] not in existing_ids:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "id": record["id"], "appended": record["id"] not in existing_ids}, ensure_ascii=False))


if __name__ == "__main__":
    main()

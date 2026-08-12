#!/usr/bin/env python3
"""Record de-identified feedback for controlled skill evolution."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_OUTPUT = (
    Path(os.environ.get("GONGCHUANG_SKILL_DATA_DIR", Path.home() / ".config" / "gongchuang-skills"))
    / "gongchuang-humanizer-zh"
    / "evolution-feedback.jsonl"
)


def parse_candidate(value: str) -> dict:
    name, separator, score = value.rpartition(":")
    if not separator or not name:
        raise argparse.ArgumentTypeError("候选格式应为 名称:分数")
    try:
        number = float(score)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("候选分数必须是数字") from exc
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("候选分数必须在 0 至 100 之间")
    return {"name": name, "score": number}


def source_hash(source_file: str | None, source_hash_value: str | None) -> str:
    if source_hash_value:
        normalized = source_hash_value.lower()
        if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError("source-sha256 必须是 64 位十六进制字符串")
        return normalized
    if not source_file:
        raise ValueError("必须提供 source-file 或 source-sha256")
    return hashlib.sha256(Path(source_file).read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="记录去 AI 味技能的脱敏评测反馈")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--field", default="通用文本")
    parser.add_argument("--source-file")
    parser.add_argument("--source-sha256")
    parser.add_argument("--candidate", action="append", type=parse_candidate, required=True)
    parser.add_argument("--winner", required=True)
    parser.add_argument("--issue", action="append", default=[])
    parser.add_argument("--note", default="")
    parser.add_argument("--fail-gate", action="append", choices=["fact_lock", "required_narrative", "format", "cross_consistency"], default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    names = {item["name"] for item in args.candidate}
    if args.winner not in names:
        parser.error("winner 必须与某个 candidate 名称一致")

    try:
        digest = source_hash(args.source_file, args.source_sha256)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    gates = {name: name not in args.fail_gate for name in ["fact_lock", "required_narrative", "format", "cross_consistency"]}
    entry = {
        "case_id": args.case_id,
        "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "domain": args.domain,
        "field": args.field,
        "source_sha256": digest,
        "candidates": args.candidate,
        "winner": args.winner,
        "issues": args.issue,
        "hard_gates": gates,
        "note": args.note,
        "raw_text_stored": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"已记录脱敏反馈：{args.case_id} -> {args.output}")


if __name__ == "__main__":
    main()

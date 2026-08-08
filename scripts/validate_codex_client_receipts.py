#!/usr/bin/env python3
"""Validate and aggregate Codex desktop-client Skill evaluation receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_PHASES = ("implicit", "explicit", "negative", "functional")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output")
    options = parser.parse_args()
    run_dir = Path(options.run_dir).expanduser().resolve()
    manifest = load(run_dir / "run-manifest.json")
    receipts_dir = run_dir / "receipts"
    errors: list[str] = []
    results = []

    for record in manifest.get("skills") or []:
        skill = record["skill"]
        matches = list(receipts_dir.glob(f"*-{skill}.json"))
        if len(matches) != 1:
            errors.append(f"{skill}: expected exactly one receipt, got {len(matches)}")
            continue
        receipt = load(matches[0])
        phases = receipt.get("phases") or {}
        phase_results = {}
        for phase in EXPECTED_PHASES:
            item = phases.get(phase)
            if not isinstance(item, dict):
                errors.append(f"{skill}/{phase}: missing phase receipt")
                continue
            for field in (
                "thread_id",
                "prompt_sha256",
                "assistant_text_sha256",
                "status",
                "target_skill_observed",
            ):
                if field not in item:
                    errors.append(f"{skill}/{phase}: missing {field}")
            expected_target = phase != "negative"
            target_observed = item.get("target_skill_observed") is True
            passed = (
                item.get("status") == "completed"
                and target_observed == expected_target
                and item.get("verification_status") == "pass"
            )
            if not passed:
                errors.append(f"{skill}/{phase}: verification failed")
            phase_results[phase] = {
                "status": "pass" if passed else "fail",
                "thread_id": item.get("thread_id"),
            }
        results.append(
            {
                "skill": skill,
                "status": (
                    "pass"
                    if len(phase_results) == len(EXPECTED_PHASES)
                    and all(v["status"] == "pass" for v in phase_results.values())
                    else "fail"
                ),
                "phases": phase_results,
            }
        )

    report = {
        "schema_version": 1,
        "run_id": manifest.get("run_id"),
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": "pass" if not errors and len(results) == 49 else "fail",
        "skill_count": len(results),
        "expected_skill_count": 49,
        "expected_phase_count": 4,
        "expected_receipt_count": 196,
        "compression_risk_tested": any(
            item.get("phases", {}).get("implicit", {}).get("status") == "pass"
            for item in results
        ),
        "errors": errors,
        "results": results,
    }
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
    report["report_sha256"] = hashlib.sha256(canonical).hexdigest()
    output = (
        Path(options.output).expanduser().resolve()
        if options.output
        else run_dir / "codex-client-49-skill-report.json"
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

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
    expected_skill_count = len(manifest.get("skills") or [])
    expected_receipt_count = expected_skill_count * len(EXPECTED_PHASES)
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
        if receipt.get("candidate_skill_tree_sha256") != record.get("tree_sha256"):
            errors.append(f"{skill}: candidate skill tree hash mismatch")
        index = int(receipt.get("index") or 0)
        replacement_case = receipt.get("replacement_case_file")
        if replacement_case:
            replacement_case = str(replacement_case)
            if Path(replacement_case).name != replacement_case:
                errors.append(f"{skill}: invalid replacement case path")
                continue
            case_path = run_dir / "replacements" / replacement_case
        else:
            case_path = run_dir / "cases" / f"{index:02d}-{skill}.json"
        if not case_path.is_file():
            errors.append(f"{skill}: missing bound case file")
            continue
        case = load(case_path)
        expected_negative_skill = case.get("negative_expected_skill")
        expected_implicit_behavior = case.get("implicit_expected_behavior") or "triggered"
        expected_negative_behavior = case.get("negative_expected_behavior") or (
            "rerouted" if expected_negative_skill else "not_triggered"
        )
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
            expected_prompt_sha256 = (case.get("prompt_sha256") or {}).get(phase)
            if item.get("prompt_sha256") != expected_prompt_sha256:
                errors.append(f"{skill}/{phase}: prompt hash mismatch")
            expected_target = (
                False
                if phase == "implicit" and expected_implicit_behavior == "not_triggered"
                else phase != "negative"
                or expected_negative_behavior == "refused_in_scope"
            )
            target_observed = item.get("target_skill_observed") is True
            negative_semantics_ok = True
            if phase == "negative":
                observed_behavior = item.get("negative_behavior") or (
                    "refused_in_scope"
                    if target_observed and expected_negative_skill == skill
                    else "rerouted"
                    if item.get("expected_alternative_skill")
                    else "not_triggered"
                )
                negative_semantics_ok = observed_behavior == expected_negative_behavior
                if expected_negative_behavior in {"rerouted", "refused_in_scope"}:
                    negative_semantics_ok = (
                        negative_semantics_ok
                        and item.get("expected_alternative_skill")
                        == expected_negative_skill
                    )
                else:
                    negative_semantics_ok = (
                        negative_semantics_ok
                        and item.get("expected_alternative_skill") is None
                    )
            passed = (
                item.get("status") == "completed"
                and target_observed == expected_target
                and item.get("prompt_sha256") == expected_prompt_sha256
                and negative_semantics_ok
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
        "status": "pass" if not errors and len(results) == expected_skill_count else "fail",
        "skill_count": len(results),
        "expected_skill_count": expected_skill_count,
        "expected_phase_count": 4,
        "expected_receipt_count": expected_receipt_count,
        "compression_risk_tested": len(results) == expected_skill_count and all(
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
        else run_dir / "codex-client-full-suite-report.json"
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

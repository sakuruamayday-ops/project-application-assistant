#!/usr/bin/env python3
"""Bind a 24-sample visual review to an automated WorkBuddy candidate run."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


REQUIRED_CHECKS = (
    "no_missing_glyphs",
    "no_overlap",
    "no_clipping",
    "tables_readable",
    "watermark_visible",
    "hierarchy_clear",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pipeline_constants(repo_root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    path = repo_root / "scripts/run_workbuddy_report_candidate_pipeline.py"
    spec = importlib.util.spec_from_file_location("candidate_pipeline_constants", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载候选流水线:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module.PROJECT_IDS), tuple(module.REPORT_TYPES)


def finalize_visual_review(
    *,
    repo_root: Path,
    pipeline_receipt: Path,
    checklist_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"拒绝覆盖视觉回执:{output_path}")
    pipeline = json.loads(pipeline_receipt.read_text(encoding="utf-8"))
    checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
    if pipeline.get("schema") != "gongchuang-workbuddy-report-candidate-pipeline/v1":
        raise ValueError("候选流水线回执schema不匹配")
    if pipeline.get("automated_gate_status") != "pass":
        raise ValueError("自动化候选门禁未通过")
    if pipeline.get("candidate_state") != "pending-visual-review":
        raise ValueError("候选状态不是待视觉复核")
    if checklist.get("schema") != "gongchuang-report-visual-review/v1":
        raise ValueError("视觉检查表schema不匹配")
    release_tag = str(pipeline.get("release_tag") or "")
    if str(checklist.get("release_tag") or "") != release_tag:
        raise ValueError("视觉检查表版本不匹配")
    contact = pipeline.get("contact_sheet")
    if not isinstance(contact, dict):
        raise ValueError("候选回执缺联系表")
    if contact.get("sample_count") != 24:
        raise ValueError("视觉联系表样本数不是24")
    contact_path = Path(str(contact.get("path") or "")).expanduser().resolve()
    if not contact_path.is_file():
        raise FileNotFoundError(contact_path)
    actual_hash = sha256_file(contact_path)
    expected_hash = str(contact.get("sha256") or "")
    if actual_hash != expected_hash or str(checklist.get("contact_sheet_sha256") or "") != actual_hash:
        raise ValueError("视觉联系表哈希不闭环")
    reviewer = str(checklist.get("reviewer") or "").strip()
    review_method = str(checklist.get("review_method") or "").strip()
    reviewed_at = str(checklist.get("reviewed_at") or "").strip()
    if not reviewer or not review_method or not reviewed_at:
        raise ValueError("视觉检查表缺复核人、复核方式或时间")
    project_ids, report_types = load_pipeline_constants(repo_root)
    expected_items = [(project_id, report_type) for project_id in project_ids for report_type in report_types]
    items = checklist.get("items")
    if not isinstance(items, list):
        raise ValueError("视觉检查表items必须为数组")
    actual_items = [
        (str(item.get("project_id") or ""), str(item.get("report_type") or ""))
        for item in items
        if isinstance(item, dict)
    ]
    if actual_items != expected_items:
        raise ValueError("视觉检查必须按受控顺序恰好覆盖12类双报告")
    failures: list[str] = []
    for item in items:
        identity = f"{item['project_id']}/{item['report_type']}"
        if item.get("status") != "pass":
            failures.append(identity + ":status")
        checks = item.get("checks")
        if not isinstance(checks, dict):
            failures.append(identity + ":checks")
            continue
        for check in REQUIRED_CHECKS:
            if checks.get(check) is not True:
                failures.append(identity + ":" + check)
    if failures:
        raise ValueError("视觉抽检未通过:" + "、".join(failures))
    result = {
        "schema": "gongchuang-workbuddy-report-candidate-visual-final/v1",
        "status": "pass",
        "release_tag": release_tag,
        "source_commit": pipeline.get("source_commit"),
        "candidate_state": "ready-for-real-host-testing",
        "candidate_only": True,
        "formal_release_eligible": False,
        "reviewer": reviewer,
        "review_method": review_method,
        "reviewed_at": reviewed_at,
        "contact_sheet": {
            "path": str(contact_path),
            "sha256": actual_hash,
            "sample_count": len(items),
        },
        "required_checks": list(REQUIRED_CHECKS),
        "reviewed_item_count": len(items),
        "real_host_acceptance": pipeline.get("real_host_acceptance"),
        "zcode": pipeline.get("zcode"),
        "pipeline_receipt": str(pipeline_receipt.resolve()),
        "pipeline_receipt_sha256": sha256_file(pipeline_receipt),
        "checklist_sha256": sha256_file(checklist_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**result, "receipt_path": str(output_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--pipeline-receipt", type=Path, required=True)
    parser.add_argument("--checklist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = finalize_visual_review(
            repo_root=args.repo_root.expanduser().resolve(),
            pipeline_receipt=args.pipeline_receipt.expanduser().resolve(),
            checklist_path=args.checklist.expanduser().resolve(),
            output_path=args.output.expanduser().resolve(),
        )
    except Exception as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

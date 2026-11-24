#!/usr/bin/env python3
"""校验技能进化批次是否具备进入签名阶段的条件。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ALLOWED_RISKS = {"low", "medium", "high", "protected"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(document: dict, base: Path) -> list[str]:
    errors: list[str] = []
    for field in ("batch_id", "state", "risk_level", "snapshot", "impact_report", "diff", "test_report"):
        if not document.get(field):
            errors.append(f"缺少{field}")
    if document.get("risk_level") not in ALLOWED_RISKS:
        errors.append("risk_level无效")
    if document.get("state") not in {"tested", "approved"}:
        errors.append("进入签名前state必须为tested或approved")
    for field in ("snapshot", "impact_report", "diff", "test_report"):
        value = document.get(field)
        if not value:
            continue
        path = (base / value["path"]).resolve() if isinstance(value, dict) else (base / str(value)).resolve()
        if not path.is_file():
            errors.append(f"{field}文件不存在:{path}")
            continue
        if isinstance(value, dict) and value.get("sha256") and sha256(path) != value["sha256"]:
            errors.append(f"{field}哈希不匹配")
    tests = document.get("tests", [])
    if not tests or any(item.get("status") != "pass" for item in tests):
        errors.append("强制测试不完整或未全部通过")
    approval = document.get("approval")
    if document.get("state") == "approved":
        if not isinstance(approval, dict) or not approval.get("approved_by") or not approval.get("diff_sha256"):
            errors.append("approved状态缺少绑定审批")
    if document.get("risk_level") == "protected" and not isinstance(approval, dict):
        errors.append("受保护变更缺少逐项审批")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: validate_evolution_batch.py <evolution-batch.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]).resolve()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False))
        return 2
    errors = validate(document, path.parent)
    print(json.dumps({"status": "pass" if not errors else "fail", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

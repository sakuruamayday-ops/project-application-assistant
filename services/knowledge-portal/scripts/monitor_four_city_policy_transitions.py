#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PORTAL_DIR = Path(__file__).resolve().parents[1]
if str(PORTAL_DIR) not in sys.path:
    sys.path.insert(0, str(PORTAL_DIR))

from app.policy_transition_monitor import (  # noqa: E402
    affected_enterprises_for_policy_cell,
    build_policy_transition_snapshot,
    diff_policy_transition_snapshots,
    promote_verified_formal_candidate,
)


def read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}顶层必须为对象")
    return payload


def write_json(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "监测四市研发平台征求意见稿转正式文件，并按城市项目族内容哈希"
            "生成增量重编与企业影响清单"
        )
    )
    parser.add_argument(
        "--policy-registry",
        type=Path,
        default=(
            PORTAL_DIR
            / "references"
            / "four-city-rd-platform-policy-registry.json"
        ),
    )
    parser.add_argument(
        "--threshold-registry",
        type=Path,
        default=(
            PORTAL_DIR
            / "references"
            / "four-city-rd-platform-threshold-packs.json"
        ),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=(
            PORTAL_DIR
            / "references"
            / "four-city-policy-transition-snapshot.json"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=(
            PORTAL_DIR
            / "references"
            / "last-four-city-policy-transition-report.json"
        ),
    )
    parser.add_argument("--candidate-json", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument(
        "--apply-verified-promotion",
        action="store_true",
        help="仅在官方域名、正式状态和阈值轨道均通过门禁时写回注册表",
    )
    arguments = parser.parse_args()

    policy_registry = read_json(arguments.policy_registry)
    threshold_registry = read_json(arguments.threshold_registry)
    previous_snapshot = read_json(arguments.snapshot)
    promotion: dict[str, object] | None = None
    if arguments.candidate_json:
        candidate = read_json(arguments.candidate_json)
        promotion = promote_verified_formal_candidate(
            policy_registry,
            threshold_registry,
            candidate,
        )
        if (
            promotion.get("status") == "promoted"
            and arguments.apply_verified_promotion
        ):
            policy_registry = dict(promotion["policy_registry"])
            threshold_registry = dict(promotion["threshold_registry"])
            write_json(arguments.policy_registry, policy_registry)
            write_json(arguments.threshold_registry, threshold_registry)

    current_snapshot = build_policy_transition_snapshot(
        policy_registry,
        threshold_registry,
    )
    change_set = diff_policy_transition_snapshots(
        previous_snapshot or None,
        current_snapshot,
    )
    changed_names = [
        str(
            current_snapshot.get("cells", {})
            .get(str(item.get("cell_key") or ""), {})
            .get("canonical_name")
            or ""
        )
        for item in change_set["changed_cells"]
    ]
    affected_enterprises = affected_enterprises_for_policy_cell(
        arguments.database,
        project_names=changed_names,
    )
    report = {
        "schema_version": 1,
        "status": "pass",
        "promotion": (
            {
                key: value
                for key, value in promotion.items()
                if key not in {"policy_registry", "threshold_registry"}
            }
            if promotion
            else None
        ),
        "change_set": change_set,
        "affected_enterprise_count": len(affected_enterprises),
        "affected_enterprises": affected_enterprises,
        "next_actions": {
            "compile_project_ids": change_set["compile_project_ids"],
            "recompute": [
                "企业阈值判断",
                "前瞻预测",
                "历史回测解释",
                "政策来源披露",
            ]
            if change_set["change_count"]
            else [],
            "preserve": ["官方名单身份事实", "认定年度", "认定时名称"],
        },
    }
    write_json(arguments.snapshot, current_snapshot)
    write_json(arguments.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

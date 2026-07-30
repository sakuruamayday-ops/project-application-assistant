#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PORTAL_DIR = Path(__file__).resolve().parents[1]
if str(PORTAL_DIR) not in sys.path:
    sys.path.insert(0, str(PORTAL_DIR))

from app.policy_impact import simulate_policy_change_impact  # noqa: E402


def read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}顶层必须为对象")
    return payload


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="模拟政策变化的项目与企业身份影响")
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    before = read_json(arguments.before) if arguments.before else None
    after = read_json(arguments.after)
    report = simulate_policy_change_impact(
        before,
        after,
        database_path=arguments.database,
    )
    if arguments.output:
        write_json(arguments.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate one filled report through the client bundled document runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fill_report_template import complete_report
from select_report_template import resolve_template


def generate_report(input_path: Path, output_path: Path, report_type: str) -> dict:
    fixture = json.loads(input_path.read_text(encoding="utf-8"))
    selection = resolve_template(str(fixture["project_id"]), report_type)
    output_path = output_path.expanduser().resolve()
    # The copied blank master is never an intermediate delivery artifact.
    skill_root = Path(__file__).resolve().parents[1]
    if output_path.is_relative_to(skill_root):
        raise ValueError("报告输出不得位于技能目录")
    result = complete_report(
        template_path=Path(selection["template_path"]),
        output_path=output_path,
        fixture={**fixture, "project_id": selection["project_id"]},
        report_type=selection["report_type"],
        release_tag=selection["release_tag"],
        public_root=skill_root.parent,
    )
    return {**result, "schema_version": "gongchuang-project-report-operation/v1"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-type", choices=("preassessment", "feasibility"), required=True)
    args = parser.parse_args()
    result = generate_report(args.input, args.output, args.report_type)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

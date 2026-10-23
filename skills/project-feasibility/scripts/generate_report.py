#!/usr/bin/env python3
"""Generate one filled report through the client bundled document runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fill_report_template import ReportInputError, complete_report
from select_report_template import _select_by_alias, load_registry, resolve_template


def generate_report(input_path: Path, output_path: Path, report_type: str) -> dict:
    fixture = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if not isinstance(fixture, dict) or not isinstance(fixture.get("project_id"), str):
        raise ReportInputError("报告输入必须为包含 project_id 的对象", "report-required-fields", ["project_id"])
    output_path = output_path.expanduser().resolve()
    project = _select_by_alias(str(fixture["project_id"]), load_registry()["projects"])
    direct_html = project["id"] in {"high-tech-enterprise", "specialized-sme", "little-giant"}
    if direct_html and output_path.suffix.lower() != ".html":
        raise ReportInputError("高新、专精分析及体检报告只生成 HTML 供客户端直接导出 PDF；申请书使用独立 Word 回填操作", "report-output-format", ["output"])
    selection = resolve_template(str(project["id"]), report_type, template_format="html" if direct_html else "docx")
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
    try:
        result = generate_report(args.input, args.output, args.report_type)
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        print(json.dumps({"schema_version": "gongchuang-project-report-operation/v1",
                          "status": "fail", "errors": [str(error)],
                          **({"input_rejection": error.input_rejection} if isinstance(error, ReportInputError) else {})}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

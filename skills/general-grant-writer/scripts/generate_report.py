#!/usr/bin/env python3
"""Generate one filled report through the client bundled document runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fill_report_template import ReportInputError, complete_report
from select_report_template import _select_by_alias, load_registry, resolve_template


def project_template_query(project_id: str) -> str:
    if not project_id.startswith("project:"):
        return project_id
    try:
        parts = json.loads(project_id.removeprefix("project:"))
    except json.JSONDecodeError as error:
        raise ReportInputError("索引项目 ID 格式无效", "report-project-id", ["project_id"]) from error
    if (
        not isinstance(parts, list)
        or len(parts) != 3
        or not all(isinstance(part, str) for part in parts)
        or not parts[0].strip()
    ):
        raise ReportInputError("索引项目 ID 必须包含项目名称、地区和年度", "report-project-id", ["project_id"])
    return parts[0]


def generate_report(input_path: Path, output_path: Path, report_type: str) -> dict:
    fixture = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if not isinstance(fixture, dict) or not isinstance(fixture.get("project_id"), str):
        raise ReportInputError("报告输入必须为包含 project_id 的对象", "report-required-fields", ["project_id"])
    output_path = output_path.expanduser().resolve()
    project_id = fixture["project_id"]
    query = project_template_query(project_id)
    project = _select_by_alias(query, load_registry()["projects"])
    template_format = "docx"
    if project["id"] in {"high-tech-enterprise", "specialized-sme", "little-giant"}:
        output_suffix = output_path.suffix.lower()
        if output_suffix == ".html":
            template_format = "html"
        elif report_type != "feasibility" or output_suffix != ".docx":
            raise ReportInputError(
                "前期报告输出为 .html，可行性报告输出为 .html 或 .docx",
                "report-output-format", ["output"],
            )
    selection = resolve_template(str(project["id"]), report_type, template_format=template_format)
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
        project_id=project_id if query != project_id else None,
    )
    return {**result, "schema_version": "project-report-operation/v1"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-type", choices=("preassessment", "feasibility"), required=True)
    args = parser.parse_args()
    try:
        result = generate_report(args.input, args.output, args.report_type)
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        print(json.dumps({"schema_version": "project-report-operation/v1",
                          "status": "fail", "errors": [str(error)],
                          **({"input_rejection": error.input_rejection} if isinstance(error, ReportInputError) else {})}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

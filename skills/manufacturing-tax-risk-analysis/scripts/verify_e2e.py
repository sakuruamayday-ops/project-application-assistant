#!/usr/bin/env python3
"""Generate and verify the portable 17-page tax-risk sample."""

from __future__ import annotations

import argparse

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_checked(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, text=True, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def verify(skills_root: Path, output_directory: Path) -> dict[str, object]:
    tax_root = skills_root / "manufacturing-tax-risk-analysis"

    required = [
        tax_root / "scripts" / "generate_report_html.py",
        tax_root / "scripts" / "render_pdf_stdout.js",

        tax_root / "scripts" / "calculate_metrics.py",
        tax_root / "references" / "report-data.example.json",
        tax_root / "references" / "metrics-input.example.json",
        tax_root / "assets" / "gold-analysis.css",



    ]

    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"portable report resources missing: {missing}")

    output_directory.mkdir(parents=True, exist_ok=True)
    html_path = output_directory / "tax-risk-sample.html"
    pdf_path = output_directory / "tax-risk-sample.pdf"


    facts_path = output_directory / "enterprise-financial-facts.v1.json"
    metrics_path = output_directory / "manufacturing-tax-risk-metrics.v1.json"

    run_checked(
        [
            sys.executable,
            str(tax_root / "scripts" / "calculate_metrics.py"),
            str(tax_root / "references" / "metrics-input.example.json"),
            str(facts_path),
            "--metrics-output",
            str(metrics_path),
        ]
    )

    generate = run_checked(
        [
            sys.executable,
            str(tax_root / "scripts" / "generate_report_html.py"),
            str(tax_root / "references" / "report-data.example.json"),
            str(html_path),
            "--metrics-json",
            str(metrics_path),
        ]
    )
    html_text = html_path.read_text(encoding="utf-8")
    if html_text.count('<section class="page') != 17:
        raise RuntimeError("generated HTML does not contain exactly 17 page sections")

    import pymupdf as fitz

    renderer = subprocess.run(
        [os.environ.get("NODE_BINARY", "node"), str(tax_root / "scripts" / "render_pdf_stdout.js"), str(html_path)],
        capture_output=True, check=True,
    )
    with fitz.open(stream=renderer.stdout, filetype="pdf") as document:
        if len(document) != 17:
            raise RuntimeError(f"expected 17 pages, got {len(document)}")
        if not all(page.get_text("text").strip() for page in document):
            raise RuntimeError("PDF contains a blank page")
        pdf_path.write_bytes(renderer.stdout)
    return {
        "status": "passed", "html": str(html_path), "pdf": str(pdf_path), "pages": 17,
        "financial_facts": str(facts_path), "metrics": str(metrics_path),
        "generator": json.loads(generate.stdout),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--audit-json", type=Path)
    args = parser.parse_args()

    if args.output_dir:
        result = verify(args.skills_root.resolve(), args.output_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="tax-risk-e2e-") as directory:
            result = verify(args.skills_root.resolve(), Path(directory))
            result.pop("html", None)
            result.pop("pdf", None)
    if args.audit_json:
        args.audit_json.parent.mkdir(parents=True, exist_ok=True)
        args.audit_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

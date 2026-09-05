#!/usr/bin/env python3
"""Generate and verify the portable 17-page branded tax-risk sample."""

from __future__ import annotations

import argparse
import hashlib
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
    runtime_root = skills_root / "_runtime" / "gongchuang-branding"
    required = [
        tax_root / "scripts" / "generate_report_html.py",
        tax_root / "scripts" / "render_pdf_stdout.js",
        tax_root / "scripts" / "brand_gold_pdf.py",
        tax_root / "scripts" / "calculate_metrics.py",
        tax_root / "references" / "report-data.example.json",
        tax_root / "references" / "metrics-input.example.json",
        tax_root / "assets" / "gold-advisor.css",
        runtime_root / "scripts" / "delivery_gate.py",
        runtime_root / "scripts" / "pdf_two_pass.py",
        runtime_root / "references" / "brand_config.json",
    ]
    required.extend(sorted((runtime_root / "assets").glob("brand-*.png")))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"portable report resources missing: {missing}")

    output_directory.mkdir(parents=True, exist_ok=True)
    html_path = output_directory / "tax-risk-sample.html"
    pdf_path = output_directory / "tax-risk-sample.pdf"
    brand_audit_path = output_directory / "brand-audit.json"
    delivery_audit_path = output_directory / "delivery-audit.json"
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

    env = os.environ.copy()
    render = subprocess.Popen(
        [
            env.get("NODE_BINARY", "node"),
            str(tax_root / "scripts" / "render_pdf_stdout.js"),
            str(html_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert render.stdout is not None
    brand = subprocess.run(
        [
            sys.executable,
            str(tax_root / "scripts" / "brand_gold_pdf.py"),
            str(pdf_path),
            "--audit-json",
            str(brand_audit_path),
            "--title",
            "示例制造有限公司｜金税四期财务分析报告",
        ],
        stdin=render.stdout,
        capture_output=True,
        text=False,
        env=env,
    )
    render.stdout.close()
    render_stderr = render.stderr.read().decode("utf-8", errors="replace")
    render_returncode = render.wait()
    if render_returncode:
        raise RuntimeError(f"PDF renderer failed ({render_returncode}): {render_stderr}")
    if brand.returncode:
        raise RuntimeError(
            f"branding failed ({brand.returncode}): "
            f"{brand.stderr.decode('utf-8', errors='replace')}"
        )

    delivery = run_checked(
        [
            sys.executable,
            str(runtime_root / "scripts" / "delivery_gate.py"),
            str(pdf_path),
            "--expected-pages",
            "17",
            "--expected-author",
            "共创知识产权",
            "--expected-title-contains",
            "金税四期",
            "--audit-json",
            str(delivery_audit_path),
        ]
    )
    audit = json.loads(delivery_audit_path.read_text(encoding="utf-8"))
    if audit.get("watermarks") != 17:
        raise RuntimeError("delivery audit did not confirm 17 watermarks")

    return {
        "status": "passed",
        "skills_root": str(skills_root),
        "html": str(html_path),
        "pdf": str(pdf_path),
        "financial_facts": str(facts_path),
        "metrics": str(metrics_path),
        "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "pages": audit["pages"],
        "watermarks": audit["watermarks"],
        "watermark_size": audit["watermark_size"],
        "metadata": audit["metadata"],
        "generator": json.loads(generate.stdout),
        "delivery_gate": json.loads(delivery.stdout),
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
        with tempfile.TemporaryDirectory(prefix="gongchuang-tax-e2e-") as directory:
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

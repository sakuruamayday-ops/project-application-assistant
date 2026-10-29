"""Exercise fixed PDF CLI imports without loading optional ML engines."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("GONGCHUANG_TEST_PYTHON", sys.executable)
RUNTIME = ROOT / "skills" / "_runtime" / "gongchuang-branding" / "scripts"


@pytest.fixture(scope="module")
def pdf_inputs(tmp_path_factory):
    root = tmp_path_factory.mktemp("classic-pdf-cli")
    generator = r'''
import sys
from pathlib import Path
sys.modules["pymupdf.layout"] = None
sys.modules["pymupdf4llm"] = None
import pymupdf
sys.path.insert(0, sys.argv[1])
from pdf_two_pass import brand_pdf_document
root = Path(sys.argv[2])
with pymupdf.open() as document:
    for index in range(3):
        page = document.new_page()
        page.insert_textbox((72, 110, 500, 700), ("SOURCE-PAGE-%s Synthetic preserved report text. " % (index + 1)) * 8)
        if index == 0:
            page.insert_text((72, 80), "报告机构：共创知识产权", fontname="china-s", fontsize=12)
    document.save(root / "source.pdf")
    brand_pdf_document(document, variant="gold")
    document.save(root / "branded.pdf")
(root / "source.html").write_text("<p>Synthetic browser input</p>", encoding="utf-8")
'''
    subprocess.run([PYTHON, "-B", "-I", "-c", generator, str(RUNTIME), str(root)],
                   check=True, capture_output=True, text=True, timeout=30)
    return root


PROBE = r'''
import base64, contextlib, io, json, runpy, shutil, subprocess, sys, types
from pathlib import Path
config = json.loads(sys.argv[1])
root = Path(config["root"])
script = Path(config["script"])
sys.path.insert(0, str(script.parent))
preserved = {}
if config.get("preserveLoaded"):
    for name in ("pymupdf.layout", "pymupdf4llm"):
        preserved[name] = types.ModuleType(name)
        sys.modules[name] = preserved[name]
if config.get("mockBrowser"):
    # Only browser conversion is stubbed; PDF read/metadata/brand work is real.
    def browser_result(command, **kwargs):
        return types.SimpleNamespace(stdout=str(root) if command[0] == "npm" else base64.b64encode((root / "source.pdf").read_bytes()))
    subprocess.run = browser_result
    shutil.which = lambda command: "/synthetic/" + command
if config.get("stdinPdf"):
    sys.stdin = io.TextIOWrapper(io.BytesIO((root / "source.pdf").read_bytes()), encoding="utf-8")
sys.argv = [str(script)] + [part.format(root=str(root)) for part in config["args"]]
output = io.StringIO()
exit_code = 0
with contextlib.redirect_stdout(output):
    if config.get("function"):
        namespace = runpy.run_path(str(script), run_name="library-import-check")
        function = namespace[config["function"]]
        function.__globals__["__name__"] = "__main__"
        value = function(root / "source.pdf")
        if isinstance(value, str):
            assert "SOURCE-PAGE-1" in value and "SOURCE-PAGE-3" in value
    else:
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as error:
            exit_code = error.code or 0
assert exit_code == config.get("exitCode", 0), (exit_code, output.getvalue())
for name, module in preserved.items():
    assert sys.modules[name] is module, name
flags = {"layout": sys.modules.get("pymupdf.layout") is not None,
         "fourLlm": sys.modules.get("pymupdf4llm") is not None,
         "onnx": any(name.startswith("onnxruntime") for name in sys.modules)}
expected = {"layout": bool(preserved), "fourLlm": bool(preserved), "onnx": False}
assert flags == expected, flags
if config.get("outputPdf"):
    import pymupdf
    with pymupdf.open(root / config["outputPdf"]) as document:
        assert document.page_count == 3
        assert "SOURCE-PAGE-3" in document[-1].get_text("text")
if config.get("reader"):
    result = json.loads(output.getvalue())
    assert "SOURCE-PAGE-1" in result["text"] and "SOURCE-PAGE-3" in result["text"]
print(json.dumps({"flags": flags, "exitCode": exit_code, "callerModulesPreserved": bool(preserved)}))
'''


@pytest.mark.parametrize("relative,args,extra", [
    ("_runtime/gongchuang-branding/scripts/pdf_two_pass.py", ["{root}/source.pdf", "{root}/shared.pdf", "--variant", "gold"], {"outputPdf": "shared.pdf"}),
    ("_runtime/gongchuang-branding/scripts/delivery_gate.py", ["{root}/branded.pdf"], {}),
    ("_runtime/gongchuang-branding/scripts/delivery_gate.py", ["{root}/source.pdf"], {"exitCode": 2}),
    ("enterprise-panorama-analysis/scripts/render_sales_pdf.py", ["--html", "{root}/source.html", "--out", "{root}/sales.pdf", "--title", "Synthetic"], {"mockBrowser": True, "outputPdf": "sales.pdf"}),
    ("enterprise-panorama-analysis/scripts/render_html_report.py", ["--html", "{root}/source.html", "--out", "{root}/advisory.pdf"], {"mockBrowser": True, "outputPdf": "advisory.pdf"}),
    ("enterprise-panorama-analysis/scripts/validate_report_pdf.py", ["{root}/branded.pdf", "--require-watermark"], {}),
    ("enterprise-panorama-analysis/scripts/pdf_two_pass.py", ["--help"], {}),
    ("manufacturing-tax-risk-analysis/scripts/brand_gold_pdf.py", ["{root}/tax.pdf", "--title", "Synthetic"], {"stdinPdf": True, "outputPdf": "tax.pdf"}),
    ("project-application-assistant/scripts/extract_workspace_document.py", ["{root}/source.pdf"], {"reader": True}),
    ("project-feasibility/scripts/fill_report_template.py", [], {"function": "extract_source_text"}),
    ("project-feasibility/scripts/validate_report_profile_delivery.py", [], {"function": "_pdf_text"}),
    ("project-feasibility/scripts/validate_report_profile_delivery.py", [], {"function": "_pdf_cjk_font_errors"}),
    ("enterprise-panorama-analysis/scripts/render_sales_pdf.py", ["--help"], {"preserveLoaded": True}),
])
def test_fixed_pdf_cli_uses_core_and_preserves_explicit_ml_modules(pdf_inputs, relative, args, extra):
    config = {"root": str(pdf_inputs), "script": str(ROOT / "skills" / relative), "args": args, **extra}
    result = subprocess.run([PYTHON, "-B", "-I", "-X", "utf8", "-c", PROBE, json.dumps(config)],
                            check=True, text=True, capture_output=True, timeout=30)
    receipt = json.loads(result.stdout)
    assert receipt["flags"]["onnx"] is False

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pypdfium2 as pdfium


SCRIPT = Path(__file__).parents[1] / "scripts" / "extract_workspace_document.py"
FIXTURES = Path(__file__).parent / "fixtures"
OPERATIONS = Path(__file__).parents[2] / "client-runtime-operations.json"


def run(path: Path) -> tuple[int, dict[str, object]]:
    completed = subprocess.run([sys.executable, str(SCRIPT), str(path)], check=False, capture_output=True, text=True)
    return completed.returncode, json.loads(completed.stdout)


def test_extracts_utf8_txt(tmp_path: Path) -> None:
    source = tmp_path / "企业资料.txt"
    source.write_text("营业收入 100 万元", encoding="utf-8")
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert result["text"] == "营业收入 100 万元"


def test_extracts_docx_paragraphs(tmp_path: Path) -> None:
    source = tmp_path / "企业资料.docx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>核心技术</w:t>'
            '</w:r></w:p><w:p><w:r><w:t>已产业化</w:t></w:r></w:p></w:body></w:document>',
        )
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert "核心技术" in str(result["text"])
    assert "已产业化" in str(result["text"])


def test_extracts_xlsx_shared_strings(tmp_path: Path) -> None:
    source = tmp_path / "财务数据.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns:r="urn:relationships"><sheets><sheet name="财务数据" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr("xl/sharedStrings.xml", '<sst><si><t>营业收入</t></si></sst>')
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet><sheetData><row><c t="s"><v>0</v></c><c><v>100</v></c></row></sheetData></worksheet>',
        )
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert "营业收入\t100" in str(result["text"])


def test_extracts_xlsx_relationship_order_sparse_cells_and_visible_percentages(tmp_path: Path) -> None:
    source = tmp_path / "多表财务数据.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns:r="urn:relationships"><sheets>'
            '<sheet name="增长数据" r:id="rId10"/><sheet name="人员数据" r:id="rId1"/>'
            '</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships>'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId10" Target="worksheets/sheet10.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/styles.xml",
            '<styleSheet><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="10"/></cellXfs></styleSheet>',
        )
        archive.writestr(
            "xl/worksheets/sheet10.xml",
            '<worksheet><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>增长率</t></is></c>'
            '<c r="C1" s="1"><v>1.9</v></c></row></sheetData></worksheet>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>研发人数</t></is></c>'
            '<c r="B1"><v>6</v></c></row></sheetData></worksheet>',
        )
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    text = str(result["text"])
    assert text.index("## 增长数据") < text.index("## 人员数据")
    assert "增长率\t\t190.00%" in text
    assert "研发人数\t6" in text


def test_extracts_legacy_xls_visible_values() -> None:
    code, result = run(FIXTURES / "document-extraction-sample.xls")
    assert code == 0
    assert result["kind"] == "xls"
    assert result["status"] == "extracted"
    assert result["sheets"] == 1
    assert "研发人数\t6" in str(result["text"])
    # Evidence binds the value visible in Excel, not the stored numeric 1.9.
    assert "增长率\t190.00%" in str(result["text"])


def test_image_only_pdf_requires_ocr_instead_of_counting_page_heading_as_text(tmp_path: Path) -> None:
    source = tmp_path / "扫描件.pdf"
    document = pdfium.PdfDocument.new()
    document.new_page(width=595, height=842)
    document.save(source)
    document.close()

    code, result = run(source)
    assert code == 0
    assert result["status"] == "needs_ocr"
    assert result["text"] == ""
    assert result["pages"] == 1


def test_rejects_unsupported_file(tmp_path: Path) -> None:
    source = tmp_path / "payload.exe"
    source.write_bytes(b"MZ")
    code, result = run(source)
    assert code == 2
    assert result["status"] == "rejected"


def test_signed_operation_requires_the_document_extraction_schema_only() -> None:
    registry = json.loads(OPERATIONS.read_text(encoding="utf-8"))
    operations = {item["id"]: item for item in registry["operations"]}
    extractor = operations["project-application-assistant.extract-workspace-document"]
    ledger = operations["evidence-ledger.validate-strict-ledger"]
    assert extractor["stdout_json_schema_version"] == "gongchuang-document-extraction/v1"
    assert "stdout_json_schema_version" not in ledger

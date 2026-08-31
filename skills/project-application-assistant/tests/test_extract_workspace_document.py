from __future__ import annotations

import json
import struct
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


def write_content_types(archive: zipfile.ZipFile, part: str, content_type: str) -> None:
    archive.writestr(
        "[Content_Types].xml",
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Override PartName="/{part}" ContentType="{content_type}"/>'
        "</Types>",
    )


def write_minimal_docx(path: Path, *, macros: bool = False, content_type: str | None = None) -> None:
    content_type = content_type or (
        "application/vnd.ms-word.document.macroEnabled.main+xml"
        if macros
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    )
    with zipfile.ZipFile(path, "w") as archive:
        write_content_types(archive, "word/document.xml", content_type)
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>核心技术</w:t>'
            '</w:r></w:p><w:p><w:r><w:t>已产业化</w:t></w:r></w:p></w:body></w:document>',
        )
        if macros:
            archive.writestr("word/vbaProject.bin", b"macro-is-never-executed")


def write_minimal_xlsx(path: Path, *, macros: bool = False, content_type: str | None = None) -> None:
    content_type = content_type or (
        "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
        if macros
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    )
    with zipfile.ZipFile(path, "w") as archive:
        write_content_types(archive, "xl/workbook.xml", content_type)
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
        if macros:
            archive.writestr("xl/vbaProject.bin", b"macro-is-never-executed")


def replace_ole_directory_name(data: bytearray, old: str, new: str) -> None:
    needle = f"{old}\0".encode("utf-16le")
    position = data.find(needle)
    assert position >= 0
    entry_start = position - (position % 128)
    data[entry_start : entry_start + 64] = b"\0" * 64
    name = f"{new}\0".encode("utf-16le")
    assert len(name) <= 64
    data[entry_start : entry_start + len(name)] = name
    struct.pack_into("<H", data, entry_start + 64, len(name))


def write_minimal_ole_doc(path: Path) -> None:
    data = bytearray((FIXTURES / "document-extraction-sample.xls").read_bytes())
    replace_ole_directory_name(data, "Workbook", "WordDocument")
    path.write_bytes(data)


def test_extracts_utf8_txt(tmp_path: Path) -> None:
    source = tmp_path / "企业资料.txt"
    source.write_text("营业收入 100 万元", encoding="utf-8")
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert result["text"] == "营业收入 100 万元"


def test_extracts_docx_paragraphs(tmp_path: Path) -> None:
    source = tmp_path / "企业资料.docx"
    write_minimal_docx(source)
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert "核心技术" in str(result["text"])
    assert "已产业化" in str(result["text"])


def test_extracts_xlsx_shared_strings(tmp_path: Path) -> None:
    source = tmp_path / "财务数据.xlsx"
    write_minimal_xlsx(source)
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert "营业收入\t100" in str(result["text"])


def test_extracts_xlsx_relationship_order_sparse_cells_and_visible_percentages(tmp_path: Path) -> None:
    source = tmp_path / "多表财务数据.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        write_content_types(
            archive,
            "xl/workbook.xml",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        )
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


def test_routes_by_content_when_docx_has_wps_suffix(tmp_path: Path) -> None:
    source = tmp_path / "错后缀.wps"
    write_minimal_docx(source)
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert result["declared_suffix"] == ".wps"
    assert result["detected_kind"] == "docx"


def test_routes_et_compatibility_file_only_when_content_is_real_xlsx(tmp_path: Path) -> None:
    source = tmp_path / "兼容表格.et"
    write_minimal_xlsx(source)
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert result["declared_suffix"] == ".et"
    assert result["detected_kind"] == "xlsx"
    assert "营业收入\t100" in str(result["text"])

    proprietary = tmp_path / "专有表格.et"
    proprietary.write_text("项目,金额\n研发,100\n", encoding="utf-8")
    code, result = run(proprietary)
    assert code == 0
    assert result["detected_kind"] == "proprietary-office"
    assert result["status"] == "conversion_required"


def test_rejects_zip_with_office_named_part_but_no_content_type_contract(tmp_path: Path) -> None:
    source = tmp_path / "伪装.docx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", "<document>not enough</document>")
    code, result = run(source)
    assert code == 0
    assert result["status"] == "unsupported_format"
    assert result["detected_kind"] == "unknown-archive"


def test_zip_sniffing_rejects_content_type_bomb_before_decompression(tmp_path: Path) -> None:
    source = tmp_path / "嗅探炸弹.docx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", " " * 1_100_000)
        archive.writestr("word/document.xml", "<document/>")
    code, result = run(source)
    assert code == 0
    assert result["detected_kind"] == "unsafe-archive"
    assert result["status"] == "unsafe_document"
    assert result["retryable"] is False


def test_damaged_zip_and_ole_return_structured_non_retrying_outcomes(tmp_path: Path) -> None:
    damaged_zip = tmp_path / "损坏.docx"
    damaged_zip.write_bytes(b"PK\x03\x04broken")
    code, result = run(damaged_zip)
    assert code == 0
    assert result["detected_kind"] == "damaged-archive"
    assert result["status"] == "damaged_document"
    assert result["retryable"] is False

    damaged_ole = tmp_path / "损坏.xls"
    damaged_ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1broken")
    code, result = run(damaged_ole)
    assert code == 0
    assert result["detected_kind"] == "damaged-ole"
    assert result["status"] == "damaged_document"
    assert result["retryable"] is False


def test_macro_enabled_ooxml_is_read_only_and_never_executes_macro(tmp_path: Path) -> None:
    source = tmp_path / "只读.docm"
    write_minimal_docx(source, macros=True)
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert result["contains_macros"] is True
    assert result["macro_policy"] == "ignored-read-only"
    assert result["external_links"] == "not-followed"


def test_ooxml_word_and_excel_template_families_use_same_read_only_parsers(tmp_path: Path) -> None:
    dotm = tmp_path / "文字模板.dotm"
    write_minimal_docx(
        dotm,
        macros=True,
        content_type="application/vnd.ms-word.template.macroEnabledTemplate.main+xml",
    )
    code, result = run(dotm)
    assert code == 0
    assert result["detected_kind"] == "docx"
    assert result["macro_policy"] == "ignored-read-only"

    xltm = tmp_path / "表格模板.xltm"
    write_minimal_xlsx(
        xltm,
        macros=True,
        content_type="application/vnd.ms-excel.template.macroEnabled.main+xml",
    )
    code, result = run(xltm)
    assert code == 0
    assert result["detected_kind"] == "xlsx"
    assert result["formula_policy"] == "cached-values-only"


def test_extracts_ods_visible_cells_and_repetitions(tmp_path: Path) -> None:
    source = tmp_path / "财务数据.ods"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        archive.writestr(
            "content.xml",
            '<office:document-content xmlns:office="urn:o" xmlns:table="urn:t" xmlns:text="urn:x">'
            '<office:body><office:spreadsheet><table:table table:name="财务">'
            '<table:table-row><table:table-cell><text:p>营业收入</text:p></table:table-cell>'
            '<table:table-cell table:number-columns-repeated="2"><text:p>100</text:p></table:table-cell>'
            '</table:table-row></table:table></office:spreadsheet></office:body></office:document-content>',
        )
    code, result = run(source)
    assert code == 0
    assert result["status"] == "extracted"
    assert result["detected_kind"] == "ods"
    assert "营业收入\t100\t100" in str(result["text"])


def test_ods_repeat_bomb_stops_at_structured_safety_boundary(tmp_path: Path) -> None:
    source = tmp_path / "重复炸弹.ods"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        archive.writestr(
            "content.xml",
            '<document><table name="风险"><table-row>'
            '<table-cell number-columns-repeated="999999999"><p>x</p></table-cell>'
            '</table-row></table></document>',
        )
    code, result = run(source)
    assert code == 0
    assert result["status"] == "unsafe_document"
    assert result["retryable"] is False


def test_extracts_odt_and_rtf_with_standard_library_only(tmp_path: Path) -> None:
    odt = tmp_path / "说明.odt"
    with zipfile.ZipFile(odt, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr(
            "content.xml",
            '<document xmlns:text="urn:x"><body><text:p>项目说明</text:p><text:p>第二段</text:p></body></document>',
        )
    code, result = run(odt)
    assert code == 0
    assert result["status"] == "extracted"
    assert result["detected_kind"] == "odt"
    assert "项目说明\n第二段" in str(result["text"])

    rtf = tmp_path / "说明.rtf"
    rtf.write_bytes(b"{\\rtf1\\ansi\\ansicpg1252 Visible \\u39033?\\u30446?\\par Next}")
    code, result = run(rtf)
    assert code == 0
    assert result["status"] == "extracted"
    assert result["detected_kind"] == "rtf"
    assert "项目" in str(result["text"])
    assert "Next" in str(result["text"])


def test_extracts_csv_and_tsv_as_bounded_visible_rows(tmp_path: Path) -> None:
    csv_source = tmp_path / "财务.csv"
    csv_source.write_text("项目,金额\n研发,100\n", encoding="utf-8-sig")
    code, result = run(csv_source)
    assert code == 0
    assert result["kind"] == "csv"
    assert "项目\t金额" in str(result["text"])

    tsv_source = tmp_path / "人员.tsv"
    tsv_source.write_text("姓名\t人数\n研发\t6\n", encoding="gb18030")
    code, result = run(tsv_source)
    assert code == 0
    assert result["kind"] == "tsv"
    assert "研发\t6" in str(result["text"])


def test_plain_txt_with_commas_and_semicolons_keeps_original_prose(tmp_path: Path) -> None:
    source = tmp_path / "说明.txt"
    original = "第一段，包含逗号,但不是表格；仍需保留。\n第二段,列数并不相同；也是普通正文。"
    source.write_text(original, encoding="utf-8")
    code, result = run(source)
    assert code == 0
    assert result["kind"] == "txt"
    assert result["text"] == original


def test_json_stdout_is_bounded_after_chinese_and_newline_escaping(tmp_path: Path) -> None:
    source = tmp_path / "超长中文.txt"
    source.write_text(("中\n" * 300_000), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(SCRIPT), str(source)], check=False, capture_output=True)
    result = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert len(completed.stdout) <= 900 * 1024 + 1
    assert result["status"] == "extracted"
    assert result["truncated"] is True
    assert len(str(result["text"])) <= 500_000


def test_legacy_ole_doc_returns_one_structured_conversion_outcome(tmp_path: Path) -> None:
    source = tmp_path / "旧专利.doc"
    write_minimal_ole_doc(source)
    code, result = run(source)
    assert code == 0
    assert result["detected_kind"] == "doc"
    assert result["status"] == "conversion_required"
    assert result["action"] == "convert_to_supported_format"
    assert result["retryable"] is False


def test_unknown_proprietary_wps_returns_conversion_instead_of_generic_error(tmp_path: Path) -> None:
    source = tmp_path / "专有格式.wps"
    source.write_bytes(b"\x01WPS-PROPRIETARY\x00\xff")
    code, result = run(source)
    assert code == 0
    assert result["detected_kind"] == "proprietary-office"
    assert result["status"] == "conversion_required"
    assert result["retryable"] is False


def test_encrypted_office_container_returns_password_free_copy_action(tmp_path: Path) -> None:
    source = tmp_path / "加密.docx"
    data = bytearray((FIXTURES / "document-extraction-sample.xls").read_bytes())
    replace_ole_directory_name(data, "Root Entry", "EncryptionInfo")
    replace_ole_directory_name(data, "Workbook", "EncryptedPackage")
    source.write_bytes(data)
    code, result = run(source)
    assert code == 0
    assert result["detected_kind"] == "encrypted-office"
    assert result["status"] == "encrypted_document"
    assert result["action"] == "provide_password_free_copy"
    assert result["retryable"] is False


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
    assert code == 0
    assert result["status"] == "unsupported_format"
    assert result["retryable"] is False


def test_signed_operation_requires_the_document_extraction_schema_only() -> None:
    registry = json.loads(OPERATIONS.read_text(encoding="utf-8"))
    operations = {item["id"]: item for item in registry["operations"]}
    extractor = operations["project-application-assistant.extract-workspace-document"]
    ledger = operations["evidence-ledger.validate-strict-ledger"]
    assert extractor["stdout_json_schema_version"] == "gongchuang-document-extraction/v1"
    extensions = extractor["parameters"]["document"]["extensions"]
    assert len(extensions) == 19
    assert set(extensions) == {
        ".doc", ".docx", ".docm", ".dotx", ".dotm", ".wps", ".rtf", ".xls", ".xlsx",
        ".xlsm", ".xltx", ".xltm", ".ods", ".odt", ".csv", ".tsv", ".et", ".pdf", ".txt",
    }
    assert "stdout_json_schema_version" not in ledger

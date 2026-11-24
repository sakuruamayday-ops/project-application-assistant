"""Read text from archived policy originals without fetching remote content."""

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
from zipfile import is_zipfile


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if tag in {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _legacy_word(path):
    if tool := shutil.which("textutil"):
        args = [tool, "-convert", "txt", "-stdout", str(path)]
    elif tool := shutil.which("antiword"):
        args = [tool, "-m", "UTF-8.txt", str(path)]
    else:
        raise ValueError("读取 DOC 原件需要 textutil 或 antiword")
    result = subprocess.run(args, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("DOC 原件转换失败")
    return result.stdout.decode("utf-8-sig")


def read_policy_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md", ".csv"}:
            text = path.read_text(encoding="utf-8-sig")
        elif suffix in {".html", ".htm"}:
            parser = _HTMLText()
            parser.feed(path.read_text(encoding="utf-8-sig"))
            text = "".join(parser.parts)
        elif suffix == ".docx" or (suffix == ".doc" and is_zipfile(path)):
            from docx import Document
            document = Document(path)
            parts = [paragraph.text for paragraph in document.paragraphs]
            parts.extend(cell.text for table in document.tables for row in table.rows for cell in row.cells)
            text = "\n".join(parts)
        elif suffix == ".doc":
            text = _legacy_word(path)
        elif suffix == ".pdf":
            import fitz
            with path.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError("PDF 文件头无效")
            with fitz.open(path) as document:
                text = "\n".join(page.get_text("text") for page in document)
        elif suffix in {".xlsx", ".xlsm"}:
            from openpyxl import load_workbook
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                text = "\n".join(str(value) for sheet in workbook.worksheets
                                 for row in sheet.iter_rows(values_only=True)
                                 for value in row if value is not None)
            finally:
                workbook.close()
        elif suffix == ".xls":
            import xlrd
            with xlrd.open_workbook(path) as workbook:
                text = "\n".join(str(value) for sheet in workbook.sheets()
                                 for index in range(sheet.nrows) for value in sheet.row_values(index) if value != "")
        else:
            raise ValueError(f"不支持的政策原件格式 {suffix}")
        if not text.strip():
            raise ValueError("无可读取的原文文本")
        return text
    except Exception as error:
        # Format readers use different exception types for damaged or encrypted originals.
        raise ValueError(f"读回原件 {path.name} 失败：{error}") from error

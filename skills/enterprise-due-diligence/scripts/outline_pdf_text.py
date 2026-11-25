"""Keep printed text visible and searchable without embedding font programs."""

import re
import unicodedata

import pymupdf as fitz
from lxml import etree


SVG_NS = "{http://www.w3.org/2000/svg}"
PAGE_DECORATION = re.compile(
    r"企业全景调研报告|主要数据来源|来源|网址|查询日期"
    r"|资料出处见[「『“]?主要数据来源[」』”]?[。.]?"
    r"|(?:报告日期|报告机构|报告人)[:：].*"
    r"|第?\d+页(?:[/／]?(?:共)?\d+页)?|\d+[/／]\d+"
)


class ValidationError(RuntimeError):
    pass


def validate_page_content(document: fitz.Document) -> int:
    """Reject pages that have no body or populated table text."""
    if not document.is_pdf or document.needs_pass or not document.page_count:
        raise ValidationError("无法读取有效的报告 PDF")
    empty_pages = []
    for number, page in enumerate(document, start=1):
        lines = ("".join(unicodedata.normalize("NFKC", line).split())
                 for line in page.get_text("text").splitlines())
        if not any(any(character.isalnum() for character in line) and not PAGE_DECORATION.fullmatch(line)
                   for line in lines):
            empty_pages.append(str(number))
    if empty_pages:
        raise ValidationError(f"报告 PDF 第 {'、'.join(empty_pages)} 页缺正文或表格内容（空白或仅尾注）")
    return document.page_count


def _keep_glyph_paths(node: etree._Element) -> None:
    for child in list(node):
        if child.tag == SVG_NS + "g":
            _keep_glyph_paths(child)
            if len(child):
                continue
        if child.tag == SVG_NS + "defs" or (
            child.tag == SVG_NS + "use" and "data-text" in child.attrib
        ):
            continue
        node.remove(child)


def _restore_searchable_text(page: fitz.Page, spans: list[dict]) -> None:
    page.insert_font(fontname="helv")
    to_pdf = ~page.transformation_matrix
    placeholder_width = fitz.get_text_length("M", fontname="helv", fontsize=1)
    commands = []
    for span in spans:
        text = span["text"]
        size = span["size"]
        if not text or size <= 0:
            continue
        origin = fitz.Point(span["origin"]) * to_pdf
        width = span["bbox"][2] - span["bbox"][0]
        scale = max(0.01, 100 * width / (placeholder_width * size * len(text)))
        actual = "FEFF" + text.encode("utf-16-be").hex()
        # ActualText retains Unicode, and PDF text rendering mode 3 leaves the
        # visible glyph outlines unobstructed.
        commands.append(
            f"/Span <</ActualText <{actual}>>> BDC\n"
            f"BT /helv {size:.5f} Tf 3 Tr {scale:.5f} Tz "
            f"1 0 0 1 {origin.x:.5f} {origin.y:.5f} Tm ({'M' * len(text)}) Tj ET\n"
            "EMC\n"
        )
    document = page.parent
    stream = document.get_new_xref()
    document.update_object(stream, "<<>>")
    document.update_stream(stream, "".join(commands).encode("ascii"))
    contents = " ".join(f"{xref} 0 R" for xref in (*page.get_contents(), stream))
    document.xref_set_key(page.xref, "Contents", f"[{contents}]")


def outline_pdf_text(document: fitz.Document) -> None:
    """Replace printed glyphs with vectors and retain each page's text and links."""
    validate_page_content(document)
    for page in document:
        spans = [
            span for block in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
            for line in block["lines"] for span in line["spans"]
        ]
        if not spans:
            continue
        links = page.get_links()
        glyphs = etree.fromstring(page.get_svg_image(text_as_path=True).encode("utf-8"))
        _keep_glyph_paths(glyphs)

        # Redact only the original text so clipping, fills and image alpha stay
        # in the original PDF. The SVG contributes only the text outlines.
        page.add_redact_annot(page.rect, fill=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        with fitz.open(stream=etree.tostring(glyphs), filetype="svg") as drawing:
            with fitz.open(stream=drawing.convert_to_pdf(), filetype="pdf") as visual:
                page.show_pdf_page(page.rect, visual, 0)
        _restore_searchable_text(page, spans)
        for link in links:
            page.insert_link(link)
        page.clean_contents()

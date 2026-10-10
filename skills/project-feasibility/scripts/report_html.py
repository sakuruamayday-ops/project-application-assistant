"""Serialize the filled report master for the client's local PDF renderer."""
from html import escape
import re

from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def _paragraph(paragraph: Paragraph) -> str:
    pieces = []
    for node in paragraph._p:
        if node.tag == qn("w:r"):
            nodes = [node]
            target = None
        elif node.tag == qn("w:hyperlink"):
            nodes = list(node.findall(qn("w:r")))
            relationship = paragraph.part.rels.get(node.get(qn("r:id")))
            target = str(relationship.target_ref) if relationship else None
        else:
            continue
        for run in nodes:
            text = "".join(escape(child.text or "") if child.tag == qn("w:t") else
                           "<br>" if child.tag == qn("w:br") else
                           "&#9;" if child.tag == qn("w:tab") else "" for child in run)
            properties = run.find(qn("w:rPr"))
            if properties is not None:
                styles = []
                size = properties.find(qn("w:sz"))
                if size is not None:
                    value = size.get(qn("w:val"), "")
                    if value.isdigit() and int(value) > 0:
                        styles.append(f"font-size:{int(value) / 2:g}pt")
                color = properties.find(qn("w:color"))
                if color is not None:
                    value = color.get(qn("w:val"), "")
                    if re.fullmatch(r"[0-9A-Fa-f]{6}", value):
                        styles.append(f"color:#{value}")
                if styles:
                    text = f'<span style="{";".join(styles)}">{text}</span>'
                for property_name, tag in (("b", "strong"), ("i", "em")):
                    setting = properties.find(qn(f"w:{property_name}"))
                    if setting is not None and setting.get(qn("w:val")) not in {"0", "false"}:
                        text = f"<{tag}>{text}</{tag}>"
            if target and target.startswith(("https://", "http://")):
                text = f'<a href="{escape(target, quote=True)}">{text}</a>'
            pieces.append(text)
    style = paragraph.style.name if paragraph.style else ""
    tag = "h1" if style in {"Title", "Heading 1"} else "h2" if style == "Heading 2" else "h3" if style == "Heading 3" else "p"
    page_break = ' data-page-break="true"' if paragraph.paragraph_format.page_break_before else ""
    alignment = {0: "left", 1: "center", 2: "right", 3: "justify"}.get(paragraph.alignment)
    paragraph_style = f' style="text-align:{alignment}"' if alignment else ""
    return f"<{tag}{page_break}{paragraph_style}>{''.join(pieces)}</{tag}>"


def _table(table: Table) -> str:
    rows = []
    for row_index, row in enumerate(table.rows):
        cells = []
        seen = set()
        for cell in row.cells:
            if cell._tc in seen:
                continue
            seen.add(cell._tc)
            span = cell._tc.grid_span
            tag = "th" if row_index == 0 else "td"
            content = "".join(_paragraph(paragraph) for paragraph in cell.paragraphs)
            shading = cell._tc.find(f'{qn("w:tcPr")}/{qn("w:shd")}')
            fill = shading.get(qn("w:fill"), "") if shading is not None else ""
            cell_style = f' style="background:#{fill}"' if re.fullmatch(r"[0-9A-Fa-f]{6}", fill) else ""
            cells.append(f'<{tag} colspan="{span}"{cell_style}>{content}</{tag}>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    widths = [column.width for column in table.columns]
    columns = ("<colgroup>" + "".join(f'<col style="width:{width / sum(widths) * 100:.6g}%">' for width in widths)
               + "</colgroup>") if widths and all(width is not None and width > 0 for width in widths) else ""
    return '<table data-repeat-header="true">' + columns + '<tbody>' + "".join(rows) + "</tbody></table>"


def report_html(document) -> str:
    """Retain master order, headings, tables, emphasis and source links without rewriting text."""
    blocks = []
    for element in document.element.body:
        if element.tag == qn("w:p"):
            blocks.append(_paragraph(Paragraph(element, document)))
        elif element.tag == qn("w:tbl"):
            blocks.append(_table(Table(element, document)))
    title = escape(document.core_properties.title or "项目分析报告")
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title>'
            '<meta name="author" content="共创知识产权"><style>'
            '@page{size:A4;margin:18mm 18mm 16mm}html,body{margin:0;padding:0;background:white;color:#20262f;letter-spacing:0}'
            'body{width:174mm;font-size:10.5pt;line-height:1.55}h1{font-size:19pt;color:#233d66;margin:10pt 0}'
            'h2{font-size:14pt;color:#233d66;margin:10pt 0 6pt}h3{font-size:11.5pt;margin:8pt 0 5pt}'
            'p{margin:4pt 0;white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse;table-layout:fixed;width:100%;margin:6pt 0}'
            'th,td{border:1px solid #cbd9eb;padding:5pt;vertical-align:top;overflow-wrap:anywhere}th{background:#e8eff8;color:#233d66;font-weight:700}'
            'th p,td p{margin:0;font-size:9pt;line-height:1.45}a{color:#233d66;text-decoration:underline}'
            '</style></head><body>' + "".join(blocks) + "</body></html>")

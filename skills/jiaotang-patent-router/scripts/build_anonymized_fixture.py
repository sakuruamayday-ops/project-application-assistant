#!/usr/bin/env python3
import argparse
import copy
import re
import zipfile
from pathlib import Path
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
V = "urn:schemas-microsoft-com:vml"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
NS = {"w": W, "m": M, "cp": CP, "dc": DC}
KEEP = {"摘要", "权利要求书", "说明书", "技术领域", "背景技术", "发明内容",
        "附图说明", "具体实施方式", "说明书附图", "摘要附图"}

def mask_text(s):
    if s in KEEP:
        return s
    return re.sub(r"[A-Za-z0-9\u3400-\u9fff]", "样", s)

def wtag(name):
    return f"{{{W}}}{name}"

def mtag(name):
    return f"{{{M}}}{name}"

def paragraph(text, style=None):
    p = etree.Element(wtag("p"))
    if style:
        ppr = etree.SubElement(p, wtag("pPr"))
        ps = etree.SubElement(ppr, wtag("pStyle"))
        ps.set(wtag("val"), style)
    r = etree.SubElement(p, wtag("r"))
    t = etree.SubElement(r, wtag("t"))
    t.text = text
    return p

def table_fixture():
    tbl = etree.Element(wtag("tbl"))
    pr = etree.SubElement(tbl, wtag("tblPr"))
    width = etree.SubElement(pr, wtag("tblW")); width.set(wtag("w"), "9000"); width.set(wtag("type"), "dxa")
    grid = etree.SubElement(tbl, wtag("tblGrid"))
    for v in ("1800", "3600", "3600"):
        c = etree.SubElement(grid, wtag("gridCol")); c.set(wtag("w"), v)
    values = [
        ["合并标题：复杂表格定位锚点", None, None],
        ["参数", "样例值", "说明"],
        ["P0", "100", "基准透过率"],
        ["P1", "20", "阻隔后透过率"],
    ]
    for ri, vals in enumerate(values):
        tr = etree.SubElement(tbl, wtag("tr"))
        for ci, value in enumerate(vals):
            if value is None:
                continue
            tc = etree.SubElement(tr, wtag("tc"))
            tcpr = etree.SubElement(tc, wtag("tcPr"))
            if ri == 0 and ci == 0:
                gs = etree.SubElement(tcpr, wtag("gridSpan")); gs.set(wtag("val"), "3")
            tc.append(paragraph(value))
    return tbl

def math_fixture():
    mp = etree.Element(mtag("oMathPara"), nsmap={"m": M})
    om = etree.SubElement(mp, mtag("oMath"))
    for text in ("B", "=", "P0", "/", "P1"):
        mr = etree.SubElement(om, mtag("r"))
        mt = etree.SubElement(mr, mtag("t")); mt.text = text
    return mp

def textbox_fixture():
    p = etree.Element(wtag("p"), nsmap={"w": W, "v": V})
    r = etree.SubElement(p, wtag("r"))
    pict = etree.SubElement(r, wtag("pict"))
    shape = etree.SubElement(pict, f"{{{V}}}shape")
    shape.set("style", "width:360pt;height:36pt")
    textbox = etree.SubElement(shape, f"{{{V}}}textbox")
    content = etree.SubElement(textbox, wtag("txbxContent"))
    content.append(paragraph("文本框定位锚点 REG-TEXTBOX-001"))
    return p

def main():
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("output")
    a = p.parse_args()
    src, dst = Path(a.input), Path(a.output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.endswith(".xml"):
                try:
                    root = etree.fromstring(data)
                    for node in root.xpath("//w:t|//w:delText|//m:t", namespaces=NS):
                        if node.text:
                            node.text = mask_text(node.text)
                    if info.filename == "docProps/core.xml":
                        for node in root.xpath("//dc:creator|//cp:lastModifiedBy", namespaces=NS):
                            node.text = "回归测试"
                    if info.filename == "word/document.xml":
                        textbox_nodes = root.xpath("//w:txbxContent//w:t", namespaces=NS)
                        if textbox_nodes:
                            textbox_nodes[0].text = "文本框定位锚点 REG-TEXTBOX-001"
                        body = root.find(f".//{{{W}}}body")
                        sect = body.find(f"{{{W}}}sectPr")
                        pos = list(body).index(sect) if sect is not None else len(body)
                        fixtures = [
                            paragraph("回归测试附页", "Heading1"),
                            paragraph("批注定位锚点：唯一文本 REG-COMMENT-001"),
                            paragraph("重复定位锚点：REG-OCCURRENCE。重复定位锚点：REG-OCCURRENCE。"),
                            paragraph("公式定位锚点：阻隔性能指数"),
                            math_fixture(),
                            paragraph("复杂表格定位锚点"),
                            table_fixture(),
                            paragraph("图99 回归测试附图标记 99"),
                            textbox_fixture(),
                        ]
                        for offset, node in enumerate(fixtures):
                            body.insert(pos + offset, node)
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                except etree.XMLSyntaxError:
                    pass
            zout.writestr(info, data)
    print(dst)

if __name__ == "__main__":
    main()

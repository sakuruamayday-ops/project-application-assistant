import json
from pathlib import Path
import subprocess
import sys

import pymupdf as fitz
import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_standard_report_uses_system_fonts(tmp_path):
    script = SCRIPTS / "build_standard_html.py"
    source = tmp_path / "facts.json"
    output = tmp_path / "standard.html"
    company = "示例装备有限公司"
    source.write_text(json.dumps({"company": {"name": company}}, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script), "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    report = output.read_text(encoding="utf-8")
    assert company in report
    assert 'font-family: "宋体", "Songti SC", "SimSun", "Noto Serif CJK SC", serif' in report
    assert "@font-face" not in report
    assert "file://" not in report
    assert "data:font/" not in report
    assert "data:image/png;base64," in report


def test_pdf_preserves_visible_and_searchable_text_without_font_programs(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from outline_pdf_text import outline_pdf_text

    sentence = "装备示例有限公司 MES 系统"
    text_box = fitz.Rect(30, 32, 240, 64)
    with fitz.open() as source:
        page = source.new_page()
        page.draw_rect(text_box, color=None, fill=(1, 0.9, 0.7))
        page.insert_font(fontname="FixtureCJK", fontbuffer=fitz.Font("cjk").buffer)
        page.insert_text((36, 52), sentence, fontsize=12, fontname="FixtureCJK")
        page.insert_link({"kind": fitz.LINK_URI, "from": text_box, "uri": "https://example.com"})
        original = source.tobytes()
    with fitz.open(stream=original, filetype="pdf") as source:
        before = source[0].get_pixmap(clip=text_box).samples
        assert any(source.extract_font(row[0])[3] for row in source[0].get_fonts())
        outline_pdf_text(source)
        exported = source.tobytes(garbage=4, deflate=True)
    with fitz.open(stream=exported, filetype="pdf") as result:
        page = result[0]
        after = page.get_pixmap(clip=text_box).samples
        assert "".join(page.get_text().split()) == "".join(sentence.split())
        assert page.get_links()[0]["uri"] == "https://example.com"
        assert not any(result.extract_font(row[0])[3] for row in page.get_fonts(full=True))
        # Independent raster comparison detects blank glyphs even when the
        # invisible text is still extractable.
        assert len(before) == len(after)
        assert sum(abs(a - b) for a, b in zip(before, after)) / len(before) < 12


@pytest.mark.parametrize("footer", [False, True])
def test_outline_renderer_rejects_a_page_without_body(monkeypatch, footer):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from outline_pdf_text import ValidationError, outline_pdf_text, validate_page_content

    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 100), "A populated table row")
        assert validate_page_content(document) == 1
        page = document.new_page()
        if footer:
            page.insert_text((50, 70), "企业全景调研报告\n资料出处见「主要数据来源」。\n报告日期：2026-11-21",
                             fontname="china-s")
        with pytest.raises(ValidationError, match="第 2 页缺正文或表格内容"):
            outline_pdf_text(document)

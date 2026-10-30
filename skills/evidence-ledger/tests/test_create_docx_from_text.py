from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH


SCRIPT = Path(__file__).parents[1] / "scripts" / "create_docx_from_text.py"


def test_creates_a_native_docx_with_one_structured_stdout_record(tmp_path: Path) -> None:
    artifact = tmp_path / "quality-brand-draft.docx"
    content = """制造精品前期评估

# 总体结论
当前材料仅形成待补资料清单。

| 核验项 | 结论 |
|---|---|
| 质量管理 | 待补资料 |

- 请企业补充质量管理体系材料。
"""

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), content, str(artifact)],
        check=True,
        capture_output=True,
        text=True,
    )

    # 受签名运行时只接受一条 JSON；警告或调试输出都必须让测试失败。
    assert completed.stdout.count("\n") == 1
    result = json.loads(completed.stdout)
    assert result["schema_version"] == "gongchuang-docx-generation-operation/v1"
    assert result["characters"] == len(content)
    assert result["tables"] == 1
    generated = Document(artifact)
    assert generated.paragraphs[0].text == "制造精品前期评估"
    assert generated.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert generated.sections[0].top_margin.cm == pytest.approx(2.0, abs=0.001)
    assert generated.sections[0].left_margin.cm == pytest.approx(2.2, abs=0.001)
    assert generated.styles["Normal"].font.size.pt == pytest.approx(10.5)
    assert generated.paragraphs[2].paragraph_format.line_spacing == 1.25
    assert generated.tables[0].cell(1, 0).text == "质量管理"
    assert generated.tables[0].rows[0]._tr.xpath('./w:trPr/w:tblHeader')
    assert all(row._tr.xpath('./w:trPr/w:cantSplit') for row in generated.tables[0].rows)
    table_run = generated.tables[0].cell(1, 0).paragraphs[0].runs[0]
    assert table_run.font.size.pt == pytest.approx(9.5)
    assert generated.tables[0].cell(1, 0).paragraphs[0].paragraph_format.space_after.pt == 0


def test_refuses_to_overwrite_an_existing_docx(tmp_path: Path) -> None:
    artifact = tmp_path / "existing.docx"
    Document().save(artifact)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "不会覆盖", str(artifact)],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "拒绝覆盖" in completed.stderr


def test_input_file_larger_than_one_mib_preserves_every_paragraph(tmp_path: Path) -> None:
    paragraphs = [f"第{index:03d}段：" + "合成正文甲乙丙丁0123456789。" * 300 for index in range(100)]
    content = "# 合成长正文\n\n" + "\n\n".join(paragraphs)
    source = tmp_path / "long-report.md"
    source.write_text(content, encoding="utf-8")
    assert source.stat().st_size > 1024 * 1024
    artifact = tmp_path / "long-report.docx"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--input-file", str(source), str(artifact)],
        check=True, capture_output=True, text=True,
    )

    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "passed"
    assert receipt["characters"] == len(content)
    assert [paragraph.text for paragraph in Document(artifact).paragraphs] == ["合成长正文", *paragraphs]
    with ZipFile(artifact) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    for paragraph in paragraphs:
        assert paragraph in xml
    assert source.read_text(encoding="utf-8") == content


def test_exports_markdown_emphasis_without_changing_literal_symbols(tmp_path: Path) -> None:
    artifact = tmp_path / 'formatted.docx'
    content = '**测试报告**\n\n结果为 **0%**，*已核实*；代码 `a**b`，转义 \\*文字\\*。\n\n| 项目 | 结论 |\n|---|---|\n| 销售额 | **0元** |\n\n1. 保留编号及正文样式。\n\n来源：[国家数据](https://data.stats.gov.cn/)'
    subprocess.run([sys.executable, str(SCRIPT), content, str(artifact)], check=True, capture_output=True, text=True)
    generated = Document(artifact)
    assert generated.paragraphs[0].text == '测试报告'
    assert generated.paragraphs[1].text == '结果为 0%，已核实；代码 a**b，转义 *文字*。'
    assert any(run.text == '0%' and run.bold for run in generated.paragraphs[1].runs)
    assert any(run.text == '已核实' and run.italic for run in generated.paragraphs[1].runs)
    assert generated.tables[0].cell(1, 1).text == '0元'
    numbered = next(p for p in generated.paragraphs if p.text.startswith('1. '))
    assert numbered.text == '1. 保留编号及正文样式。'
    assert numbered.runs[0].font.size.pt == 10.5
    assert not numbered.runs[0].bold
    assert generated.paragraphs[-1].text == '来源：国家数据'
    assert generated.paragraphs[-1].hyperlinks[0].url == 'https://data.stats.gov.cn/'


def test_html_file_keeps_literal_body_and_native_table_cells(tmp_path: Path) -> None:
    source = tmp_path / "same-report.html"
    source.write_text(
        '<!doctype html><html><head><style>not report text</style></head><body>'
        '<h1>政策原文未核验的草稿</h1><p>原文 **字符** A|B；金额 1,234.56 万元。</p>'
        '<table><thead><tr><th>来源</th><th>缺项</th></tr></thead>'
        '<tbody><tr><td>年度表 A|B</td><td>**待核验**</td></tr></tbody></table>'
        '<p>https://example.gov.cn/source?id=1&amp;year=2025</p>'
        '</body></html>', encoding="utf-8",
    )
    original = source.read_bytes()
    output = tmp_path / "same-report.docx"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--input-file", str(source), str(output)],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(completed.stdout)["status"] == "passed"
    assert completed.stdout.count("\n") == 1
    document = Document(output)
    paragraphs = [p.text for p in document.paragraphs]
    assert "政策原文未核验的草稿" in paragraphs
    assert "原文 **字符** A|B；金额 1,234.56 万元。" in paragraphs
    assert "https://example.gov.cn/source?id=1&year=2025" in paragraphs
    assert "not report text" not in "\n".join(paragraphs)
    assert [[c.text for c in row.cells] for row in document.tables[0].rows] == [
        ["来源", "缺项"], ["年度表 A|B", "**待核验**"],
    ]
    assert source.read_bytes() == original


def test_html_headers_footers_and_chapter_titles_keep_their_word_roles(tmp_path: Path) -> None:
    source = tmp_path / "report-with-page-furniture.html"
    source.write_text(
        '<html><body><div class="gongchuang-document-header">共创研究院</div>'
        '<div class="gongchuang-cover-signature">封面署名</div><h1>分析草稿</h1>'
        '<section><div class="gongchuang-document-header">共创研究院</div>'
        '<header class="page-header"><span>01</span><b>现金流</b></header>'
        '<h2>经营收现需要核验</h2><p>2025 年度金额 1,234.56 万元，资料尚未取得。</p>'
        '<footer class="page-footer">财务分析｜报告署名</footer></section>'
        '<footer class="page-footer">财务分析｜报告署名</footer></body></html>', encoding="utf-8",
    )
    output = tmp_path / "report.docx"
    subprocess.run([sys.executable, str(SCRIPT), "--input-file", str(source), str(output)],
                   check=True, capture_output=True, text=True)
    document = Document(output)
    body = [p.text for p in document.paragraphs]
    assert body == ["分析草稿", "01 现金流", "经营收现需要核验", "2025 年度金额 1,234.56 万元，资料尚未取得。"]
    section = document.sections[0]
    assert [p.text for p in section.header.paragraphs if p.text] == ["共创研究院"]
    assert [p.text for p in section.footer.paragraphs if p.text] == ["财务分析｜报告署名"]
    assert [p.text for p in section.first_page_footer.paragraphs if p.text] == ["封面署名"]
    assert section.different_first_page_header_footer
    for paragraph in document.paragraphs[:3]:
        assert paragraph.paragraph_format.keep_with_next
        assert paragraph.paragraph_format.keep_together


def test_existing_template_chapter_headers_and_report_end_remain_in_body(tmp_path: Path) -> None:
    from lxml import html

    skills = SCRIPT.parents[2]
    tax = html.document_fromstring((skills / "manufacturing-tax-risk-analysis/assets/deep-gold-advisor-template.html").read_bytes())
    sales = html.document_fromstring((skills / "enterprise-panorama-analysis/assets/sales-master-template.html").read_bytes())
    chapter_headers = tax.xpath("//header[not(@class)]")[:2]
    report_end = sales.xpath('//footer[@class="report-end"]')[0]
    end_text = [p.text_content().replace("{{REPORT_DATE}}", "2026-10-17") for p in report_end.xpath("./p")]
    fragments = [html.tostring(node, encoding="unicode", with_tail=False) for node in chapter_headers]
    fragments.append(html.tostring(report_end, encoding="unicode", with_tail=False).replace("{{REPORT_DATE}}", "2026-10-17"))
    source = tmp_path / "template-body-semantics.html"
    source.write_text("<html><body>" + "".join(fragments) + "</body></html>", encoding="utf-8")
    output = tmp_path / "template-body-semantics.docx"
    subprocess.run([sys.executable, str(SCRIPT), "--input-file", str(source), str(output)],
                   check=True, capture_output=True, text=True)
    document = Document(output)
    body = [p.text for p in document.paragraphs]
    assert body[:2] == [node.text_content() for node in chapter_headers]
    assert body[-3:] == end_text
    assert "未核验事项保留待核" in body[-2]
    assert body[-1] == "报告日期：2026-10-17"
    assert not any(p.text for p in document.sections[0].header.paragraphs)
    assert not any(p.text for p in document.sections[0].footer.paragraphs)

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import subprocess
import sys
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn


def test_distinct_report_tables_have_separate_word_headers(tmp_path):
    script = Path(__file__).resolve().parents[1] / "skills/evidence-ledger/scripts/create_docx_from_text.py"
    spec = spec_from_file_location("report_docx_tables", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "report.docx"
    module.build_document("# 材料体检\n\n| 产品 | 技术 |\n|---|---|\n| PS01 | 补偿 |\n\n| IP | 状态 |\n|---|---|\n| IP01 | 授权 |\n", output)
    doc = Document(output)
    assert [[c.text for c in t.rows[0].cells] for t in doc.tables] == [["产品", "技术"], ["IP", "状态"]]
    assert doc.tables[0]._tbl.getnext().tag == qn("w:p")
    assert doc.tables[0]._tbl.getnext().getnext() is doc.tables[1]._tbl
    with ZipFile(output) as package:
        assert "word/fonts/gongchuang-noto-sans-sc.odttf" in package.namelist()
        assert b"Noto Sans SC" in package.read("word/fontTable.xml")
        assert b"embedRegular" in package.read("word/fontTable.xml")
        assert b"embedTrueTypeFonts" in package.read("word/settings.xml")
        assert "宋体" not in package.read("word/document.xml").decode("utf-8")


def test_source_table_long_urls_cannot_resize_other_columns(tmp_path):
    script = Path(__file__).resolve().parents[1] / "skills/evidence-ledger/scripts/create_docx_from_text.py"
    spec = spec_from_file_location("fixed_source_table", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "来源表.docx"
    url = "https://example.gov.cn/" + "long-path/" * 15
    body = f"# 来源清单\n| 序号 | 来源名称 | 发布机构 | 链接 | 采用属性 |\n|---|---|---|---|---|\n| 1 | 政策原文 | 主管部门 | {url} | 历史参考 |"
    module.build_document(body, output)
    doc = Document(output)
    section = doc.sections[0]
    assert abs(section.page_width.cm - 21) < 0.01
    assert abs(section.page_height.cm - 29.7) < 0.01
    table = doc.tables[0]
    assert not table.autofit
    widths = [c.width.cm for c in table.columns]
    assert abs(widths[0] - 1) < 0.01
    assert min(widths[1:]) > 3.8
    assert max(widths[1:]) - min(widths[1:]) < 0.01
    assert url in table.cell(1, 3).text


def test_long_report_file_input_preserves_all_text_and_rejects_oversize(tmp_path):
    script = Path(__file__).resolve().parents[1] / "skills/evidence-ledger/scripts/create_docx_from_text.py"
    source = tmp_path / "正文.md"
    output = tmp_path / "报告.docx"
    body = "技术改造与数字化情况。" * 1000
    source.write_text(body, encoding="utf-8")
    run = subprocess.run([sys.executable, str(script), "--input-file", str(source), str(output)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["characters"] == len(body)
    assert "\n".join(p.text for p in Document(output).paragraphs) == body
    source.write_bytes(b"x" * (1024 * 1024 + 1))
    rejected = tmp_path / "oversize.docx"
    run = subprocess.run([sys.executable, str(script), "--input-file", str(source), str(rejected)], capture_output=True, text=True)
    assert run.returncode != 0
    assert not rejected.exists()


def test_generic_docx_brand_header_reuses_embedded_font_and_signed_dependencies(tmp_path):
    root = Path(__file__).resolve().parents[1] / "skills"
    output = tmp_path / "品牌字体.docx"
    run = subprocess.run([sys.executable, str(root / "evidence-ledger/scripts/create_docx_from_text.py"),
                          "# 中文报告\n正文与品牌页眉需要中文字体。", str(output)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    run = subprocess.run([sys.executable, str(root / "evidence-ledger/scripts/apply_office_branding.py"),
                          str(output)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    doc = Document(output)
    runs = [r for s in doc.sections for p in s.header.paragraphs for r in p.runs if r.text.strip()]
    assert runs
    assert all(r.font.name == "Noto Sans SC" for r in runs)
    assert all(r._element.rPr.rFonts.get(qn("w:eastAsia")) == "Noto Sans SC" for r in runs)
    for _ in range(2):
        run = subprocess.run([sys.executable, str(root / "evidence-ledger/scripts/apply_office_branding.py"),
                              str(output)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
    doc = Document(output)
    for section in doc.sections:
        for header in (section.header, section.first_page_header, section.even_page_header):
            assert len(header.paragraphs) == 1
            assert header.paragraphs[0].text == "共创研究院"
            assert len(header._element.xpath('.//wp:anchor')) == 1
            assert header.paragraphs[0].paragraph_format.space_before.pt == 0
            assert header.paragraphs[0].paragraph_format.space_after.pt == 0
    registry = json.loads((root / "client-runtime-operations.json").read_text())
    operations = registry["operations"]
    for operation in operations:
        if operation["id"] in {"evidence-ledger.create-docx", "evidence-ledger.create-docx-from-file"}:
            assert "project-feasibility/scripts/fill_report_template.py" in operation["files"]
            assert "project-feasibility/assets/fonts/NotoSansSC-Variable.ttf" in operation["files"]


def test_revision_refuses_existing_file_and_can_generate_new_path(tmp_path):
    script = Path(__file__).resolve().parents[1] / "skills/evidence-ledger/scripts/create_docx_from_text.py"
    output = tmp_path / "original.docx"
    first = subprocess.run([sys.executable, str(script), "# Original\nOriginal content", str(output)], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    original = output.read_bytes()
    rejected = subprocess.run([sys.executable, str(script), "# Revision\nCorrected content", str(output)], capture_output=True, text=True)
    assert rejected.returncode != 0
    assert output.read_bytes() == original
    assert "原文件未修改" in rejected.stderr
    assert "尚不存在的新路径" in rejected.stderr
    assert "不得用旧文件" in rejected.stderr
    revision = tmp_path / "revision.docx"
    accepted = subprocess.run([sys.executable, str(script), "# Revision\nCorrected content", str(revision)], capture_output=True, text=True)
    assert accepted.returncode == 0, accepted.stderr
    assert "Corrected content" in [p.text for p in Document(revision).paragraphs]
    assert output.read_bytes() == original


def test_colon_labels_render_bold_without_changing_code_or_escaped_text(tmp_path):
    script = Path(__file__).resolve().parents[1] / "skills/evidence-ledger/scripts/create_docx_from_text.py"
    spec = spec_from_file_location("report_docx_labels", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "labels.docx"
    module.build_document("# 报告\n- **工业新产品：**正文12万元\n"
                          "- **TECH-A：**误差0.02毫米\n"
                          "`**字面：**`与\\*\\*保留：\\*\\*\n"
                          "| 条件 | 说明 |\n|---|---|\n| **门槛：**100 | 原值 |", output)
    doc = Document(output)
    paragraphs = doc.paragraphs
    assert paragraphs[1].text == "• 工业新产品：正文12万元"
    assert paragraphs[2].text == "• TECH-A：误差0.02毫米"
    assert paragraphs[3].text == "**字面：**与**保留：**"
    assert any(run.text == "工业新产品：" and run.bold for run in paragraphs[1].runs)
    assert doc.tables[0].cell(1, 0).text == "门槛：100"


def test_numbered_standard_clauses_stay_body_text(tmp_path):
    script = Path(__file__).resolve().parents[1] / "skills/evidence-ledger/scripts/create_docx_from_text.py"
    spec = spec_from_file_location("report_docx_clauses", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "standard.docx"
    lines = ["# 服务规范", "## 6 验证方法", "### 6.4 检索验证",
             "6.4.1 应按预设查询逐个验证。", "6.4.2 10个预设查询应全部返回对应文件。",
             "7.1 应保存记录。", "1. 普通有序列表"]
    module.build_document("\n\n".join(lines), output)
    doc = Document(output)
    for p, text in zip(doc.paragraphs[3:6], lines[3:6]):
        assert p.text == text
        assert not p.paragraph_format.keep_with_next
        assert all(not r.bold for r in p.runs)
    assert doc.paragraphs[2].style.name == "Heading 3"
    assert doc.paragraphs[6].text == lines[6]

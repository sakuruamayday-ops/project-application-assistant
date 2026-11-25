import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from patent_extractor import extract


EXTRACTION = "SKILL.md 核稿流程第1、2步：忠实提取原件正文及 OOXML 内容"
SECTIONS = "references/review-method.md 核查矩阵：摘要、权利要求、说明书及附图"
CLAIMS = "references/review-method.md 引用关系：解析直接引用并保留择一关系"
ABSENT = "SKILL.md 判断方法：片段缺少的章节归入未提供材料"


class PatentExtractorTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "申请.docx"

    def write_docx(self, *paragraphs):
        document = Document()
        for paragraph in paragraphs:
            document.add_paragraph(paragraph)
        document.save(self.path)
        return self.path

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "patent_extractor.py"), str(self.path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )

    def test_groups_sections_and_keeps_figure_description_in_specification(self):
        paragraphs = [
            "摘 要：", "公开一种定位夹具。",
            "权 利 要 求 书 :", "1. 一种定位夹具，包括底座。",
            "2、根据权利要求1所述的定位夹具，其特征在于底座设有导轨。",
            "说明书", "技术领域", "本申请涉及工装。", "背景技术", "现有夹具易偏移。",
            "附图说明", "图1为夹具总装图。", "具体实施方式", "导轨固定于底座。",
            "说明书附图", "图1 夹具总装图", "摘要附图", "图1",
        ]
        result = extract(self.write_docx(*paragraphs))
        expected = {
            "abstract_text": "公开一种定位夹具。",
            "claims": "\n".join(paragraphs[3:5]),
            "description": "\n".join(paragraphs[6:14]),
            "description_figs": "图1 夹具总装图",
            "abstract_fig": "图1",
        }
        self.assertEqual({key: result[key] for key in expected}, expected, SECTIONS)
        self.assertEqual(result["paragraphs"], paragraphs, EXTRACTION)

    def test_recovers_unnamed_sections_when_specification_has_a_title(self):
        result = extract(self.write_docx(
            "公开一种夹具。", "1．一种夹具，包括底座。", "2、根据权利要求1所述的夹具。",
            "定位夹具", "技 术 领 域", "本申请涉及工装。",
        ))
        expected = {
            "abstract_text": "公开一种夹具。",
            "claims": "1．一种夹具，包括底座。\n2、根据权利要求1所述的夹具。",
            "description": "定位夹具\n技 术 领 域\n本申请涉及工装。",
        }
        self.assertEqual({key: result[key] for key in expected}, expected, SECTIONS)

    def test_missing_claims_do_not_consume_numbered_description_steps(self):
        result = extract(self.write_docx(
            "权利要求书", "说明书", "技术领域", "1. 将导轨固定于底座。",
        ))
        self.assertEqual(result["claims"], "", ABSENT)
        self.assertEqual(result["description"], "技术领域\n1. 将导轨固定于底座。", SECTIONS)

    def test_claim_number_gap_is_preserved(self):
        result = extract(self.write_docx(
            "权利要求书", "1. 一种夹具，包括底座。", "3．根据权利要求1所述的夹具。",
        ))
        self.assertEqual(
            result["claims"].splitlines(),
            ["1. 一种夹具，包括底座。", "3．根据权利要求1所述的夹具。"],
            CLAIMS,
        )

    def test_reference_to_absent_claim_is_preserved_for_review(self):
        result = extract(self.write_docx(
            "权利要求书", "1. 一种夹具，包括底座。", "2、根据权利要求9所述的夹具。",
        ))
        self.assertEqual(
            result["claims"], "1. 一种夹具，包括底座。\n2、根据权利要求9所述的夹具。", CLAIMS,
        )

    def test_alternative_references_keep_all_numbers_and_wording(self):
        result = extract(self.write_docx(
            "权利要求书", "1. 一种夹具，包括底座。", "2. 根据权利要求1所述的夹具。",
            "3. 根据权利要求1或2所述的夹具，其特征在于底座设有导轨。",
        ))
        self.assertEqual(result["claims"].splitlines()[2],
                         "3. 根据权利要求1或2所述的夹具，其特征在于底座设有导轨。", CLAIMS)

    def test_long_paragraph_is_preserved_across_runs(self):
        document = Document()
        document.add_paragraph("说明书")
        paragraph = document.add_paragraph()
        middle = "夹具定位行程0123456789。" * 4000
        paragraph.add_run("实施例开始。").bold = True
        paragraph.add_run(middle)
        paragraph.add_run("实施例结束。")
        document.save(self.path)
        result = extract(self.path)
        self.assertEqual(result["description"], "实施例开始。" + middle + "实施例结束。", EXTRACTION)

    def test_table_text_is_extracted_in_body_order(self):
        document = Document()
        document.add_paragraph("说明书")
        document.add_paragraph("下表列出部件。")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "部件"
        table.cell(0, 1).text = "导轨"
        document.add_paragraph("导轨固定于底座。")
        document.save(self.path)
        result = extract(self.path)
        self.assertEqual(result["tables"], {"count": 1}, EXTRACTION)
        self.assertEqual(result["description"], "下表列出部件。\n部件\n导轨\n导轨固定于底座。", EXTRACTION)

    def test_reads_omml_expression_and_reports_its_part(self):
        document = Document()
        document.add_paragraph("说明书")
        paragraph = document.add_paragraph("行程公式：")
        paragraph._p.append(parse_xml(f'<m:oMath {nsdecls("m")}><m:r><m:t>s=vt</m:t></m:r></m:oMath>'))
        document.save(self.path)
        result = extract(self.path)
        self.assertEqual(result["equations"], [
            {"part": "word/document.xml", "index": "1", "text": "s=vt"},
        ], EXTRACTION)
        self.assertEqual(result["description"], "行程公式：s=vt", EXTRACTION)

    def test_empty_word_document_returns_empty_sections(self):
        result = extract(self.write_docx())
        expected = {
            "abstract_text": "", "claims": "", "description": "", "description_figs": "",
            "abstract_fig": "", "full_text": "", "paragraphs": [],
        }
        self.assertEqual({key: result[key] for key in expected}, expected, ABSENT)

    def test_non_docx_extension_has_explicit_validation_error(self):
        path = self.path.with_suffix(".doc")
        path.write_bytes(b"old format")
        with self.assertRaises(ValueError, msg=EXTRACTION) as error:
            extract(path)
        self.assertEqual(str(error.exception), "仅支持 OOXML .docx 文件；旧 .doc 请先转换为 .docx", EXTRACTION)

    def test_zero_bytes_and_text_disguised_as_docx_raise_zip_error(self):
        for content in (b"", "不是 Word 文件。".encode("utf-8")):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with self.assertRaisesRegex(BadZipFile, "^File is not a zip file$", msg=EXTRACTION):
                    extract(self.path)

    def test_cli_writes_json_and_prints_the_same_source_text(self):
        self.write_docx("权利要求书", "1. 一种夹具。", "说明书附图", "图1 夹具")
        original = self.path.read_bytes()
        output = self.path.with_name("extracted.json")
        process = self.run_cli("--output-json", str(output), "--extract-only", "--allow-partial")
        self.assertEqual(process.returncode, 0, EXTRACTION)
        self.assertEqual(json.loads(process.stderr)["missing_sections"], ["摘要", "说明书", "附图说明"], ABSENT)
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual((result["claims"], result["description_figs"]), ("1. 一种夹具。", "图1 夹具"), SECTIONS)
        self.assertEqual(process.stdout, "权利要求书\n1. 一种夹具。\n说明书附图\n图1 夹具\n", EXTRACTION)
        self.assertEqual(self.path.read_bytes(), original, EXTRACTION)

    def test_claims_expose_their_number_kind_and_direct_references(self):
        result = extract(self.write_docx(
            "权利要求书", "1. 一种夹具，包括底座。", "3. 根据权利要求1所述的夹具。",
            "4. 根据权利要求1或3所述的夹具。", "5. 根据权利要求9所述的夹具。",
            "6. 如权利要求 1—3 中任一项所述的夹具。", "7. 根据权利要求 6 所述的夹具。",
        ))
        self.assertEqual(result.get("claim_items"), [
            {"number": 1, "type": "independent"},
            {"number": 3, "type": "dependent", "references": [1]},
            {"number": 4, "type": "dependent", "references": [1, 3]},
            {"number": 5, "type": "dependent", "references": [9]},
            {"number": 6, "type": "dependent", "references": [1, 2, 3]},
            {"number": 7, "type": "dependent", "references": [6]},
        ], CLAIMS)

    def test_claims_without_a_specification_title_keep_the_last_claim(self):
        for preceding_paragraphs, last_claim in (
            (("公开一种夹具。",), ("2. 根据权利要求1所述的夹具。",)),
            (("摘要", "公开一种夹具。", "权利要求书"), ("2. 根据权利要求1所述的夹具。",)),
            (("公开一种夹具。",), ("2. 根据权利要求1所述的夹具，其特征在于：", "（1）底座设有导轨；", "（2）导轨连接夹块。")),
        ):
            with self.subTest(preceding_paragraphs=preceding_paragraphs, last_claim=last_claim):
                claims = ("1. 一种夹具，包括底座。", *last_claim)
                result = extract(self.write_docx(
                    *preceding_paragraphs, *claims, "技术领域", "本申请涉及工装。",
                ))
                self.assertEqual(
                    (result["claims"], result["description"]),
                    ("\n".join(claims), "技术领域\n本申请涉及工装。"),
                    SECTIONS,
                )

    def test_cli_rejects_non_docx_and_empty_file_without_tracebacks(self):
        for filename, content, reason in (
            ("bad.doc", b"old format", "仅支持 OOXML .docx 文件；旧 .doc 请先转换为 .docx"),
            ("empty.docx", b"", "文件为空"),
            ("fake.docx", b"text", "文件不是有效的 DOCX 压缩包"),
        ):
            with self.subTest(filename=filename):
                self.path = self.path.with_name(filename)
                self.path.write_bytes(content)
                process = self.run_cli()
                self.assertEqual((process.returncode, process.stdout), (1, ""), EXTRACTION)
                self.assertNotIn("Traceback", process.stderr, EXTRACTION)
                self.assertEqual(
                    json.loads(process.stderr), {"error": reason, "size_bytes": len(content)}, EXTRACTION,
                )

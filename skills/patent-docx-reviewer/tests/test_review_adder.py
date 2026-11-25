import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from review_adder import add_comments


LOCATION = "SKILL.md 核稿流程第3、4步：按原文定位，在副本批注"
PRESERVATION = "SKILL.md 核稿流程第1、4、5步：保留原件及副本正文、格式和 OOXML 部件"
SCOPE = "SKILL.md 核稿流程第3步及输出：范围影响、权利要求依据与意见单一致"
MISSING_SCOPE = "references/review-method.md 引用关系：缺范围判断依据时标明材料并保留原文"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def comment_texts(path):
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/comments.xml"))
    return [
        (comment.get(qn("w:id")), "".join(node.text or "" for node in comment.findall(".//w:t", NS)))
        for comment in root.findall("w:comment", NS)
    ]


def comment_markers(path):
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    marker_names = {
        qn("w:commentRangeStart"): "start",
        qn("w:commentRangeEnd"): "end",
        qn("w:commentReference"): "reference",
    }
    markers = []
    for index, paragraph in enumerate(root.findall(".//w:p", NS)):
        offset = 0
        for node in paragraph.iter():
            if node.tag == qn("w:t"):
                offset += len(node.text or "")
            elif node.tag in marker_names:
                markers.append((index, marker_names[node.tag], node.get(qn("w:id")), offset))
    return markers


class ReviewAdderTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "申请.docx"
        self.target = self.source.with_name("批注.docx")

    def write_docx(self, *paragraphs):
        document = Document()
        for paragraph in paragraphs:
            document.add_paragraph(paragraph)
        document.save(self.source)

    def test_inserts_one_comment_at_the_exact_anchor(self):
        self.write_docx("前文导轨后文。")
        result = add_comments(self.source, self.target, [{"highlight_text": "导轨", "comment": "核对名称。"}])
        self.assertEqual(result, {
            "expected": 1, "applied": 1, "exact_anchors": 1, "paragraph_anchors": 0,
            "skipped": [], "output": str(self.target),
        }, LOCATION)
        self.assertEqual(comment_markers(self.target), [
            (0, "start", "0", 2), (0, "end", "0", 4), (0, "reference", "0", 4),
        ], LOCATION)
        self.assertEqual(comment_texts(self.target), [("0", "核对名称。")], LOCATION)

    def test_run_split_preserves_text_whitespace_and_format(self):
        document = Document()
        paragraph = document.add_paragraph(style="Heading 2")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph.paragraph_format.space_after = Pt(7)
        run = paragraph.add_run("前文 导轨 后文")
        run.bold = True
        run.italic = True
        run.font.name = "仿宋"
        run.font.size = Pt(14)
        run.font.color.rgb = RGBColor.from_string("124578")
        document.save(self.source)
        add_comments(self.source, self.target, [{"highlight_text": "导轨", "comment": "核对名称。"}])
        paragraph = Document(self.target).paragraphs[0]
        self.assertEqual(paragraph.text, "前文 导轨 后文", PRESERVATION)
        self.assertEqual(
            (paragraph.style.name, paragraph.alignment, paragraph.paragraph_format.space_after),
            ("Heading 2", WD_ALIGN_PARAGRAPH.RIGHT, Pt(7)),
            PRESERVATION,
        )
        run_format = [
            (item.text, item.bold, item.italic, item.font.name, item.font.size, str(item.font.color.rgb))
            for item in paragraph.runs if item.text
        ]
        self.assertEqual(run_format, [
            ("前文 ", True, True, "仿宋", Pt(14), "124578"),
            ("导轨", True, True, "仿宋", Pt(14), "124578"),
            (" 后文", True, True, "仿宋", Pt(14), "124578"),
        ], PRESERVATION)
        self.assertEqual(
            [(node.text, node.get(qn("xml:space"))) for node in paragraph._p.findall("w:r/w:t", NS)],
            [("前文 ", "preserve"), ("导轨", None), (" 后文", "preserve")],
            PRESERVATION,
        )

    def test_anchor_crosses_two_differently_formatted_runs(self):
        document = Document()
        paragraph = document.add_paragraph()
        paragraph.add_run("前缀夹").bold = True
        paragraph.add_run("块后缀").italic = True
        document.save(self.source)
        result = add_comments(self.source, self.target, [{"highlight_text": "夹块", "comment": "核对夹块。"}])
        self.assertEqual((result["exact_anchors"], result["paragraph_anchors"]), (1, 0), LOCATION)
        self.assertEqual(comment_markers(self.target), [
            (0, "start", "0", 2), (0, "end", "0", 4), (0, "reference", "0", 4),
        ], LOCATION)
        reopened = Document(self.target).paragraphs[0]
        self.assertEqual([(run.text, run.bold, run.italic) for run in reopened.runs if run.text], [
            ("前缀", True, None), ("夹", True, None), ("块", None, True), ("后缀", None, True),
        ], PRESERVATION)

    def test_multiple_reviews_attach_to_different_ranges_in_one_paragraph(self):
        self.write_docx("导轨固定在底座上。")
        result = add_comments(self.source, self.target, [
            {"highlight_text": "导轨", "comment": "核对导轨。"},
            {"highlight_text": "底座", "comment": "核对底座。"},
        ])
        self.assertEqual((result["applied"], result["exact_anchors"], result["skipped"]), (2, 2, []), LOCATION)
        self.assertEqual(comment_markers(self.target), [
            (0, "start", "0", 0), (0, "end", "0", 2), (0, "reference", "0", 2),
            (0, "start", "1", 5), (0, "end", "1", 7), (0, "reference", "1", 7),
        ], LOCATION)
        self.assertEqual(comment_texts(self.target), [("0", "核对导轨。"), ("1", "核对底座。")], LOCATION)

    def test_same_review_selects_each_requested_matching_paragraph(self):
        self.write_docx("导轨固定。", "夹块与支架连接。", "后侧的导轨固定。")
        review = {"highlight_text": "导轨", "comment": "两处名称相同，请核对。"}
        result = add_comments(self.source, self.target, [review, {**review, "occurrence": 2}])
        self.assertEqual((result["applied"], result["skipped"]), (2, []), LOCATION)
        self.assertEqual(comment_markers(self.target), [
            (0, "start", "0", 0), (0, "end", "0", 2), (0, "reference", "0", 2),
            (2, "start", "1", 3), (2, "end", "1", 5), (2, "reference", "1", 5),
        ], LOCATION)
        self.assertEqual(comment_texts(self.target), [
            ("0", "两处名称相同，请核对。"), ("1", "两处名称相同，请核对。"),
        ], LOCATION)

    def test_cli_copies_all_three_scope_labels_and_claim_basis_verbatim(self):
        self.write_docx("底座设有导轨和夹块。")
        reviews = [
            {
                "highlight_text": "底座",
                "suggestion": "意见摘要",
                "comment": "建议并入从属特征。\n保护范围影响：限缩\n权利要求依据：第2项的‘双导轨’。",
            },
            {
                "highlight_text": "导轨",
                "suggestion": "意见摘要",
                "comment": "建议复核数量限定。\n保护范围影响：扩大\n权利要求依据：第1项的‘两个导轨’。",
            },
            {
                "highlight_text": "夹块",
                "suggestion": "意见摘要",
                "comment": "建议统一标记。\n保护范围影响：不动\n权利要求依据：第1项的‘夹块’特征保留。",
            },
        ]
        review_path = self.source.with_name("review.json")
        review_path.write_text(json.dumps({"reviews": reviews}, ensure_ascii=False), encoding="utf-8")
        process = subprocess.run([
            sys.executable, str(SCRIPTS / "review_adder.py"), str(self.source), str(self.target),
            "--reviews-file", str(review_path),
        ], capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual((process.returncode, process.stderr), (0, ""), SCOPE)
        self.assertEqual(json.loads(process.stdout)["applied"], 3, SCOPE)
        self.assertEqual(comment_texts(self.target), [
            (str(index), review["comment"]) for index, review in enumerate(reviews)
        ], SCOPE)

    def test_missing_scope_evidence_note_and_original_are_kept(self):
        original_text = "底座设有导轨。"
        self.write_docx(original_text)
        comment = "补齐材料前保留原文。\n缺范围判断依据：第2项权利要求原稿及图1。"
        add_comments(self.source, self.target, [{"highlight_text": "导轨", "comment": comment}])
        self.assertEqual(comment_texts(self.target), [("0", comment)], MISSING_SCOPE)
        self.assertEqual(Document(self.target).paragraphs[0].text, original_text, MISSING_SCOPE)

    def test_missing_anchor_reports_exact_skip_reason_without_markers(self):
        self.write_docx("底座设有导轨。", "图1为总装图。")
        result = add_comments(self.source, self.target, [{"highlight_text": "手柄", "comment": "查手柄。"}])
        self.assertEqual((result["applied"], result["skipped"]), (0, [
            {"anchor": "手柄", "reason": "未定位到指定 occurrence"},
        ]), LOCATION)
        self.assertEqual((comment_markers(self.target), comment_texts(self.target)), ([], []), LOCATION)

    def test_oversized_occurrence_reports_error_with_other_review_applied(self):
        self.write_docx("导轨固定。", "底座设有导轨。")
        result = add_comments(self.source, self.target, [
            {"highlight_text": "导轨", "occurrence": 3, "comment": "第3处。"},
            {"highlight_text": "底座", "comment": "核对底座。"},
        ])
        self.assertEqual((result["applied"], result["skipped"]), (1, [
            {"anchor": "导轨", "reason": "未定位到指定 occurrence"},
        ]), LOCATION)
        self.assertEqual(comment_markers(self.target), [
            (1, "start", "0", 0), (1, "end", "0", 2), (1, "reference", "0", 2),
        ], LOCATION)
        self.assertEqual(comment_texts(self.target), [("0", "核对底座。")], LOCATION)

    def test_paragraph_without_addressable_runs_reports_error(self):
        document = Document()
        paragraph = document.add_paragraph()
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("w:anchor"), "图1")
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "附图引用"
        run.append(text)
        hyperlink.append(run)
        paragraph._p.append(hyperlink)
        document.save(self.source)
        result = add_comments(self.source, self.target, [{"highlight_text": "附图引用", "comment": "核对附图。"}])
        self.assertEqual((result["applied"], result["skipped"]), (0, [
            {"anchor": "附图引用", "reason": "目标段落没有可批注文本"},
        ]), LOCATION)
        self.assertEqual(comment_markers(self.target), [], LOCATION)

    def test_fallback_reports_paragraph_precision_and_preserves_inline_breaks(self):
        self.write_docx("定位\t导轨\n安装。", "图1为夹具。")
        result = add_comments(self.source, self.target, [{"highlight_text": "导轨", "comment": "核对导轨。"}])
        self.assertEqual((result["exact_anchors"], result["paragraph_anchors"], result["skipped"]), (0, 1, []), LOCATION)
        self.assertEqual(comment_markers(self.target), [
            (0, "start", "0", 0), (0, "end", "0", 7), (0, "reference", "0", 7),
        ], LOCATION)
        self.assertEqual(Document(self.target).paragraphs[0].text, "定位\t导轨\n安装。", PRESERVATION)

    def test_document_reopens_with_original_paragraphs_table_and_character_count(self):
        document = Document()
        document.add_paragraph("权利要求书")
        document.add_paragraph("1. 一种定位夹具，包括底座。")
        document.add_paragraph("说明书")
        document.add_table(rows=1, cols=1).cell(0, 0).text = "图1 底座"
        document.save(self.source)
        original = self.source.read_bytes()
        add_comments(self.source, self.target, [{"highlight_text": "图1", "comment": "核对表内图号。"}])
        reopened = Document(self.target)
        body = [paragraph.text for paragraph in reopened.paragraphs]
        body += [reopened.tables[0].cell(0, 0).text]
        expected = ["权利要求书", "1. 一种定位夹具，包括底座。", "说明书", "图1 底座"]
        self.assertEqual(body, expected, PRESERVATION)
        self.assertEqual(sum(map(len, body)), sum(map(len, expected)), PRESERVATION)
        self.assertEqual(self.source.read_bytes(), original, PRESERVATION)
        self.assertEqual(comment_markers(self.target), [
            (3, "start", "0", 0), (3, "end", "0", 2), (3, "reference", "0", 2),
        ], LOCATION)

    def test_registers_comment_part_content_type_and_relationship(self):
        self.write_docx("底座设有导轨。")
        add_comments(self.source, self.target, [{"highlight_text": "导轨", "comment": "核对导轨。"}])
        with ZipFile(self.target) as archive:
            relations = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
            content_types = ET.fromstring(archive.read("[Content_Types].xml"))
        comment_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
        self.assertEqual([node.get("Target") for node in relations if node.get("Type") == comment_type],
                         ["comments.xml"], PRESERVATION)
        self.assertEqual([node.get("ContentType") for node in content_types if node.get("PartName") == "/word/comments.xml"],
                         ["application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"], PRESERVATION)

    def test_negative_occurrence_is_rejected_without_annotating_a_paragraph(self):
        self.write_docx("导轨固定。", "底座设有导轨。")
        for occurrence in (-1, 0, True, 1.5, "1"):
            with self.subTest(occurrence=occurrence):
                with self.assertRaisesRegex(ValueError, "occurrence.*从 1 开始的正整数", msg=LOCATION):
                    add_comments(self.source, self.target, [
                        {"highlight_text": "底座", "comment": "有效位置。"},
                        {"highlight_text": "导轨", "occurrence": occurrence, "comment": "无效位置。"},
                    ])
                self.assertFalse(self.target.exists(), LOCATION)

    def test_adding_another_review_keeps_existing_comment_and_unique_markers(self):
        self.write_docx("底座设有导轨。")
        add_comments(self.source, self.target, [{"highlight_text": "底座", "comment": "原批注。"}])
        next_target = self.target.with_name("第二轮批注.docx")
        add_comments(self.target, next_target, [{"highlight_text": "导轨", "comment": "新增批注。"}])
        self.assertEqual((comment_texts(next_target), comment_markers(next_target)), (
            [("0", "原批注。"), ("1", "新增批注。")],
            [
                (0, "start", "0", 0), (0, "end", "0", 2), (0, "reference", "0", 2),
                (0, "start", "1", 4), (0, "end", "1", 6), (0, "reference", "1", 6),
            ],
        ), PRESERVATION)

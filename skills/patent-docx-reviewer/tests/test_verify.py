import json
import struct
import subprocess
import sys
import unittest
import zlib
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from docx import Document


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from verify import verify


PACKAGE = "SKILL.md 核稿流程第5步：比较 OOXML 部件、媒体、关系和正文"
SECTIONS = "references/review-method.md 核查矩阵：分别核查摘要、权利要求、说明书和附图"
COMMENTS = "SKILL.md 核稿流程第3至5步及输出：意见与批注逐条对应，并核验副本"
STRUCTURE = "references/review-method.md 核查矩阵·文件结构：核查 OOXML 部件与关系完整性"
DOCUMENT_XML = "word/document.xml"
COMMENTS_XML = "word/comments.xml"
RELATIONSHIPS = "word/_rels/document.xml.rels"
IMAGE = "word/media/image1.png"
COMMENT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}comment"


def png_pixel(red, green, blue):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes((0, red, green, blue)))) + chunk(b"IEND", b"")
    )


class VerifyTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "申请.docx"
        self.target = self.source.with_name("批注.docx")

        document = Document()
        document.add_paragraph("摘要")
        abstract = document.add_paragraph("公开一种定位夹具。")
        document.add_paragraph("权利要求书")
        claim = document.add_paragraph("1. 一种定位夹具，包括底座和导轨。")
        document.add_paragraph("说明书")
        document.add_paragraph("技术领域")
        document.add_paragraph("本申请涉及定位工装。")
        document.add_paragraph("附图说明")
        document.add_paragraph("图1是定位夹具总装图。")
        document.add_paragraph("说明书附图")
        document.add_picture(BytesIO(png_pixel(0, 0, 0)))
        document.add_paragraph("摘要附图")
        document.add_picture(BytesIO(png_pixel(0, 0, 0)))
        document.save(self.source)

        document.add_comment(abstract.runs[0], text="核对摘要。", author="核稿测试", initials="测")
        document.add_comment(claim.runs[0], text="核对术语。", author="核稿测试", initials="测")
        document.save(self.target)

    def assert_report(self, report, *, basis=PACKAGE, **changes):
        expected = {
            "valid": True,
            "text_equal": True,
            "comments_present": True,
            "missing_parts": [],
            "changed_assets": [],
            "unbound_namespace_prefixes": [],
        }
        expected.update(changes)
        self.assertEqual({field: report.get(field) for field in expected}, expected, basis)

    def read_part(self, name):
        with ZipFile(self.target) as archive:
            return archive.read(name)

    def rewrite_target(self, replacements):
        altered = self.target.with_name("改动后.docx")
        with ZipFile(self.target) as source, ZipFile(altered, "w") as target:
            for name in source.namelist():
                data = replacements[name] if name in replacements else source.read(name)
                if data is not None:
                    target.writestr(name, data)
        return altered

    def without_specification(self):
        document = Document(self.target)
        paragraphs = document.paragraphs
        titles = [paragraph.text for paragraph in paragraphs]
        for paragraph in paragraphs[titles.index("说明书"):titles.index("说明书附图")]:
            paragraph._p.getparent().remove(paragraph._p)
        path = self.target.with_name("缺少说明书.docx")
        document.save(path)
        return path

    def run_cli(self, target, *args):
        return subprocess.run([
            sys.executable, str(SCRIPTS / "verify.py"), str(self.source), str(target), *args,
        ], capture_output=True, text=True, encoding="utf-8", timeout=10)

    def test_complete_commented_docx_passes_all_checks(self):
        self.assert_report(verify(self.source, self.target))

    def test_missing_comments_is_reported_even_when_the_body_matches(self):
        no_comments = self.rewrite_target({COMMENTS_XML: None})
        self.assert_report(verify(self.source, no_comments), basis=COMMENTS,
                           valid=False, comments_present=False, missing_parts=[COMMENTS_XML])

    def test_changed_description_text_is_reported(self):
        document = Document(self.target)
        paragraph = next(item for item in document.paragraphs if item.text == "本申请涉及定位工装。")
        paragraph.text = "本申请涉及检测工装。"
        document.save(self.target)
        self.assert_report(verify(self.source, self.target), valid=False, text_equal=False)

    def test_removing_specification_from_output_causes_text_mismatch(self):
        self.assert_report(verify(self.source, self.without_specification()),
                           basis=SECTIONS, valid=False, text_equal=False)

    def test_missing_styles_part_is_reported_by_path(self):
        altered = self.rewrite_target({"word/styles.xml": None})
        self.assert_report(verify(self.source, altered), basis=STRUCTURE,
                           valid=False, missing_parts=["word/styles.xml"])

    def test_modified_figure_is_reported_by_media_path(self):
        altered = self.rewrite_target({IMAGE: png_pixel(255, 0, 0)})
        self.assert_report(verify(self.source, altered), valid=False, changed_assets=[IMAGE])

    def test_deleted_figure_is_reported_as_missing_and_changed(self):
        altered = self.rewrite_target({IMAGE: None})
        self.assert_report(verify(self.source, altered), valid=False, missing_parts=[IMAGE], changed_assets=[IMAGE])

    def test_unbound_ignorable_namespace_reports_part_and_prefix(self):
        xml = self.read_part(DOCUMENT_XML).replace(b'mc:Ignorable="', b'mc:Ignorable="ghostPat ', 1)
        altered = self.rewrite_target({DOCUMENT_XML: xml})
        self.assert_report(verify(self.source, altered), basis=STRUCTURE, valid=False,
                           unbound_namespace_prefixes=["word/document.xml: ghostPat"])

    def test_cli_writes_passing_report_to_json_and_stdout(self):
        output = self.target.with_name("verification.json")
        process = self.run_cli(self.target, "--output-json", str(output), "--expected-comments", "2")
        self.assertEqual((process.returncode, process.stderr), (0, ""), PACKAGE)
        self.assert_report(json.loads(output.read_text(encoding="utf-8")))
        self.assertEqual(json.loads(process.stdout), json.loads(output.read_text(encoding="utf-8")), PACKAGE)

    def test_cli_writes_a_specific_failure_report_for_uncommented_docx(self):
        process = self.run_cli(self.source, "--expected-comments", "2")
        self.assertEqual((process.returncode, process.stderr), (1, ""), COMMENTS)
        self.assert_report(json.loads(process.stdout), basis=COMMENTS, valid=False, comments_present=False)

    def test_report_names_the_missing_section(self):
        self.assert_report(verify(self.source, self.without_specification()),
                           basis=SECTIONS, valid=False, text_equal=False, missing_sections=["说明书"])

    def test_comment_record_count_mismatch_is_reported(self):
        comments = ET.fromstring(self.read_part(COMMENTS_XML))
        comments.remove(comments.findall(COMMENT_TAG)[1])
        altered = self.rewrite_target({COMMENTS_XML: ET.tostring(comments, encoding="utf-8")})
        # 两处正文批注引用只剩一条批注记录，期望报告两个实际数量。
        self.assert_report(verify(self.source, altered), basis=COMMENTS, valid=False,
                           comment_count_mismatch={"references": 2, "comments": 1})

        for marker in ("commentReference", "commentRangeStart", "commentRangeEnd"):
            with self.subTest(marker=marker):
                xml = self.read_part(DOCUMENT_XML).replace(
                    f'<w:{marker} w:id="1"'.encode(), f'<w:{marker} w:id="9"'.encode(),
                )
                report = verify(self.source, self.rewrite_target({DOCUMENT_XML: xml}))
                self.assert_report(report, basis=COMMENTS, valid=False)
                self.assertTrue(report.get("comment_reference_errors"), COMMENTS)
                self.assertNotIn("comment_count_mismatch", report, COMMENTS)

    def test_missing_document_xml_returns_the_specific_missing_part(self):
        altered = self.rewrite_target({DOCUMENT_XML: None})
        self.assert_report(verify(self.source, altered), basis=STRUCTURE,
                           valid=False, text_equal=False, missing_parts=[DOCUMENT_XML])

    def test_malformed_document_xml_returns_a_structured_failure(self):
        altered = self.rewrite_target({DOCUMENT_XML: b"<w:document"})
        process = self.run_cli(altered, "--structure-only")
        report = json.loads(process.stdout) if process.stdout else {}
        self.assertEqual({
            "exit_code": process.returncode,
            "valid": report.get("valid"),
            "invalid_xml_parts": report.get("invalid_xml_parts"),
            "traceback": "Traceback" in process.stderr,
        }, {"exit_code": 1, "valid": False, "invalid_xml_parts": [DOCUMENT_XML], "traceback": False}, STRUCTURE)

    def test_dangling_comment_relationship_reports_the_missing_target(self):
        relations = ET.fromstring(self.read_part(RELATIONSHIPS))
        link = next(item for item in relations if item.get("Type", "").endswith("/comments"))
        link.set("Target", "missing-comments.xml")
        altered = self.rewrite_target({RELATIONSHIPS: ET.tostring(relations, encoding="utf-8")})
        self.assert_report(verify(self.source, altered), basis=STRUCTURE,
                           valid=False, missing_parts=["word/missing-comments.xml"])
        for target, valid in (("styles.xml", False), ("/word/comments.xml", True)):
            with self.subTest(target=target):
                link.set("Target", target)
                altered = self.rewrite_target({RELATIONSHIPS: ET.tostring(relations, encoding="utf-8")})
                self.assert_report(verify(self.source, altered), basis=STRUCTURE, valid=valid)

        relations.remove(link)
        altered = self.rewrite_target({RELATIONSHIPS: ET.tostring(relations, encoding="utf-8")})
        report = verify(self.source, altered)
        self.assert_report(report, basis=STRUCTURE, valid=False)
        self.assertTrue(report.get("comment_relationship_errors"), STRUCTURE)

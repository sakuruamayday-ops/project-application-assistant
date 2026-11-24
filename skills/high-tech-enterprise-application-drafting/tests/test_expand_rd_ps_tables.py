import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "expand_rd_ps_tables.py"
FILL_SCRIPT = SCRIPT.with_name("fill_rd_core_innovation.py")
TEMPLATE = SCRIPT.parents[1] / "assets" / "高新技术企业认定申请书空白模板.docx"
RD_MARKER = "研发活动编号："
PS_MARKER = "编号："
RD_NAME = "研发活动名称"
RD_BUDGET = "研发经费总预算（万元）"
PS_NAME = "产品（服务）名称"
PS_INCOME = "上年度销售收入（万元）"
PS_MAIN = "是否主要产品（服务）"
IP_LABEL = "知识产权编号"

RD_FIELDS = (
    RD_NAME,
    "起止时间",
    "技术\n领域",
    RD_BUDGET,
    "研发经费近三年总支出（万元）",
    IP_LABEL,
    "目的及组织实施方式（限400字）",
    "核心技术及创新点（限400字）",
    "取得的\n阶段性成果（限400字）",
)
PS_FIELDS = (
    PS_NAME,
    "技术领域",
    PS_INCOME,
    PS_MAIN,
    IP_LABEL,
    "关键技术及主要技术指标（限400字）",
    "与同类产品（服务）的竞争优势（限400字）",
)
RD_A = {
    RD_NAME: "分体夹具定位研究",
    "起止时间": "2025.01.01-2025.12.31",
    RD_BUDGET: "70.00",
    IP_LABEL: "IP01",
}
RD_B = {
    RD_NAME: "快换夹具结构研究",
    "取得的\n阶段性成果（限400字）": "已形成图纸。\n已验收样机。",
    RD_BUDGET: "80.00",
    IP_LABEL: "IP02",
}
PS_A = {PS_NAME: "精密定位夹具", PS_INCOME: "120.50", PS_MAIN: "☑是 □否", IP_LABEL: "IP01"}
PS_B = {PS_NAME: "快换装夹组件", PS_INCOME: "85.25", PS_MAIN: "□是 ☑否", IP_LABEL: "IP02"}


def rows_text(table):
    return [tuple(cell.text for cell in row.cells) for row in table.rows]


def layout_xml(element):
    layout = deepcopy(element)
    for node in list(layout.iter(qn("w:t"))):
        node.getparent().remove(node)
    return layout.xml


def markers(document, prefix):
    return [
        paragraph for paragraph in document.paragraphs if paragraph.text.startswith(prefix)
    ]


class ExpandRdPsTablesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.input_path = self.work_dir / "输入申请书.docx"
        self.output_path = self.work_dir / "输出申请书.docx"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_application(self, *, rd=(), ps=(), links=None):
        document = Document()
        document.add_paragraph("高新技术企业认定申请书")
        document.add_paragraph("四、企业研究开发活动情况表")
        for code, values in rd:
            self.add_unit(document, RD_MARKER + code, RD_FIELDS, values, "Table Grid")
        if links is not None:
            rd_code, ps_code = links
            document.add_paragraph("2025年度研发费用结构明细表")
            expense = document.add_table(rows=1, cols=2)
            expense.rows[0].cells[0].text = "研发项目编号"
            expense.rows[0].cells[1].text = rd_code
        document.add_paragraph("六、上年度高新技术产品（服务）情况表")
        for code, values in ps:
            data = {PS_MAIN: "□是 □否", **values}
            self.add_unit(document, PS_MARKER + code, PS_FIELDS, data, "Light Shading Accent 1")
        if links is not None:
            document.add_paragraph("高新技术产品（服务）汇总表")
            summary = document.add_table(rows=2, cols=4)
            for row, texts in zip(
                summary.rows,
                (
                    ("PS编号", "产品（服务）名称", "对应RD", "知识产权"),
                    (ps_code, "精密定位夹具", rd_code, "IP01"),
                ),
            ):
                for cell, value in zip(row.cells, texts):
                    cell.text = value
        document.save(self.input_path)

    def add_unit(self, document, marker, fields, values, style):
        document.add_page_break()
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph.paragraph_format.keep_with_next = True
        run = paragraph.add_run(marker)
        run.bold = True
        run.font.size = Pt(12)
        table = document.add_table(rows=len(fields), cols=3)
        table.style = style
        table.autofit = False
        for column, width in zip(table.columns, (Cm(4), Cm(5), Cm(6))):
            column.width = width
        for index, (row, label) in enumerate(zip(table.rows, fields)):
            row.height = Pt(20 + index)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            label_cell, value_cell, extra_cell = row.cells
            value_cell.merge(extra_cell)
            label_paragraph = label_cell.paragraphs[0]
            label_paragraph.paragraph_format.keep_with_next = True
            label_paragraph.add_run(label).bold = True
            paragraph = value_cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(4)
            run = paragraph.add_run(values.get(label, ""))
            run.font.name = "宋体"
            run.font.size = Pt(12)

    def run_resize(self, *options, output=None, check=False):
        return subprocess.run(
            [
                sys.executable, "-B", "-X", "utf8", str(SCRIPT),
                str(self.input_path), str(output or self.output_path), *options,
            ],
            cwd=self.work_dir,
            capture_output=True,
            encoding="utf-8",
            check=check,
            timeout=20,
        )

    def resize(self, *options):
        process = self.run_resize(*options, check=True)
        return json.loads(process.stdout), Document(self.output_path)

    def assert_rejected(self, process, message, *, returncode):
        self.assertEqual(process.returncode, returncode, process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertIn(message, process.stderr)
        self.assertIs(self.output_path.exists(), False)

    def assert_cloned_forms(self, before, after, fields, marker, *, defaults=None):
        """SKILL.md §模板与回填接口保留原表、复制完整编号段并清空新增数据区。"""
        defaults = defaults or {}
        self.assertEqual([len(table.rows) for table in after.tables], [len(fields)] * 3)
        self.assertEqual(
            [rows_text(table) for table in after.tables[:2]],
            [rows_text(table) for table in before.tables],
        )
        self.assertEqual(
            [
                (label, first.strip(), second.strip())
                for label, first, second in rows_text(after.tables[2])
            ],
            [(label, defaults.get(label, ""), defaults.get(label, "")) for label in fields],
        )
        self.assertEqual(
            [layout_xml(table._tbl) for table in after.tables],
            [layout_xml(before.tables[index]._tbl) for index in (0, 1, 1)],
        )
        source_markers = markers(before, marker)
        new_marker = markers(after, marker)[2]
        self.assertEqual(layout_xml(new_marker._p), layout_xml(source_markers[1]._p))
        self.assertEqual(
            [node.get(qn("w:type")) for node in new_marker._p.getprevious().iter(qn("w:br"))],
            ["page"],
        )

    def test_rd_expansion_numbers_every_form_and_reports_added_codes(self):
        """SKILL.md §模板与回填接口规定增表后从 RD01 连续编号。"""
        self.write_application(rd=(("RD06", RD_A), ("RD08", RD_B)))
        report, document = self.resize("--rd-count", "4")
        self.assertEqual(
            [paragraph.text for paragraph in markers(document, RD_MARKER)],
            ["研发活动编号：RD01", "研发活动编号：RD02", "研发活动编号：RD03", "研发活动编号：RD04"],
        )
        self.assertEqual(len(document.tables), 4)
        self.assertEqual(
            report["rd"],
            {
                "before": 2, "requested": 4, "after": 4, "operation": "expand",
                "added": ["RD03", "RD04"], "removed": [], "renumbered_continuously": True,
            },
        )

    def test_ps_expansion_numbers_every_form_and_reports_added_codes(self):
        """SKILL.md §模板与回填接口规定增表后从 PS01 连续编号。"""
        self.write_application(ps=(("PS04", PS_A), ("PS07", PS_B)))
        report, document = self.resize("--ps-count", "4")
        self.assertEqual(
            [paragraph.text for paragraph in markers(document, PS_MARKER)],
            ["编号：PS01", "编号：PS02", "编号：PS03", "编号：PS04"],
        )
        self.assertEqual(len(document.tables), 4)
        self.assertEqual(
            report["ps"],
            {
                "before": 2, "requested": 4, "after": 4, "operation": "expand",
                "added": ["PS03", "PS04"], "removed": [], "renumbered_continuously": True,
            },
        )

    def test_rd_expansion_keeps_layout_and_original_row_content(self):
        """references/writing-rules.md §一要求保留合并、列宽、行高、边框、段落及分页。"""
        self.write_application(rd=(("RD01", RD_A), ("RD02", RD_B)))
        before = Document(self.input_path)
        _, after = self.resize("--rd-count", "3")
        self.assert_cloned_forms(before, after, RD_FIELDS, RD_MARKER)

    def test_ps_expansion_keeps_layout_and_resets_new_checkbox(self):
        """SKILL.md §模板与回填接口要求保留已有勾选并清空新增数据区。"""
        self.write_application(ps=(("PS01", PS_A), ("PS02", PS_B)))
        before = Document(self.input_path)
        _, after = self.resize("--ps-count", "3")
        self.assert_cloned_forms(before, after, PS_FIELDS, PS_MARKER, defaults={PS_MAIN: "□是 □否"})

    def test_rd_trim_to_one_preserves_first_form_and_records_original_markers(self):
        """SKILL.md §模板与回填接口规定仅删空白尾表、新编号及默认审计文件。"""
        self.write_application(rd=(("RD06", RD_A), ("RD08", {}), ("RD09", {})))
        before = Document(self.input_path)
        report, after = self.resize("--rd-count", "1", "--trim-empty-tail")
        self.assertEqual([paragraph.text for paragraph in markers(after, RD_MARKER)], ["研发活动编号：RD01"])
        self.assertEqual([len(table.rows) for table in after.tables], [9])
        self.assertEqual(rows_text(after.tables[0]), rows_text(before.tables[0]))
        self.assertEqual(layout_xml(after.tables[0]._tbl), layout_xml(before.tables[0]._tbl))
        page_breaks = [
            node for node in after.element.body.iter(qn("w:br")) if node.get(qn("w:type")) == "page"
        ]
        self.assertEqual(len(page_breaks), 1)
        outcome = report["rd"]
        self.assertEqual(
            tuple(outcome[key] for key in ("before", "requested", "after", "operation", "renumbered_continuously")),
            (3, 1, 1, "trim", True),
        )
        self.assertEqual(
            [(item["position"], item["original_marker"], item["reason"]) for item in outcome["removed"]],
            [(2, "研发活动编号：RD08", "末尾完全空白表"), (3, "研发活动编号：RD09", "末尾完全空白表")],
        )
        audit_path = self.output_path.with_suffix(".docx.audit.json")
        self.assertEqual(json.loads(audit_path.read_text(encoding="utf-8")), report)

    def test_ps_trim_to_one_preserves_first_form_and_writes_requested_audit(self):
        """SKILL.md §模板与回填接口要求保留有内容的 PS，只移除末尾全空白表。"""
        self.write_application(ps=(("PS03", PS_A), ("PS08", {})))
        before = Document(self.input_path)
        audit_path = self.work_dir / "缩表记录.json"
        report, after = self.resize("--ps-count", "1", "--trim-empty-tail", "--report", str(audit_path))
        self.assertEqual([paragraph.text for paragraph in markers(after, PS_MARKER)], ["编号：PS01"])
        self.assertEqual([len(table.rows) for table in after.tables], [7])
        self.assertEqual(rows_text(after.tables[0]), rows_text(before.tables[0]))
        self.assertEqual(layout_xml(after.tables[0]._tbl), layout_xml(before.tables[0]._tbl))
        outcome = report["ps"]
        self.assertEqual(
            tuple(outcome[key] for key in ("before", "requested", "after", "operation", "renumbered_continuously")),
            (2, 1, 1, "trim", True),
        )
        self.assertEqual(
            [(item["position"], item["original_marker"], item["reason"]) for item in outcome["removed"]],
            [(2, "编号：PS08", "末尾完全空白表")],
        )
        self.assertEqual(json.loads(audit_path.read_text(encoding="utf-8")), report)

    def test_shrinking_requires_explicit_tail_trim_for_both_form_types(self):
        """SKILL.md §模板与回填接口要求以 --trim-empty-tail 明确授权缩表。"""
        self.write_application(
            rd=(("RD01", RD_A), ("RD02", {})),
            ps=(("PS01", PS_A), ("PS02", {})),
        )
        for kind in ("rd", "ps"):
            with self.subTest(kind=kind):
                process = self.run_resize(f"--{kind}-count", "1")
                self.assert_rejected(process, f"{kind.upper()}目标数量1小于现有数量2", returncode=2)
                self.assertIn("--trim-empty-tail", process.stderr)

    def test_rd_tail_with_zero_budget_blocks_all_deletions(self):
        """SKILL.md §模板与回填接口要求保护尾表中已有经费，0 也是填写值。"""
        self.write_application(
            rd=(("RD01", RD_A), ("RD02", {}), ("RD03", {RD_BUDGET: "0"})),
        )
        original = self.input_path.read_bytes()
        process = self.run_resize("--rd-count", "1", "--trim-empty-tail")
        self.assert_rejected(process, "RD缩表已阻断", returncode=2)
        self.assertIn("RD03（第4行第2列='0'）", process.stderr)
        self.assertIn("未删除任何表格", process.stderr)
        self.assertEqual(self.input_path.read_bytes(), original)

    def test_ps_checked_tail_blocks_output_even_when_rd_can_expand(self):
        """SKILL.md §模板与回填接口把已有勾选视为内容并要求整体核对。"""
        self.write_application(
            rd=(("RD01", RD_A),),
            ps=(("PS01", PS_A), ("PS02", {PS_MAIN: "☑是 □否"})),
        )
        original = self.input_path.read_bytes()
        audit_path = self.work_dir / "缩表记录.json"
        process = self.run_resize(
            "--rd-count", "2", "--ps-count", "1", "--trim-empty-tail", "--report", str(audit_path),
        )
        self.assert_rejected(process, "PS缩表已阻断", returncode=2)
        self.assertIn("PS02（第4行第2列='☑是 □否'）", process.stderr)
        self.assertIs(audit_path.exists(), False)
        self.assertEqual(self.input_path.read_bytes(), original)

    def test_zero_rejected_for_both_form_types(self):
        """SKILL.md §模板与回填接口编号从 01 开始，CLI 明确要求每类至少一张。"""
        self.write_application(rd=(("RD01", {}),), ps=(("PS01", {}),))
        for kind in ("rd", "ps"):
            with self.subTest(kind=kind):
                process = self.run_resize(f"--{kind}-count", "0", "--trim-empty-tail")
                self.assert_rejected(process, f"{kind.upper()}数量必须不小于1", returncode=1)

    def test_target_one_keeps_the_existing_rd_and_ps(self):
        """SKILL.md §模板与回填接口按最终数量复制同类表，已有一张时保留原填写内容。"""
        self.write_application(rd=(("RD01", RD_A),), ps=(("PS01", PS_A),))
        before = Document(self.input_path)
        report, after = self.resize("--rd-count", "1", "--ps-count", "1")
        self.assertEqual([len(table.rows) for table in after.tables], [9, 7])
        self.assertEqual([rows_text(table) for table in after.tables], [rows_text(table) for table in before.tables])
        for kind in ("rd", "ps"):
            with self.subTest(kind=kind):
                self.assertEqual(
                    report[kind],
                    {
                        "before": 1, "requested": 1, "after": 1, "operation": "unchanged",
                        "added": [], "removed": [], "renumbered_continuously": True,
                    },
                )

    def test_target_one_requires_a_source_form_of_the_same_kind(self):
        """SKILL.md §模板与回填接口要求从同类完整表格深拷贝。"""
        self.write_application()
        for kind in ("rd", "ps"):
            with self.subTest(kind=kind):
                process = self.run_resize(f"--{kind}-count", "1")
                self.assert_rejected(
                    process, f"文档中未找到可复制的{kind.upper()}表", returncode=2,
                )

    def test_in_place_resize_is_rejected(self):
        """SKILL.md §模板与回填接口要求另存新路径保留原件。"""
        self.write_application(rd=(("RD01", RD_A),))
        original = self.input_path.read_bytes()
        process = self.run_resize("--rd-count", "2", output=self.input_path)
        self.assert_rejected(process, "输出文件不得与输入文件相同", returncode=1)
        self.assertEqual(self.input_path.read_bytes(), original)

    def test_expansion_preserves_already_correct_links_and_unrelated_tables(self):
        """references/summary-table-contract.md §高新技术产品（服务）汇总表保留已确认映射。"""
        self.write_application(rd=(("RD01", RD_A),), ps=(("PS01", PS_A),), links=("RD01", "PS01"))
        original = self.input_path.read_bytes()
        _, document = self.resize("--rd-count", "2", "--ps-count", "2")
        self.assertEqual(len(document.tables), 6)
        self.assertEqual(rows_text(document.tables[2]), [("研发项目编号", "RD01")])
        self.assertEqual(
            rows_text(document.tables[5]),
            [
                ("PS编号", "产品（服务）名称", "对应RD", "知识产权"),
                ("PS01", "精密定位夹具", "RD01", "IP01"),
            ],
        )
        self.assertEqual(self.input_path.read_bytes(), original)

    def test_numbering_and_report_match_when_form_count_reaches_100(self):
        self.write_application(rd=(("RD01", {}),), ps=(("PS01", {}),), links=("RD01", "PS01"))
        _, document = self.resize("--rd-count", "99", "--ps-count", "99")
        reference = document.add_paragraph("正文：")
        reference.add_run("RD9")
        reference.add_run("9、PS99；XRD99、RD99A、PS99_附录")
        self.add_rd_ps_mapping(document, "RD99", "PS99")
        document.save(self.input_path)

        report, document = self.resize("--rd-count", "100", "--ps-count", "100", "--overwrite")
        self.assert_numbered(document, "RD", 100, 3)
        self.assert_numbered(document, "PS", 100, 3)
        self.assertEqual(len(document.tables), 203)
        self.assertEqual(report["rd"]["added"], ["RD100"])
        self.assertEqual(report["ps"]["added"], ["PS100"])
        self.assert_summary_links(document, 100, "RD001", "PS001")
        self.assertEqual(rows_text(document.tables[-1])[-1], ("RD099", "PS099"))
        self.assertEqual(document.paragraphs[-2].text, "正文：RD099、PS099；XRD99、RD99A、PS99_附录")

    def assert_numbered(self, document, kind, count, width):
        prefix = RD_MARKER if kind == "RD" else PS_MARKER
        self.assertEqual(
            [paragraph.text for paragraph in markers(document, prefix)],
            [f"{prefix}{kind}{index:0{width}d}" for index in range(1, count + 1)],
        )

    def assert_summary_links(self, document, rd_count, rd, ps):
        expense = document.tables[rd_count]
        summary = document.tables[rd_count + 1 + len(markers(document, PS_MARKER))]
        self.assertEqual(expense.cell(0, 1).text, rd)
        self.assertEqual(rows_text(summary)[1], (ps, "精密定位夹具", rd, "IP01"))

    def add_rd_ps_mapping(self, document, rd, ps):
        document.add_paragraph("RD/PS 对照表")
        table = document.add_table(rows=2, cols=2)
        for row, values in zip(table.rows, (("研发活动", "产品"), (rd, ps))):
            for cell, value in zip(row.cells, values):
                cell.text = value

    def test_numbering_and_references_at_one_and_two(self):
        for count in (1, 2):
            with self.subTest(count=count):
                self.write_application(rd=(("RD06", RD_A),), ps=(("PS07", PS_A),), links=("RD06", "PS07"))
                _, document = self.resize("--rd-count", str(count), "--ps-count", str(count), "--overwrite")
                self.assert_numbered(document, "RD", count, 2)
                self.assert_numbered(document, "PS", count, 2)
                self.assert_summary_links(document, count, "RD01", "PS01")

    def test_numbering_and_one_pass_references_at_99(self):
        self.write_application(
            rd=(("RD02", RD_A), ("RD01", RD_B)),
            ps=(("PS02", PS_A), ("PS01", PS_B)),
            links=("RD02", "PS02"),
        )
        document = Document(self.input_path)
        document.add_paragraph("正文：RD02、RD01、PS02、PS01")
        self.add_rd_ps_mapping(document, "RD01", "PS01")
        document.save(self.input_path)
        _, document = self.resize("--rd-count", "99", "--ps-count", "99")
        self.assert_numbered(document, "RD", 99, 2)
        self.assert_numbered(document, "PS", 99, 2)
        self.assert_summary_links(document, 99, "RD01", "PS01")
        self.assertEqual(document.paragraphs[-2].text, "正文：RD01、RD02、PS01、PS02")
        self.assertEqual(rows_text(document.tables[-1])[-1], ("RD02", "PS02"))

    def test_rd_and_ps_number_widths_are_independent(self):
        for rd_count, ps_count, rd, ps in ((100, 2, "RD001", "PS01"), (2, 100, "RD01", "PS001")):
            with self.subTest(rd_count=rd_count, ps_count=ps_count):
                self.write_application(rd=(("RD06", RD_A),), ps=(("PS07", PS_A),), links=("RD06", "PS07"))
                _, document = self.resize("--rd-count", str(rd_count), "--ps-count", str(ps_count), "--overwrite")
                self.assert_numbered(document, "RD", rd_count, len(rd) - 2)
                self.assert_numbered(document, "PS", ps_count, len(ps) - 2)
                self.assert_summary_links(document, rd_count, rd, ps)

    def test_150_forms_keep_numbering_links_and_repeating_headers(self):
        self.write_application(rd=(("RD10", RD_A),), ps=(("PS10", PS_A),), links=("RD10", "PS10"))
        document = Document(self.input_path)
        document.add_paragraph("正文：RD10、PS10")
        document.sections[0].header.paragraphs[0].text = "页眉：RD10、PS10"
        self.add_rd_ps_mapping(document, "RD10", "PS10")
        for index in (0, 2):
            document.tables[index].rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        document.save(self.input_path)

        report, document = self.resize("--rd-count", "150", "--ps-count", "150")
        self.assert_numbered(document, "RD", 150, 3)
        self.assert_numbered(document, "PS", 150, 3)
        self.assertEqual(report["rd"]["added"][-1], "RD150")
        self.assertEqual(report["ps"]["added"][-1], "PS150")
        self.assertEqual(len(document.tables), 303)
        self.assert_summary_links(document, 150, "RD001", "PS001")
        self.assertEqual(document.paragraphs[-2].text, "正文：RD001、PS001")
        self.assertEqual(document.sections[0].header.paragraphs[0].text, "页眉：RD001、PS001")
        self.assertEqual(rows_text(document.tables[-1])[-1], ("RD001", "PS001"))
        for kind, first_label in ((RD_MARKER, RD_NAME), (PS_MARKER, PS_NAME)):
            for marker in markers(document, kind):
                table = marker._p.getnext()
                self.assertEqual(table.tag, qn("w:tbl"))
                self.assertEqual(next(table.iter(qn("w:t"))).text, first_label)
                self.assertEqual(len(list(table.iter(qn("w:tblHeader")))), 1)

    def test_trim_from_150_to_50_rewrites_surviving_links(self):
        self.write_application(rd=(("RD01", RD_A),), ps=(("PS01", PS_A),), links=("RD01", "PS01"))
        _, document = self.resize("--rd-count", "150", "--ps-count", "150")
        document.add_paragraph("正文：RD001、RD050、PS001、PS050")
        self.add_rd_ps_mapping(document, "RD050", "PS050")
        document.save(self.input_path)

        report, document = self.resize("--rd-count", "50", "--ps-count", "50", "--trim-empty-tail", "--overwrite")
        self.assert_numbered(document, "RD", 50, 2)
        self.assert_numbered(document, "PS", 50, 2)
        self.assert_summary_links(document, 50, "RD01", "PS01")
        self.assertEqual(rows_text(document.tables[-1])[-1], ("RD50", "PS50"))
        self.assertEqual(document.paragraphs[-2].text, "正文：RD01、RD50、PS01、PS50")
        for kind in ("rd", "ps"):
            self.assertEqual(report[kind]["operation"], "trim")
            self.assertEqual(
                [item["code"] for item in report[kind]["removed"]],
                [f"{kind.upper()}{index:03d}" for index in range(51, 151)],
            )

    def test_trim_large_document_refuses_to_leave_a_dangling_reference(self):
        self.write_application(rd=(("RD01", {}),))
        _, document = self.resize("--rd-count", "100")
        document.add_paragraph("已有对应项目：RD100")
        document.save(self.input_path)
        output = self.work_dir / "缩表候选.docx"
        process = self.run_resize("--rd-count", "50", "--trim-empty-tail", output=output)
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertIn("原编号RD100仍有引用", process.stderr)
        self.assertFalse(output.exists())

    def test_form_numbers_grow_to_four_digits(self):
        self.write_application(rd=(("RD01", {}),), ps=(("PS01", {}),), links=("RD01", "PS01"))
        report, document = self.resize("--rd-count", "1000")
        self.assert_numbered(document, "RD", 1000, 4)
        self.assert_numbered(document, "PS", 1, 2)
        self.assert_summary_links(document, 1000, "RD0001", "PS01")
        self.assertEqual(report["rd"]["added"][-1], "RD1000")

    def test_real_template_updates_numbering_note_and_blank_expense_examples(self):
        document = Document(TEMPLATE)
        document.save(self.input_path)
        _, document = self.resize("--rd-count", "100", "--ps-count", "2")
        self.assert_numbered(document, "RD", 100, 3)
        self.assert_numbered(document, "PS", 2, 2)
        self.assertEqual(rows_text(document.tables[105])[0][1:4], ("RD001", "RD002", "RD003"))
        note = next(paragraph.text for paragraph in document.paragraphs if "IP代表知识产权编号" in paragraph.text)
        self.assertIn("RD、PS表按用户申报的研发项目与产品数量生成", note)
        self.assertNotIn("IP、RD、PS后取两位数", note)

    def test_fill_writes_rd10_rd100_and_rd1000_to_distinct_forms(self):
        codes = ("RD10", "RD100", "RD1000")
        self.write_application(rd=tuple((code, {}) for code in codes))
        spec = self.work_dir / "研发回填.json"
        spec.write_text(
            json.dumps({
                "schema_version": 1,
                "items": [
                    {"rd_id": code, "basic_fields": {RD_NAME: f"回填项目 {code}"}}
                    for code in codes
                ],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        process = subprocess.run(
            [sys.executable, "-B", str(FILL_SCRIPT), str(self.input_path), str(spec), str(self.output_path)],
            capture_output=True, encoding="utf-8", check=True, timeout=20,
        )
        self.assertEqual(list(json.loads(process.stdout)["rd"]), list(codes))
        document = Document(self.output_path)
        self.assertEqual([table.cell(0, 1).text for table in document.tables], [f"回填项目 {code}" for code in codes])

    def assert_links_follow_numbering(self, kind, target, *, trim=False):
        """references/summary-table-contract.md §高新技术产品（服务）汇总表规定 RD 映射。"""
        rd = [("RD06", RD_A)] if kind == "rd" else [("RD01", RD_A)]
        ps = [("PS04", PS_A)] if kind == "ps" else [("PS01", PS_A)]
        if trim and kind == "rd":
            rd.append(("RD08", {}))
        if trim and kind == "ps":
            ps.append(("PS08", {}))
        self.write_application(rd=rd, ps=ps, links=(rd[0][0], ps[0][0]))
        options = [f"--{kind}-count", str(target)]
        if trim:
            options.append("--trim-empty-tail")
        _, document = self.resize(*options)
        prefix = RD_MARKER if kind == "rd" else PS_MARKER
        self.assertEqual(markers(document, prefix)[0].text, f"{prefix}{kind.upper()}01")
        expense = document.tables[target if kind == "rd" else 1]
        summary = document.tables[-1]
        self.assertEqual(
            (expense.cell(0, 1).text, summary.cell(1, 2).text, summary.cell(1, 0).text),
            ("RD01", "RD01", "PS01"),
        )

    def test_rd_expansion_updates_expense_and_product_summary_links(self):
        """SKILL.md §模板与回填接口及 references/summary-table-contract.md §高新技术产品（服务）汇总表。"""
        self.assert_links_follow_numbering("rd", 2)

    def test_rd_trimming_updates_expense_and_product_summary_links(self):
        """SKILL.md §模板与回填接口及 references/application-fields-format.md 的 rd_financials。"""
        self.assert_links_follow_numbering("rd", 1, trim=True)

    def test_ps_expansion_updates_product_summary_link(self):
        """SKILL.md §模板与回填接口、§汇总表规定连续编号并保留对应产品映射。"""
        self.assert_links_follow_numbering("ps", 2)

    def test_ps_trimming_updates_product_summary_link(self):
        """SKILL.md §模板与回填接口、§汇总表要求缩表后连续编号及保留产品映射。"""
        self.assert_links_follow_numbering("ps", 1, trim=True)


if __name__ == "__main__":
    unittest.main()

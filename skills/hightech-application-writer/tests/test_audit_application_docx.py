import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_application_docx.py"
INNOVATION_SECTIONS = (
    "知识产权对企业竞争力的作用",
    "科技成果转化情况",
    "研究开发与技术创新组织管理情况",
    "管理与科技人员情况",
)
FIELD = "先进制造与自动化／先进制造技术／机械基础件及制造技术／高精度加工技术"
RD_CORE = "核心技术及创新点（限400字）"
RD_STAGE = "取得的阶段性成果（限400字）"
PS_INCOME = "上年度销售收入（万元）"
PS_LIMITED_FIELDS = (
    "关键技术及主要技术指标（限400字）",
    "与同类产品（服务）的竞争优势（限400字）",
    "知识产权获得情况及其对产品（服务）在技术上发挥的支持作用（限400字）",
)
CORE_LINES = (
    f"所属技术领域：{FIELD}。",
    "核心技术：",
    "1、限位校准技术：以定位销约束侧移。实测技术指标为0.2毫米。",
    "2、快换装夹技术：采用分体卡扣。实测技术指标为30秒。",
    "创新点：",
    "1、增加定位销，按同批工件测量重复定位偏差。",
    "2、将夹头与基座分离，按相同工况记录换型时间。",
)
STAGE_LINES = (
    "1、项目于2025年完成样机验收。",
    "2、已形成夹具装配图和试制样件。",
    "3、分体夹具专利IP01已授权。",
    "4、样机已用于精密结构件的小批量试生产。",
)


class AuditApplicationDocxTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.input_path = self.work_dir / "申请书.docx"
        self.evidence_path = self.work_dir / "创新能力证据.json"
        self.evidence_path.write_text(
            json.dumps(
                {
                    "allowed_corporate_names": ["甲例精密有限公司"],
                    "policy_titles": ["研发项目管理制度"],
                    "allowed_result_claims": ["试制夹具已用于小批量试生产"],
                    "allowed_personnel_claims": ["科技人员8名，占职工总数20.00%"],
                    "allow_financing_claims": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.document = Document()
        self.registration = self.add_fields(
            "企业注册登记表",
            (("企业名称", "甲例精密有限公司"), ("注册时间", "2020.05.12")),
        )
        self.document.add_paragraph("一、主要情况")
        self.summary = self.document.add_table(rows=0, cols=4)
        for values in (
            ("年度", "净资产（万元）", "销售收入（万元）", "利润总额（万元）"),
            ("2023", "100.00", "200.00", "20.00"),
            ("2024", "115.00", "220.00", "22.00"),
            ("2025", "130.00", "230.00", "23.00"),
        ):
            for cell, value in zip(self.summary.add_row().cells, values):
                cell.text = value
        self.rd = self.add_rd("RD01")
        self.expense = self.add_fields(
            "2025年度研发费用结构明细表",
            (("研发项目编号", "RD01"), ("研究开发费用（内、外部）小计", "18.00")),
        )
        self.ps = self.add_fields(
            "编号：PS01",
            (
                ("产品（服务）名称", "精密定位夹具"),
                ("技术领域", FIELD),
                ("技术来源", "自主研发"),
                (PS_INCOME, "120.50"),
                ("是否主要产品（服务）", "☑是 □否"),
                ("知识产权编号", "IP01"),
                (PS_LIMITED_FIELDS[0], "标准工况重复定位偏差实测为0.2毫米。"),
                (PS_LIMITED_FIELDS[1], "分体结构便于按工件规格更换夹头。"),
                (PS_LIMITED_FIELDS[2], "已授权的IP01支撑夹头与基座的连接结构。"),
            ),
        )
        self.innovation = self.add_fields(
            "七、企业创新能力",
            (
                (INNOVATION_SECTIONS[0], "已授权的IP01保护分体夹具连接结构。"),
                (INNOVATION_SECTIONS[1], "试制夹具已用于小批量试生产。"),
                (INNOVATION_SECTIONS[2], "按《研发项目管理制度》组织样机验收。"),
                (INNOVATION_SECTIONS[3], "现有科技人员8名，占职工总数20.00%。"),
            ),
            limited=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_fields(self, heading, fields, *, limited=False):
        self.document.add_paragraph(heading)
        table = self.document.add_table(rows=0, cols=2)
        rows = {}
        for label, value in fields:
            row = table.add_row()
            row.cells[0].text = f"{label}（限400字）" if limited else label
            row.cells[1].text = value
            rows[label] = row
        return rows

    def add_rd(self, code):
        return self.add_fields(
            f"研发活动编号：{code}",
            (
                ("研发活动名称", "分体夹具定位研究"),
                ("起止时间", "2023.01.01-2025.12.31"),
                ("技术领域", FIELD),
                ("技术来源", "自主研发"),
                ("知识产权编号", "IP01"),
                ("研发经费总预算（万元）", "50.00"),
                ("研发经费近三年总支出（万元）", "45.00"),
                ("第一年", "12.00"),
                ("第二年", "15.00"),
                ("第三年", "18.00"),
                ("目的及组织实施方式（限400字）", "研发组负责结构设计和重复定位验证。"),
                (RD_CORE, "\n".join(CORE_LINES)),
                (RD_STAGE, "\n".join(STAGE_LINES)),
            ),
        )

    def apply_template_font(self):
        paragraphs = list(self.document.paragraphs)
        for table in self.document.tables:
            for row in table.rows:
                for cell in row.cells:
                    paragraphs.extend(cell.paragraphs)
        for paragraph in paragraphs:
            for run in paragraph.runs:
                run.font.name = "宋体"
                run.font.size = Pt(12)
                run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def run_audit(self, *, check=False):
        return subprocess.run(
            [
                sys.executable, "-B", "-X", "utf8", str(SCRIPT), str(self.input_path),
                "--innovation-evidence", str(self.evidence_path),
            ],
            cwd=self.work_dir,
            capture_output=True,
            encoding="utf-8",
            check=check,
            timeout=20,
        )

    def findings(self):
        self.apply_template_font()
        self.document.save(self.input_path)
        return json.loads(self.run_audit(check=True).stdout)

    def assert_issue_at(self, report, *patterns):
        issue_records = [
            json.dumps(issue, ensure_ascii=False)
            for key, entries in report.items()
            if key.endswith("issues") and isinstance(entries, list)
            for issue in entries
        ]
        matching = [
            record for record in issue_records
            if all(re.search(pattern, record) for pattern in patterns)
        ]
        self.assertEqual(
            len(matching), 1,
            f"应有一条问题同时包含 {patterns!r}，实际问题为 {issue_records!r}",
        )

    def test_complete_sample_reports_no_issues(self):
        """SKILL.md §章节写法 3–6、§检查与交付规定的正文结构及宋体 12 磅。"""
        report = self.findings()
        expected = {
            "font_issue_count": 0,
            "font_issue_sample": [],
            "placeholder_count": 0,
            "placeholder_sample": [],
            "innovation_issue_count": 0,
            "innovation_issues": [],
            "rd_core_issue_count": 0,
            "rd_core_issues": [],
            "rd_stage_issue_count": 0,
            "rd_stage_issues": [],
            "limited_field_issue_count": 0,
            "limited_field_issues": [],
        }
        self.assertEqual({key: report[key] for key in expected}, expected)
        self.assertEqual(tuple(report["innovation_capability"]), INNOVATION_SECTIONS)
        core = report["rd_core_innovation"]["RD01"]
        self.assertEqual(
            (core["field"], core["line_count"], core["core_technology_count"], core["innovation_count"]),
            (FIELD, 7, 2, 2),
        )
        self.assertEqual(report["rd_stage_results"]["RD01"]["line_count"], 4)

    def test_missing_rd_core_value_cell_identifies_the_rd(self):
        """references/rd-core-innovation-format.md §输入JSON 按标签定位相邻物理格。"""
        label, value = self.rd[RD_CORE].cells
        label.merge(value).text = RD_CORE
        self.assertEqual(
            self.findings()["rd_core_issues"],
            [{"rd_id": "RD01", "issue": "领域或核心技术数据单元格缺失"}],
        )

    def test_missing_innovation_row_identifies_section(self):
        """references/enterprise-innovation-capability-format.md §一规定四栏完整。"""
        row = self.innovation[INNOVATION_SECTIONS[3]]._tr
        row.getparent().remove(row)
        self.assertEqual(
            self.findings()["innovation_issues"],
            [{"section": "企业创新能力", "issue": f"四栏顺序或完整性错误：{list(INNOVATION_SECTIONS[:3])}"}],
        )

    def test_innovation_rows_out_of_order_identify_section(self):
        """references/enterprise-innovation-capability-format.md §一规定四栏的先后顺序。"""
        first = self.innovation[INNOVATION_SECTIONS[0]]._tr
        second = self.innovation[INNOVATION_SECTIONS[1]]._tr
        first.addprevious(second)
        actual_order = [INNOVATION_SECTIONS[1], INNOVATION_SECTIONS[0], *INNOVATION_SECTIONS[2:]]
        self.assertEqual(
            self.findings()["innovation_issues"],
            [{"section": "企业创新能力", "issue": f"四栏顺序或完整性错误：{actual_order}"}],
        )

    def test_wrong_font_and_size_report_the_affected_text(self):
        """references/writing-rules.md §一规定母版宋体小四 12 磅。"""
        self.apply_template_font()
        run = self.document.paragraphs[0].runs[0]
        run.font.name = "黑体"
        run.font.size = Pt(11)
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
        self.document.save(self.input_path)
        report = json.loads(self.run_audit(check=True).stdout)
        self.assertEqual(report["font_issue_count"], 1)
        self.assertEqual(
            report["font_issue_sample"],
            [{"text": "企业注册登记表", "font": "黑体", "eastAsia": "黑体", "size": 11.0}],
        )

    def test_pending_ip_marker_is_reported_verbatim(self):
        """references/writing-rules.md §二「四项阶段性成果」和 §七要求汇总 XXX 缺口。"""
        cell = self.rd[RD_STAGE].cells[1]
        cell.text = STAGE_LINES[0]
        for line in (STAGE_LINES[1], "3、知识产权编号XXX。", STAGE_LINES[3]):
            cell.add_paragraph(line)
        report = self.findings()
        self.assertEqual(report["placeholder_count"], 1)
        self.assertEqual(report["placeholder_sample"], ["3、知识产权编号XXX。"])

    def test_rd_header_and_body_technical_fields_must_match(self):
        """SKILL.md §章节写法 4 要求正文所属领域与本 RD 表头一致。"""
        self.rd["技术领域"].cells[1].text = "另一四级技术领域"
        self.assertEqual(
            self.findings()["rd_core_issues"],
            [{"rd_id": "RD01", "issue": "正文所属技术领域与本RD表头不一致"}],
        )

    def test_rd_core_requires_seven_lines(self):
        """SKILL.md §章节写法 4 规定七行和第七行的第二条创新点。"""
        self.rd[RD_CORE].cells[1].text = "\n".join(CORE_LINES[:6])
        self.assertEqual(
            self.findings()["rd_core_issues"],
            [
                {"rd_id": "RD01", "issue": "应为7行，实际为6行"},
                {"rd_id": "RD01", "issue": "第7行必须以2、开头"},
            ],
        )

    def test_rd_core_reports_missing_number_and_unit_at_their_lines(self):
        """references/writing-rules.md §二「核心技术」要求两条均有数值和单位或阈值。"""
        lines = list(CORE_LINES)
        lines[2] = "1、限位校准技术：以定位销约束侧移。实测技术指标为稳定。"
        lines[3] = "2、快换装夹技术：采用分体卡扣。实测技术指标为30。"
        self.rd[RD_CORE].cells[1].text = "\n".join(lines)
        self.assertEqual(
            self.findings()["rd_core_issues"],
            [
                {"rd_id": "RD01", "issue": "第3行须为具名核心技术并含拟定或实测技术指标与数值"},
                {"rd_id": "RD01", "issue": "第4行技术指标缺少单位或阈值边界"},
            ],
        )

    def test_rd_core_limit_excludes_field_and_headings(self):
        """SKILL.md §章节写法 4 的 400 字只计算两条技术和两条创新点。"""
        fixed_length = sum(len(line) for line in (*CORE_LINES[2:4], CORE_LINES[5], "2、"))
        for length, expected in (
            (400, []),
            (401, [{"rd_id": "RD01", "issue": "核心技术与创新点合计401字，超过400字上限"}]),
        ):
            with self.subTest(length=length):
                line = "2、" + "测" * (length - fixed_length)
                self.rd[RD_CORE].cells[1].text = "\n".join((*CORE_LINES[:6], line))
                report = self.findings()
                self.assertEqual(report["rd_core_innovation"]["RD01"]["body_length"], length)
                self.assertEqual(report["rd_core_issues"], expected)
                self.assertEqual(report["limited_field_issues"], [])

    def test_eleven_empty_rd_stage_results_are_reported_with_rd_ids(self):
        rd_ids = [f"RD{number:02d}" for number in range(1, 12)]
        for rd_id in rd_ids:
            rd = self.rd if rd_id == "RD01" else self.add_rd(rd_id)
            rd[RD_STAGE].cells[1].text = ""
        self.add_rd("RD12")

        report = self.findings()
        self.assertEqual(report["rd_stage_issue_count"], 11)
        self.assertEqual(report["rd_stage_issues"], [
            {"rd_id": rd_id, "issue": "阶段性成果未填写"} for rd_id in rd_ids
        ])

    def test_rd_stage_result_with_only_breaks_tabs_and_fullwidth_spaces_is_empty(self):
        cell = self.rd[RD_STAGE].cells[1]
        cell.text = " \n\t\u3000"
        cell.add_paragraph("\u00a0")

        report = self.findings()
        self.assertEqual(report["rd_stage_issue_count"], 1)
        self.assertEqual(report["rd_stage_results"]["RD01"], {
            "line_count": 0, "body_length": 0, "issues": ["阶段性成果未填写"],
        })

    def test_rd_stage_result_with_four_items_and_padding_is_filled(self):
        self.rd[RD_STAGE].cells[1].text = "\n\u3000" + "\n\n".join(STAGE_LINES) + "\t\n"

        report = self.findings()
        self.assertEqual(report["rd_stage_issue_count"], 0)
        self.assertEqual(report["rd_stage_results"]["RD01"]["line_count"], 4)

    def test_rd_stage_results_require_four_numbered_items(self):
        """references/section-writing-templates.md §RD四项阶段性成果规定四项及顺序。"""
        self.rd[RD_STAGE].cells[1].text = "\n".join(
            (*STAGE_LINES[:2], "4、跳过知识产权结果。")
        )
        self.assertEqual(
            self.findings()["rd_stage_issues"],
            [
                {"rd_id": "RD01", "issue": "阶段性成果应为4条，实际为3条"},
                {"rd_id": "RD01", "issue": "阶段性成果第3条必须以3、开头"},
            ],
        )

    def test_rd_stage_limit_counts_all_four_items_together(self):
        """references/writing-rules.md §二「篇幅口径」规定阶段成果合计最多 400 字。"""
        prefix = "\n".join((*STAGE_LINES[:3], "4、"))
        fixed_length = len(prefix.replace("\n", ""))
        for length, expected in (
            (400, []),
            (401, [{"rd_id": "RD01", "issue": "阶段性成果合计401字，超过400字上限"}]),
        ):
            with self.subTest(length=length):
                self.rd[RD_STAGE].cells[1].text = prefix + "测" * (length - fixed_length)
                report = self.findings()
                self.assertEqual(report["rd_stage_results"]["RD01"]["body_length"], length)
                self.assertEqual(report["rd_stage_issues"], expected)
                self.assertEqual(report["limited_field_issues"], [])

    def test_ps_limits_are_independent_and_locate_each_overlong_field(self):
        """references/writing-rules.md §三规定 PS 三栏分别最多 400 字。"""
        expected = []
        for index, label in enumerate(PS_LIMITED_FIELDS, start=7):
            self.ps[label].cells[1].text = "测" * 400
            expected.append({"table": 5, "row": index, "field": label, "length": 400})
        report = self.findings()
        self.assertEqual([item for item in report["limited_fields"] if item["table"] == 5], expected)
        self.assertEqual(report["limited_field_issues"], [])
        for label in PS_LIMITED_FIELDS:
            self.ps[label].cells[1].text += "测"
        self.assertEqual(
            self.findings()["limited_field_issues"],
            [
                {**entry, "length": 401, "issue": "正文401字，超过400字上限"}
                for entry in expected
            ],
        )

    def test_evidence_flags_pending_ip_and_financing_claim_in_ip_section(self):
        """references/enterprise-innovation-capability-format.md §二 1、§四要求区分状态与融资证据。"""
        self.innovation[INNOVATION_SECTIONS[0]].cells[1].text = (
            "申请中的夹具专利已授权。提高融资估值。"
        )
        self.assertEqual(
            self.findings()["innovation_issues"],
            [
                {
                    "section": INNOVATION_SECTIONS[0],
                    "issue": "申请、受理或审中知识产权疑似被写成授权成果：申请中的夹具专利已授权",
                },
                {
                    "section": INNOVATION_SECTIONS[0],
                    "issue": "缺少融资作用证据但出现相关表述：['融资', '估值']",
                },
            ],
        )

    def test_innovation_evidence_checks_result_policy_and_personnel_locations(self):
        """references/enterprise-innovation-capability-format.md §三、§四规定原件名称和证据约束。"""
        self.innovation[INNOVATION_SECTIONS[1]].cells[1].text = "产品获得用户高度认可。"
        self.innovation[INNOVATION_SECTIONS[2]].cells[1].text = "执行《研发项目管理办法》。"
        self.innovation[INNOVATION_SECTIONS[3]].cells[1].text = "现有科技人员9名。"
        self.assertEqual(
            self.findings()["innovation_issues"],
            [
                {
                    "section": INNOVATION_SECTIONS[1],
                    "issue": "科技成果转化栏出现未登记的市场、合作或政策主张：用户高度认可",
                },
                {
                    "section": INNOVATION_SECTIONS[2],
                    "issue": "制度名称未逐字命中详细制度文件：['研发项目管理办法']",
                },
                {
                    "section": INNOVATION_SECTIONS[3],
                    "issue": "人员栏出现未登记的数量或比例：9名",
                },
            ],
        )

    def test_required_company_name_is_reported_at_registration(self):
        """references/application-fields-format.md 的 registration 字段确定企业名称的登记位置。"""
        self.registration["企业名称"].cells[1].text = ""
        self.assert_issue_at(self.findings(), "企业注册登记表", "企业名称", "缺失|必填|空白|未填写")

    def test_required_blank_rd_core_is_reported_at_its_rd(self):
        """SKILL.md §章节写法 3–4 规定每个 RD 的核心技术及创新点。"""
        self.rd[RD_CORE].cells[1].text = ""
        self.assert_issue_at(self.findings(), "RD01", "核心技术", "缺失|必填|空白|未填写")

    def test_invalid_year_is_reported_at_the_financial_summary(self):
        """references/application-fields-format.md 的 annual_financials 要求三个实际年度。"""
        self.summary.cell(3, 0).text = "20X5"
        self.assert_issue_at(self.findings(), "主要情况", "年度", "20X5", "格式|无效|非法|错误")

    def test_invalid_money_is_reported_at_ps_income(self):
        """references/application-fields-format.md 首段及 ps 字段规定销售收入使用数值万元。"""
        self.ps[PS_INCOME].cells[1].text = "12.3.4"
        self.assert_issue_at(
            self.findings(), "PS01", re.escape(PS_INCOME), r"12\.3\.4", "格式|无效|非法|错误",
        )

    def test_invalid_percentage_is_reported_at_the_personnel_section(self):
        """references/enterprise-innovation-capability-format.md §二 4、§五边界示例给出比例口径。"""
        self.innovation[INNOVATION_SECTIONS[3]].cells[1].text = "现有科技人员8名，占职工总数20.00%%。"
        self.assert_issue_at(
            self.findings(), INNOVATION_SECTIONS[3], r"20\.00%%", "格式|无效|非法|错误",
        )

    def test_conflicting_rd_expense_reports_both_sections_and_amounts(self):
        """references/material-checkup-report-template.md §4 要求年度结构明细与 RD 活动表勾稽。"""
        self.expense["研究开发费用（内、外部）小计"].cells[1].text = "19.00"
        self.assert_issue_at(
            self.findings(), "2025年度研发费用结构明细表", "RD01", "第三年",
            r"18\.00", r"19\.00", "不一致|冲突|差异|勾稽",
        )

    def test_empty_docx_is_rejected_with_an_explanation(self):
        """SKILL.md §任务与资料的输入是申请书 DOCX，按本轮空文档要求返回诊断。"""
        Document().save(self.input_path)
        process = self.run_audit()
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("Traceback", process.stderr)
        self.assertIn("文档无正文内容", process.stderr)

    def test_non_docx_is_rejected_without_traceback(self):
        """SKILL.md §任务与资料要求 DOCX，§资料读取与能力校准按实际容器判定。"""
        self.input_path.write_text("这是普通文本。", encoding="utf-8")
        process = self.run_audit()
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("Traceback", process.stderr)
        self.assertRegex(process.stderr, r"(?i)DOCX|Word|格式|not a zip file")

    def test_rd100_is_audited_separately_from_rd10(self):
        """SKILL.md §模板与回填接口要求连续编号，§检查与交付按编号检查各 RD。"""
        marker = next(p for p in self.document.paragraphs if p.text == "研发活动编号：RD01")
        marker.text = "研发活动编号：RD10"
        self.add_rd("RD100")
        report = self.findings()
        self.assertEqual(
            (list(report["rd_core_innovation"]), list(report["rd_stage_results"])),
            (["RD10", "RD100"], ["RD10", "RD100"]),
        )

    def test_ps100_is_reported_in_full_for_an_invalid_income(self):
        marker = next(p for p in self.document.paragraphs if p.text == "编号：PS01")
        marker.text = "编号 : ps100"
        self.ps[PS_INCOME].cells[1].text = "12.3.4"
        self.assert_issue_at(
            self.findings(), r"PS100\b", re.escape(PS_INCOME), r"12\.3\.4", "金额格式无效",
        )

    def test_inherited_template_font_counts_as_song_12pt(self):
        """SKILL.md §检查与交付要求母版正文呈现宋体 12 磅。"""
        style = self.document.styles["Normal"]
        style.font.name = "宋体"
        style.font.size = Pt(12)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        self.document.save(self.input_path)
        report = json.loads(self.run_audit(check=True).stdout)
        self.assertEqual((report["font_issue_count"], report["font_issue_sample"]), (0, []))


if __name__ == "__main__":
    unittest.main()

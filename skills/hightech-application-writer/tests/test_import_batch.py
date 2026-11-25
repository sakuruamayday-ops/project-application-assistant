import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from io import BytesIO, StringIO
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document
from lxml import etree


SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / 'scripts'
TEMPLATE = SKILL / 'assets' / '高新技术企业认定申请书空白模板.docx'
sys.path.insert(0, str(SCRIPTS))
import fill_application_fields as filler
import fill_rd_core_innovation as rd_filler


class ImportBatchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.spec = self.directory / 'spec.json'
        self.output = self.directory / '申请书.docx'

    def run_cli(self, script, *args):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def row(self, report, target):
        return next(row for row in report['batch_check']['rows'] if row['target_field'] == target)

    def with_saved_change(self, change, spec):
        original_write = ZipFile.writestr

        def altered_write(package, entry, data, *args, **kwargs):
            if getattr(entry, "filename", entry) == "word/document.xml":
                root = etree.fromstring(data)
                change(root)
                data = etree.tostring(root)
            return original_write(package, entry, data, *args, **kwargs)

        with patch.object(ZipFile, "writestr", altered_write):
            return filler.fill_application(TEMPLATE, spec, self.output, spec_path=self.spec)

    def change_registration_value(self, root, field, value):
        cell = filler.target(root.find("w:body/w:tbl", namespaces=filler.NS), field)
        cell.find(".//w:t", namespaces=filler.NS).text = value

    def read_back_registration_name(self, converted, actual):
        def change_registration_name(root):
            self.change_registration_value(root, "企业名称", actual)

        result = self.with_saved_change(change_registration_name, {'registration': {'企业名称': converted}})
        return self.row(result, '/registration/企业名称')

    def test_documented_region_alias_preserves_the_cover_runs_and_styles(self):
        result = filler.fill_application(TEMPLATE, {"cover": {"地区": "浙江省杭州市"}}, self.output)
        row = self.row(result, "/cover/企业所在地区")
        self.assertEqual((row["status"], row["source_location"], row["actual_value"]),
                         ("completed", "/cover/地区", "企业所在地区：浙江省杭州市"))
        with ZipFile(TEMPLATE) as before, ZipFile(self.output) as after:
            self.assertEqual(set(before.namelist()), set(after.namelist()))
            for member in set(before.namelist()) - {"word/document.xml"}:
                self.assertEqual(before.read(member), after.read(member), member)
            self.assertEqual([
                etree.tostring(node)
                for node in etree.fromstring(before.read("word/document.xml")).iter(filler.W + "rPr")
            ], [
                etree.tostring(node)
                for node in etree.fromstring(after.read("word/document.xml")).iter(filler.W + "rPr")
            ])

    def test_readback_ignores_leading_and_trailing_whitespace(self):
        actual = ' 甲企业\n'
        row = self.read_back_registration_name('甲企业', actual)
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['actual_value'], actual)

    def test_readback_normalizes_fullwidth_spaces_and_whitespace_runs(self):
        actual = '甲\u3000  \t企业'
        row = self.read_back_registration_name('甲 企业', actual)
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['actual_value'], actual)

    def test_readback_reports_internal_content_change_with_raw_values(self):
        expected, actual = ' 甲精密 企业 ', '甲数控\u3000企业\n'
        row = self.read_back_registration_name(expected, actual)
        self.assertEqual(row['status'], 'incomplete')
        self.assertEqual(row['check_reason'], '成品回读值与转换值不一致')
        self.assertEqual((row['original_value'], row['converted_value'], row['actual_value']),
                         (expected, expected, actual))

    def expand_template(self):
        expanded = self.directory / '扩表.docx'
        self.run_cli('expand_rd_ps_tables.py', TEMPLATE, expanded, '--rd-count', 1, '--ps-count', 1)
        return expanded

    def rd_spec(self):
        return {'schema_version': 1, 'batch_check': {'batch_id': 'B-RD', 'rows': []}, 'items': [
            {'rd_id': 'RD01', 'basic_fields': {'起止时间': '2025.5.1-2025.8.31'},
             'core_technologies': [{'name': '弹性夹持技术', 'description': '用夹爪定位', 'indicators': '偏差0.2毫米'}],
             'innovations': ['可更换限位块']},
        ]}

    def test_planner_and_filler_reuse_source_location_raw_value_and_same_batch_id(self):
        source = self.directory / '营业执照.txt'
        source.write_text('注册资金：1,200 万元', encoding='utf-8')
        manifest = self.directory / 'manifest.json'
        manifest.write_text(json.dumps({
            'schema_version': 1, 'documents': [{'path': source.name, 'role': 'essential'}],
            'source_fields': [{'source_file': source.name, 'source_location': '第 1 行',
                               'original_value': '1,200 万元', 'target_field': '/registration/注册资金', 'reason': '提取万元数值'}],
        }, ensure_ascii=False), encoding='utf-8')
        plan = self.run_cli('plan_hightech_inputs.py', manifest, '--state', self.directory / 'state.json',
                            '--report', self.directory / 'plan.json')
        self.assertEqual(plan['batch_check']['rows'][0]['status'], 'mapped')
        self.spec.write_text(json.dumps({'registration': {'注册资金': 1200}, 'batch_check': plan['batch_check']},
                                        ensure_ascii=False), encoding='utf-8')
        result = self.run_cli('fill_application_fields.py', TEMPLATE, self.spec, self.output)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['batch_check']['batch_id'], plan['batch_check']['batch_id'])
        row = self.row(result, '/registration/注册资金')
        self.assertEqual({key: row[key] for key in ('source_file', 'source_location', 'original_value', 'target_field', 'converted_value', 'reason')}, {
            'source_file': str(source.resolve()), 'source_location': '第 1 行', 'original_value': '1,200 万元',
            'target_field': '/registration/注册资金', 'converted_value': '1200', 'reason': '提取万元数值。按母版标签定位回填',
        })
        self.assertEqual(row['actual_value'], '1200')
        self.assertEqual(row['status'], 'completed')

    def test_one_written_field_mismatch_keeps_other_fields_and_intermediate_docx(self):
        def change_registration(root):
            self.change_registration_value(root, "注册资金", "990")

        result = self.with_saved_change(change_registration, {'registration': {'企业名称': '甲企业', '注册资金': 1200}})
        self.assertEqual(result['status'], 'partial')
        row = self.row(result, '/registration/注册资金')
        self.assertEqual((row['converted_value'], row['actual_value'], row['status']), ('1200', '990', 'incomplete'))
        self.assertEqual(row['check_reason'], '成品回读值与转换值不一致')
        self.assertEqual(self.row(result, '/registration/企业名称')['status'], 'completed')
        intermediate = Path(result['batch_check']['intermediate_artifact'])
        self.assertEqual(intermediate, self.output.resolve())
        self.assertIn('990', [cell.text for table in Document(intermediate).tables for row in table.rows for cell in row.cells])

    def test_unrecognized_input_location_and_original_value_remain_in_report(self):
        result = filler.fill_application(TEMPLATE, {'registration': {'既有业务简称': '甲', '注册资金': 1200}},
                                         self.output, spec_path=self.spec)
        self.assertEqual(result['status'], 'partial')
        row = self.row(result, '/registration/既有业务简称')
        self.assertEqual(row['status'], 'unrecognized')
        self.assertEqual(row['source_location'], '/registration/既有业务简称')
        self.assertEqual(row['original_value'], '甲')
        self.assertIsNone(row['converted_value'])
        self.assertEqual(self.row(result, '/registration/注册资金')['actual_value'], '1200')
        self.assertEqual(result['batch_check']['intermediate_artifact'], str(self.output.resolve()))

    def test_rd_project_count_and_financial_totals_are_read_from_actual_docx(self):
        expanded = self.expand_template()
        result = filler.fill_application(expanded, {
            'rd_financials': {'RD01': [84, 55, 0]},
            'annual_financials': [{'year': 2023, 'rd': 84, 'domestic_rd': 84},
                                  {'year': 2024, 'rd': 55, 'domestic_rd': 55},
                                  {'year': 2025, 'rd': 0, 'domestic_rd': 0}],
        }, self.output, spec_path=self.spec)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['batch_check']['counts']['RD'], {'expected': 1, 'actual': 1, 'status': 'completed'})
        self.assertEqual(result['rd_totals'], {'RD01': '139'})
        totals = self.row(result, '/rd_financials/RD01/研发经费近三年总支出（万元）')
        self.assertEqual((totals['kind'], totals['original_value'], totals['actual_value']), ('total', [84, 55, 0], '139'))
        self.assertEqual(self.row(result, '/expense/2024/RD01至RD01/研究开发费用（内、外部）小计/合计')['actual_value'], '55')

    def test_whole_form_preserves_existing_runs_breaks_rows_and_financial_year_slots(self):
        expanded = self.expand_template()
        result = filler.fill_application(expanded, {
            'registration': {'企业名称': '甲企业', '企业是否上市': '□是  ☑否'},
            'annual_financials': [{'year': 2023, 'rd': 84}, {'year': 2024, 'rd': 55}, {'year': 2025, 'rd': 0}],
            'rd_financials': {'RD01': [84, 55, 0]},
            'rd_external': {'RD01': [None, 5, 0]},
            'ps': [{'关键技术及主要技术指标（限400字）': '第一段\n第二段'}],
            'ip': [{'知识产权名称': '夹持装置', '授权号': 'ZL示例'}],
        }, self.output)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['batch_check']['counts']['IP'], {'expected': 1, 'actual': 1, 'status': 'completed'})
        self.assertEqual(self.row(result, '/expense/2024/RD01/内部研究开发费用')['actual_value'], '50')
        document = Document(self.output)
        self.assertEqual(len(document.tables), len(Document(expanded).tables))
        self.assertEqual(len(document.tables[3].rows), len(Document(expanded).tables[3].rows))
        expense = document.tables[6]
        self.assertEqual(expense.cell(11, 1).text, '84/55/0')
        self.assertEqual(expense.cell(9, 1).text, '—/5/0')
        self.assertEqual(expense.cell(1, 1).text, '—/50/0')
        self.assertEqual(document.tables[7].cell(4, 1).text.strip(), '第一段\n第二段')
        validator = next(path for directory in SKILL.parents
                         if (path := directory / '_runtime/template-fidelity/scripts/validate_docx_text_only.py').is_file())

        def compare(output, *flags):
            check = subprocess.run([sys.executable, str(validator), str(expanded), str(output), *flags],
                                   text=True, capture_output=True)
            return check.returncode, json.loads(check.stdout)

        self.assertEqual(compare(self.output)[0], 1)
        code, strict = compare(self.output, '--allow-empty-cell-text')
        self.assertEqual((code, strict['errors']), (0, []))
        self.assertGreater(strict['filled_empty_cell_slots'], 0)

        modified = self.directory / '加粗反例.docx'
        with ZipFile(self.output) as original, ZipFile(modified, 'w') as tampered:
            for entry in original.infolist():
                value = original.read(entry.filename)
                if entry.filename == 'word/document.xml':
                    root = etree.fromstring(value)
                    size = root.find('.//w:r/w:rPr/w:sz', filler.NS)
                    size.set(filler.W + 'val', '86')
                    value = etree.tostring(root)
                tampered.writestr(entry, value)
        self.assertEqual(compare(modified, '--allow-empty-cell-text')[0], 1)

    def test_preserves_published_year_labels_when_refilling_an_existing_form(self):
        expanded = self.expand_template()
        annual = [{'year': 2023, 'sales': 11}, {'year': 2024, 'sales': 13}, {'year': 2025, 'sales': 15}]
        filler.fill_application(expanded, {'annual_financials': annual}, self.output)
        updated = self.directory / '重填.docx'
        result = filler.fill_application(self.output, {'annual_financials': [{'year': 2023, 'profit': 3}]}, updated)
        self.assertEqual(result['status'], 'passed')
        before = Document(self.output).tables[1]
        after = Document(updated).tables[1]
        for row in (4, 5, 6):
            self.assertEqual([cell.text for cell in before.rows[row].cells][:-1],
                             [cell.text for cell in after.rows[row].cells][:-1])

    def test_expense_conflict_preserves_both_values_and_requires_correction(self):
        expanded = self.expand_template()
        result = filler.fill_application(expanded, {
            'rd_financials': {'RD01': [84, 55, 0]},
            'annual_financials': [{'year': 2023, 'rd': 999, 'domestic_rd': 84},
                                  {'year': 2024, 'rd': 55, 'domestic_rd': 55},
                                  {'year': 2025, 'rd': 0, 'domestic_rd': 0}],
        }, self.output, spec_path=self.spec)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['batch_check']['status'], 'completed')
        finance = result['financial_reconciliation']
        self.assertEqual(finance['status'], 'conflict')
        self.assertEqual(set(finance['items'][0]), {'item', 'gap', 'action', 'priority'})
        self.assertIn('差额 -915 万元', finance['items'][0]['gap'])
        self.assertEqual(self.row(result, '/expense/2023/RD01至RD01/研究开发费用（内、外部）小计/合计')['actual_value'], '84')
        self.assertTrue(self.output.is_file())

    def test_missing_project_table_on_disk_fails_count_even_without_ps_field_writes(self):
        def remove_product_table(root):
            table, = [table for table in root.xpath('./w:body/w:tbl', namespaces=filler.NS)
                      if filler.PS_FIELDS[0] in filler.named_cells(table)]
            table.getparent().remove(table)

        result = self.with_saved_change(remove_product_table, {'registration': {'注册资金': 1200}})
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['batch_check']['counts']['PS'], {'expected': 1, 'actual': 0, 'status': 'incomplete'})
        self.assertEqual(self.row(result, '/registration/注册资金')['status'], 'completed')

    def test_rd_only_filler_retains_shared_batch_and_unmapped_rd(self):
        spec = self.rd_spec()
        spec['items'].append({'rd_id': 'RD02', 'basic_fields': {'研发活动名称': '额外项目'}})
        self.spec.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
        report = self.run_cli('fill_rd_core_innovation.py', self.expand_template(), self.spec, self.output)
        self.assertEqual(report['status'], 'draft')
        self.assertEqual(report['batch_check']['batch_id'], 'B-RD')
        self.assertEqual(report['batch_check']['counts']['RD']['actual'], 1)
        row = self.row(report, '/items/0/basic_fields/起止时间')
        self.assertEqual((row['original_value'], row['converted_value'], row['actual_value'], row['status']),
                         ('2025.5.1-2025.8.31', '2025.05.01-2025.08.31', '2025.05.01-2025.08.31', 'completed'))
        self.assertEqual(self.row(report, '/items/1')['original_value']['rd_id'], 'RD02')
        self.assertEqual(self.row(report, '/items/1')['status'], 'unrecognized')

    def test_rd_readback_failure_keeps_failed_artifact_and_restores_previous_file(self):
        expanded = self.expand_template()
        self.spec.write_text(json.dumps(self.rd_spec(), ensure_ascii=False), encoding='utf-8')
        original = b'previous output'
        self.output.write_bytes(original)
        audit = self.directory / 'rd-audit.json'
        args = Namespace(input=expanded, output=self.output, spec=self.spec, report=audit, overwrite=True, max_body_chars=400)
        path_replace = Path.replace

        def replace_with_changed_cell(source, target):
            output = path_replace(source, target)
            payload = BytesIO()
            with ZipFile(output) as old, ZipFile(payload, 'w') as modified:
                for entry in old.infolist():
                    content = old.read(entry.filename)
                    if entry.filename == 'word/document.xml':
                        content = content.replace(b'2025.05.01-2025.08.31', b'2025.05.02-2025.08.31')
                    modified.writestr(entry, content)
            output.write_bytes(payload.getvalue())
            return output

        with patch.object(rd_filler, 'parse_args', return_value=args), patch.object(Path, 'replace', replace_with_changed_cell), redirect_stdout(StringIO()):
            with self.assertRaisesRegex(SystemExit, '起止时间写入后置校验失败'):
                rd_filler.main()
        self.assertEqual(self.output.read_bytes(), original)
        result = json.loads(audit.read_text(encoding='utf-8'))
        self.assertIs(result['postcondition_verified'], False)
        row = self.row(result, '/items/0/basic_fields/起止时间')
        self.assertEqual((row['actual_value'], row['status']), ('2025.05.02-2025.08.31', 'incomplete'))
        failed_artifact = Path(result['batch_check']['intermediate_artifact'])
        with ZipFile(failed_artifact) as failed:
            self.assertIn(b'2025.05.02-2025.08.31', failed.read('word/document.xml'))


if __name__ == '__main__':
    unittest.main()

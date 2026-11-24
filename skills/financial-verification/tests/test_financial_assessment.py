import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_financial_assessment.py'


class FinancialAssessmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / '财务核验.json'
        self.data = {
            'identity': {'company_name': '甲企业有限公司'},
            'scope': {'period': '2025', 'currency': 'CNY', 'unit': '万元', 'consolidation_scope': 'standalone'},
            'sources': [{'id': 'BS', 'path': '资产负债表.xlsx', 'sheet': '资产负债表', 'cell': 'D8'}],
            'facts': [], 'metrics': [], 'conflicts': [], 'quality': {'status': 'computed'},
        }

    def validate(self, exit_code=0):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
        run = subprocess.run([sys.executable, str(SCRIPT), str(self.path)], capture_output=True, text=True)
        self.assertEqual(run.returncode, exit_code, run.stderr or run.stdout)
        return json.loads(run.stdout)

    def metric(self, name, formula_id, inputs, result, unit='万元'):
        return {'metric': name, 'formula_id': formula_id, 'formula': name, 'inputs': inputs,
                'result': result, 'status': 'computed', 'unit': unit, 'source_ids': ['BS']}

    def test_issue_contains_five_values_and_retains_batch_context(self):
        self.data['facts'] = [{'id': 'asset', 'value': 320, 'status': 'invalid', 'source_ids': ['BS']}]
        report = self.validate(2)
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['issues'], [{
            'field_location': 'facts[0].status', 'current_value': 'invalid',
            'expected_requirement': {'rule': '质量状态取 computed、conflicting、missing、not-applicable、verified',
                                     'reference': 'references/financial-facts-contract.md#结构化核验回执'},
            'fix': '按原报表及实际核验结果填写 status', 'source_location': '资产负债表.xlsx 资产负债表 D8',
        }])
        self.assertEqual(report['identity'], {'company_name': '甲企业有限公司'})
        self.assertEqual(report['scope']['period'], '2025')
        self.assertEqual(report['scope']['unit'], '万元')
        self.assertEqual(report['sources'], self.data['sources'])
        self.assertEqual(report['quality'], {'status': 'computed'})

    def test_explicit_missing_source_position_when_only_file_is_known(self):
        self.data['sources'] = [{'id': 'BS', 'path': '资产负债表.xlsx'}]
        self.data['facts'] = [{'value': 320, 'status': '未知', 'source_ids': ['BS']}]
        issue = self.validate(2)['issues'][0]
        self.assertEqual(issue['field_location'], 'facts[0].status')
        self.assertEqual(issue['current_value'], '未知')
        self.assertEqual(issue['source_location'], '缺来源位置')

    def test_all_issues_in_same_batch_include_each_affected_field(self):
        self.data['facts'] = [{'value': 320, 'status': 'verified', 'source_location': '总账 B7'}]
        self.data['metrics'] = [{'metric': '研发费用', 'status': 'computed', 'source_ids': ['BS'],
                                 'inputs': {'费用': 150}, 'unit': '万元'}]
        problems = {issue['field_location']: issue for issue in self.validate(2)['issues']}
        self.assertEqual(set(problems), {'facts[0].source_ids', 'metrics[0].formula', 'metrics[0].result'})
        self.assertEqual(problems['facts[0].source_ids']['source_location'], '总账 B7')
        self.assertEqual(problems['metrics[0].formula']['fix'], '按该指标原始计算口径填入 formula')
        self.assertIsNone(problems['metrics[0].result']['current_value'])

    def test_repaired_fact_recalculates_ratio_net_assets_and_dependent_total(self):
        self.data['facts'] = [{'id': key, 'value': value, 'status': 'verified', 'source_ids': ['BS']}
                              for key, value in [('assets', 320), ('debt', 80), ('adjustment', 10)]]
        inputs = [{'fact_id': 'assets'}, {'fact_id': 'debt'}]
        self.data['metrics'] = [self.metric('调整后权益', 'sum', [{'metric': '净资产'}, {'fact_id': 'adjustment'}], 250),
                                self.metric('净资产', 'net_assets', inputs, 240),
                                self.metric('资产负债率', 'debt_ratio', list(reversed(inputs)), 25, '%')]
        self.assertEqual(self.validate()['recomputed_metrics'][0]['result'], '250')
        self.data['facts'][1]['value'] = 40
        report = self.validate(2)
        self.assertEqual({row['metric']: row['result'] for row in report['recomputed_metrics']},
                         {'调整后权益': '290', '净资产': '280', '资产负债率': '12.500'})
        issues = {row['field_location']: row for row in report['issues']}
        self.assertEqual(issues['metrics[0].result']['current_value'], 250)
        self.assertEqual(issues['metrics[1].result']['expected_requirement'], {
            'rule': '资产总额－负债总额 = 280', 'reference': 'references/reconciliation-and-formulas.md#常用公式',
        })
        self.assertEqual(issues['metrics[2].result']['fix'], '根据已核输入将 result 改为 12.500')
        for row, new in zip(self.data['metrics'], (290, 280, 12.5)):
            row['result'] = new
        self.assertEqual(self.validate()['issues'], [])

    def test_zero_denominator_keeps_independent_valid_calculation(self):
        self.data['facts'] = [{'id': key, 'value': val, 'status': 'verified', 'source_ids': ['BS']}
                              for key, val in [('current', 140), ('prior', 0)]]
        self.data['metrics'] = [self.metric('增长率', 'revenue_growth', [{'fact_id': 'current'}, {'fact_id': 'prior'}], 0, '%'),
                                self.metric('当期合计', 'sum', [{'fact_id': 'current'}], 140)]
        report = self.validate(2)
        self.assertEqual(report['issues'][0]['field_location'], 'metrics[0].inputs')
        self.assertEqual(report['issues'][0]['fix'], '分母为零，按原报表补正分母或记录为不可计算')
        self.assertEqual([(row['metric'], row['result']) for row in report['recomputed_metrics']], [('当期合计', '140')])

    def test_bounded_ratios_checked_before_rounding(self):
        for name, formula in [('主营占比', 'main_revenue_ratio'), ('研发费率', 'rd_ratio'),
                              ('高新收入占比', 'high_tech_income_ratio')]:
            for value in (-0.01, 100.01):
                with self.subTest(name=name, value=value):
                    self.data['facts'] = [{'id': key, 'value': amount, 'status': 'verified', 'source_ids': ['BS']}
                                          for key, amount in [('part', value), ('total', 100)]]
                    metric = self.metric(name, formula, [{'fact_id': 'part'}, {'fact_id': 'total'}], round(value), '%')
                    self.data['metrics'] = [{**metric, 'round_to': 0}]
                    report = self.validate(2)
                    self.assertIn('超出 0% 到 100%', report['errors'][0])
                    self.assertEqual(report['recomputed_metrics'], [])

    def test_blank_source_subject_cannot_borrow_task_identity(self):
        self.data['sources'][0]['company_name'] = '   '
        report = self.validate(2)
        self.assertIn('缺主体信息', report['errors'])
        self.assertEqual(report['issues'][0]['source_location'], '资产负债表.xlsx 资产负债表 D8')

    def test_conflicting_sources_report_both_subjects(self):
        self.data['sources'][0]['company_name'] = '甲企业有限公司'
        self.data['sources'].append({'id': 'PL', 'path': '利润表.xlsx', 'company_name': '乙企业有限公司'})
        report = self.validate(2)
        self.assertIn('甲企业有限公司', report['errors'][0])
        self.assertIn('乙企业有限公司', report['errors'][0])
        self.assertEqual(report['recomputed_metrics'], [])

    def test_existing_metric_without_formula_id_keeps_legacy_validation(self):
        self.data['metrics'] = [{'metric': '研发支出', 'formula': '汇总报表', 'inputs': {'2025': 180},
                                 'unit': '万元', 'result': 180, 'status': 'verified', 'source_ids': ['BS']}]
        report = self.validate()
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['recomputed_metrics'], [])

    def three_statement_output(self):
        def period(year, assets, liabilities, revenue, research, debt_ratio, rd_ratio):
            facts = {
                'assets': assets, 'liabilities': liabilities, 'equity': assets - liabilities,
                'revenue': revenue, 'cost': revenue // 2, 'research_expense': research,
                'operating_cash_flow': 20, 'taxes_paid': 8,
            }
            evidence = {field: f'三表.pdf 第{page}页 {year}年列 {field}' for field, page in (
                ('assets', 1), ('liabilities', 1), ('equity', 1), ('revenue', 2),
                ('cost', 2), ('research_expense', 2), ('operating_cash_flow', 3), ('taxes_paid', 3),
            )}
            evidence['assets'] = {'path': '三表.pdf', 'page': 1, 'location': f'资产负债表 {year}年列 资产总计'}
            return {'facts': facts, 'evidence': evidence,
                    'metrics': {'debt_ratio': debt_ratio, 'research_to_revenue': rd_ratio, 'gross_margin': 0.5},
                    'quality': {'status': 'unverified', 'missing_fields': [], 'notes': []}}

        return {
            'schema': 'enterprise-financial-facts/v1', 'producer': 'manufacturing-tax-risk-analysis',
            'company': {'name': '甲制造有限公司', 'unified_social_credit_code': ''},
            'basis': {'currency': 'CNY', 'unit': 'yuan', 'consolidation_scope': 'standalone'},
            'periods': {
                '2025': period('2025', 400, 80, 250, 20, 0.2, 0.08),
                '2024': period('2024', 320, 80, 200, 10, 0.25, 0.05),
            },
            'source_artifacts': [{'id': 'AUDIT', 'name': '三表.pdf', 'location': '总表第1–3页'}],
        }

    def test_direct_three_statement_output_keeps_period_source_and_quality(self):
        self.data = self.three_statement_output()
        report = self.validate()
        self.assertEqual(report['issues'], [])
        self.assertEqual(report['identity']['company_name'], '甲制造有限公司')
        self.assertEqual(report['scope']['period'], '2024–2025')
        self.assertEqual(report['scope']['unit'], 'yuan')
        self.assertEqual(report['quality']['2025']['status'], 'unverified')
        sources = {record['id']: record for record in report['sources']}
        self.assertEqual(sources['AUDIT'], self.data['source_artifacts'][0])
        self.assertEqual(sources['2024/assets']['location'], '资产负债表 2024年列 资产总计')
        self.assertEqual({row['metric']: row['result'] for row in report['recomputed_metrics']}, {
            '2024/debt_ratio': '0.25', '2024/research_to_revenue': '0.05',
            '2025/debt_ratio': '0.2', '2025/research_to_revenue': '0.08',
        })

    def test_real_producer_handoff_preserves_full_decimal_precision(self):
        producer = SCRIPT.parents[2] / 'manufacturing-tax-risk-analysis'
        fixture = json.loads((producer / 'references/metrics-input.example.json').read_text())
        fixture['source_artifacts'] = [{'id': 'FS', 'location': '三表原件 页1至3'}]
        fixture['evidence'] = {
            year: {key: f'模拟三表 {year}年度 {key}' for key, value in annual.items() if value is not None}
            for year, annual in fixture['years'].items()
        }
        source = self.path.with_name('source.json')
        source.write_text(json.dumps(fixture), encoding='utf-8')
        run = subprocess.run([sys.executable, str(producer / 'scripts/calculate_metrics.py'),
                              str(source), str(self.path)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)

        def check_file(code):
            checked = subprocess.run([sys.executable, str(SCRIPT), str(self.path)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, code, checked.stderr or checked.stdout)
            return json.loads(checked.stdout)

        report = check_file(0)
        self.assertEqual(len(report['recomputed_metrics']), 6)
        self.assertEqual(report['items'], [])
        text = self.path.read_text(encoding='utf-8')
        import re
        text, changed = re.subn(r'("research_to_revenue": )[^,]+', r'\g<1>0.12345', text, count=1)
        self.assertEqual(changed, 1)
        self.path.write_text(text, encoding='utf-8')
        wrong = check_file(2)
        self.assertEqual(len(wrong['items']), 1)
        self.assertIn('research_expense', wrong['items'][0]['evidence'])
        self.assertTrue({'item', 'gap', 'action', 'priority'} <= wrong['items'][0].keys())

    def test_direct_output_detects_a_stale_ratio_with_its_statement_location(self):
        self.data = self.three_statement_output()
        self.data['periods']['2025']['facts']['liabilities'] = 40
        report = self.validate(2)
        self.assertEqual([row['field_location'] for row in report['issues']], ['metrics[2].result'])
        self.assertIn('三表.pdf 第1页 2025年列 liabilities', report['issues'][0]['source_location'])
        results = {row['metric']: row['result'] for row in report['recomputed_metrics']}
        self.assertEqual(results['2025/debt_ratio'], '0.1')
        self.assertEqual(results['2024/debt_ratio'], '0.25')

    def test_direct_output_reports_missing_evidence_and_keeps_other_ratios(self):
        self.data = self.three_statement_output()
        del self.data['periods']['2025']['evidence']['research_expense']
        report = self.validate(2)
        self.assertEqual(len(report['issues']), 2)
        self.assertIn('2025/research_expense', report['issues'][0]['fix'])
        self.assertEqual(report['issues'][1]['field_location'], 'metrics[3].inputs')
        self.assertEqual(len(report['recomputed_metrics']), 3)

    def test_direct_single_period_output_preserves_null_as_missing(self):
        self.data = self.three_statement_output()
        del self.data['periods']['2024']
        period = self.data['periods']['2025']
        period['facts']['research_expense'] = period['metrics']['research_to_revenue'] = None
        period['quality']['missing_fields'] = ['research_expense']
        del period['evidence']['research_expense']
        report = self.validate()
        self.assertEqual(report['scope']['period'], '2025')
        self.assertEqual(report['quality']['2025']['missing_fields'], ['research_expense'])
        self.assertEqual([row['metric'] for row in report['recomputed_metrics']], ['2025/debt_ratio'])


if __name__ == '__main__':
    unittest.main()

import importlib.util
import json
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "calculate_metrics.py"
SPEC = importlib.util.spec_from_file_location("calculate_metrics", SCRIPT)
calculate_metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calculate_metrics)


def statement_facts(**overrides):
    """按 references/data-schema.md 的输入结构准备以元计的三表数据。"""
    facts = {
        "revenue": 960_000,
        "cost": 624_000,
        "profit_before_tax": 120_000,
        "net_profit": 96_000,
        "assets": 840_000,
        "assets_open": 760_000,
        "liabilities": 390_000,
        "equity": 450_000,
        "equity_open": 350_000,
        "current_assets": 480_000,
        "current_liabilities": 240_000,
        "cash": 92_000,
        "receivables": 180_000,
        "receivables_open": 140_000,
        "other_receivables": 31_500,
        "inventory": 132_000,
        "inventory_open": 108_000,
        "advances_from_customers": 48_000,
        "short_term_loans": 120_000,
        "operating_cash_flow": 150_000,
        "capex_cash": 63_000,
        "taxes_paid": 28_800,
        "sales_cash": 896_000,
        "research_expense": 45_600,
        "interest_expense": 15_000,
        "income_tax_expense": 24_000,
    }
    facts.update(overrides)
    return facts


def two_year_input():
    return {
        "company": {"name": "测试制造企业", "unified_social_credit_code": ""},
        "basis": {"currency": "CNY", "unit": "yuan", "consolidation_scope": "standalone"},
        "years": {
            "2024": statement_facts(
                revenue=800_000,
                cost=560_000,
                profit_before_tax=100_000,
                net_profit=80_000,
                assets=760_000,
                assets_open=720_000,
                liabilities=410_000,
                equity=350_000,
                equity_open=320_000,
                receivables=140_000,
                receivables_open=115_000,
                inventory=108_000,
                inventory_open=90_000,
                income_tax_expense=20_000,
            ),
            "2025": statement_facts(),
        },
    }


class CalculateMetricsTests(unittest.TestCase):
    def assert_metrics(self, facts, expected):
        metrics = calculate_metrics.calc(facts)
        for name, value in expected.items():
            with self.subTest(metric=name):
                self.assertAlmostEqual(metrics[name], value, places=8)

    def run_calculation(self, source, directory):
        input_path = Path(directory) / "input.json"
        facts_path = Path(directory) / "artifacts" / "facts.json"
        metrics_path = facts_path.with_name("metrics.json")
        input_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(input_path), str(facts_path),
             "--metrics-output", str(metrics_path)],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
        return result, facts_path, metrics_path

    def calculate_files(self, source):
        """SKILL.md「资料与复算」的命令同时生成共享事实和指标文件。"""
        with TemporaryDirectory() as directory:
            result, facts_path, metrics_path = self.run_calculation(source, directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            return (
                json.loads(facts_path.read_text(encoding="utf-8")),
                json.loads(metrics_path.read_text(encoding="utf-8")),
                json.loads(result.stdout),
            )

    def assert_calculation_failure_leaves_no_output(self, source, message):
        with TemporaryDirectory() as directory:
            result, facts_path, _ = self.run_calculation(source, directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertEqual(list(facts_path.parent.glob("*")), [])

    def assert_growth_unavailable(self, source, reason):
        _, summary, _ = self.calculate_files(source)
        rows = {row["indicator"]: row["result"] for row in summary["report_rows"]}
        expected = []
        for name, label in (("revenue_growth", "营业收入同比增长率"),
                            ("receivables_growth", "应收账款同比增长率")):
            self.assertIsNone(summary["indicators"][name]["values"]["2025"])
            self.assertEqual(rows[f"2025年{label}"], reason)
            expected.append({"indicator": label, "year": "2025", "reason": reason})
        self.assertEqual(summary["uncomputable_indicators"], expected)

    def test_profitability_uses_net_profit_and_opening_and_closing_balances(self):
        """references/data-schema.md「公式」的毛利率、净利率、ROE 和 ROA。"""
        self.assert_metrics(statement_facts(), {
            "gross_margin": 0.35,  # (960000 - 624000) / 960000
            "net_margin": 0.10,  # 96000 / 960000
            "roe": 0.24,  # 96000 / ((450000 + 350000) / 2)
            "roa": 0.12,  # 96000 / ((840000 + 760000) / 2)
        })

    def test_solvency_uses_the_matching_assets_liabilities_and_interest(self):
        """references/data-schema.md「公式」的偿债指标。营运资金取流动资产减流动负债。"""
        self.assert_metrics(statement_facts(), {
            "debt_ratio": 0.464285714286,  # 390000 / 840000
            "current_ratio": 2.00,  # 480000 / 240000
            "quick_ratio": 1.45,  # (480000 - 132000) / 240000
            "cash_ratio": 0.383333333333,  # 92000 / 240000
            "interest_coverage": 9.00,  # (120000 + 15000) / 15000
            "working_capital": 240_000.00,  # 480000 - 240000
        })

    def test_turnover_uses_average_balances_and_365_days(self):
        """references/data-schema.md「公式」以收入计算应收周转，以成本计算存货周转。"""
        self.assert_metrics(statement_facts(), {
            "ar_days": 60.833333333333,  # ((140000 + 180000) / 2) / 960000 * 365
            "inventory_days": 70.192307692308,  # ((108000 + 132000) / 2) / 624000 * 365
            "receivables_to_revenue": 0.1875,  # 180000 / 960000
            "other_ar_to_assets": 0.0375,  # 31500 / 840000
            "other_ar_to_revenue": 0.0328125,  # 31500 / 960000
            "advance_to_revenue": 0.05,  # 48000 / 960000
        })

    def test_cash_flow_and_research_use_the_correct_statement_items(self):
        """references/data-schema.md「公式」及 financial-paragraph-templates.md 的净利润口径。"""
        self.assert_metrics(statement_facts(), {
            "research_to_revenue": 0.0475,  # 45600 / 960000
            "cash_tax_payment_rate": 0.03,  # 28800 / 960000
            "sales_cash_to_revenue": 0.933333333333,  # 896000 / 960000
            "ocf_to_profit": 1.5625,  # 150000 / 96000
            "free_cash_flow": 87_000.00,  # 150000 - 63000
        })

    def test_all_statement_metrics_are_displayed_to_two_decimal_places(self):
        """SKILL.md「资料与复算」及 references/financial-paragraph-templates.md「单位由程序输出」。"""
        _, summary, _ = self.calculate_files(two_year_input())
        # 将前四例的各项手算值按原单位四舍五入。金额从元换为万元。
        self.assertEqual(summary["display_values"]["2025"]["metrics"], {
            "gross_margin": "35.00%",
            "net_margin": "10.00%",
            "debt_ratio": "46.43%",
            "current_ratio": "2.00",
            "quick_ratio": "1.45",
            "cash_ratio": "0.38",
            "roe": "24.00%",
            "roa": "12.00%",
            "ar_days": "60.83天",
            "receivables_to_revenue": "18.75%",
            "inventory_days": "70.19天",
            "other_ar_to_assets": "3.75%",
            "other_ar_to_revenue": "3.28%",
            "advance_to_revenue": "5.00%",
            "research_to_revenue": "4.75%",
            "cash_tax_payment_rate": "3.00%",
            "sales_cash_to_revenue": "93.33%",
            "ocf_to_profit": "156.25%",
            "free_cash_flow": "8.70万元",
            "interest_coverage": "9.00",
            "working_capital": "24.00万元",
        })

    def test_year_over_year_growth_compares_same_item_in_previous_year(self):
        """references/report-input-schema.md「确定性指标文件」要求按上一自然年复算增速。"""
        _, summary, _ = self.calculate_files(two_year_input())
        indicators = summary["indicators"]
        # (960000 - 800000) / 800000 = 20.00%，(180000 - 140000) / 140000 = 28.57%。
        self.assertEqual(indicators["revenue_growth"]["values"], {"2025": 0.20})
        self.assertAlmostEqual(indicators["receivables_growth"]["values"]["2025"], 0.285714285714)
        rows = {row["indicator"]: row["result"] for row in summary["report_rows"]}
        self.assertEqual(rows["2025年营业收入同比增长率"], "20.00%")
        self.assertEqual(rows["2025年应收账款同比增长率"], "28.57%")
        self.assertEqual(rows["2025年研发费用率"], "4.75%")  # 45600 / 960000

    def test_growth_marks_the_missing_calendar_year(self):
        """references/report-input-schema.md「确定性指标文件」要求同比缺期时注明缺失年度。"""
        source = two_year_input()
        source["years"]["2023"] = source["years"].pop("2024")
        _, summary, _ = self.calculate_files(source)
        expected_reason = "缺少2024年度数据，无法计算同比增长率"
        indicators = summary["indicators"]
        self.assertIsNone(indicators["revenue_growth"]["values"]["2025"])
        self.assertIsNone(indicators["receivables_growth"]["values"]["2025"])
        self.assertEqual(summary["uncomputable_indicators"], [
            {"indicator": "营业收入同比增长率", "year": "2025", "reason": expected_reason},
            {"indicator": "应收账款同比增长率", "year": "2025", "reason": expected_reason},
        ])

    def test_balanced_statements_have_zero_gaps(self):
        """SKILL.md「资料与复算」要求复算主表合计。正常资产应等于负债加权益。"""
        _, summary, _ = self.calculate_files(two_year_input())
        # 760000 - 410000 - 350000 = 0，840000 - 390000 - 450000 = 0。
        self.assertEqual(summary["indicators"]["balance_equation_gap"]["values"], {"2024": 0, "2025": 0})
        self.assertNotIn("2025年资产负债表恒等式差额", [row["indicator"] for row in summary["report_rows"]])

    def test_unbalanced_statement_reports_the_amount_of_the_gap(self):
        """references/report-input-schema.md「确定性指标文件」用复算行传递主表差额。"""
        source = two_year_input()
        source["years"]["2025"]["equity"] = 437_000
        _, summary, _ = self.calculate_files(source)
        # 840000 - 390000 - 437000 = 13000 元，即 1.30 万元。
        self.assertEqual(summary["indicators"]["balance_equation_gap"]["values"]["2025"], 13_000)
        rows = {row["indicator"]: row for row in summary["report_rows"]}
        self.assertEqual(rows["2025年资产负债表恒等式差额"], {
            "indicator": "2025年资产负债表恒等式差额",
            "formula": "资产总额－负债总额－权益",
            "result": "13,000.00元（1.30万元）",
            "source": "2025年资产、负债与所有者权益复算",
        })

    def test_zero_denominators_leave_ratios_uncomputable(self):
        """references/data-schema.md「公式」中的分母为零时，各商无定义。"""
        metrics = calculate_metrics.calc(statement_facts(
            revenue=0, cost=0, assets=0, assets_open=0, equity=0, equity_open=0,
            current_liabilities=0, net_profit=0, interest_expense=0,
        ))
        for name in (
            "gross_margin", "net_margin", "debt_ratio", "current_ratio", "quick_ratio",
            "cash_ratio", "roe", "roa", "ar_days", "receivables_to_revenue", "inventory_days",
            "other_ar_to_assets", "other_ar_to_revenue", "advance_to_revenue", "research_to_revenue",
            "cash_tax_payment_rate", "sales_cash_to_revenue", "ocf_to_profit", "interest_coverage",
        ):
            with self.subTest(metric=name):
                self.assertIsNone(metrics[name])

    def test_zero_opening_balance_and_zero_numerators_are_valid_facts(self):
        """references/data-schema.md「输入 JSON」以 null 表示缺项。零余额参与公式计算。"""
        self.assert_metrics(statement_facts(inventory_open=0, cash=0, taxes_paid=0), {
            "inventory_days": 38.605769230769,  # ((0 + 132000) / 2) / 624000 * 365
            "cash_ratio": 0.00,  # 0 / 240000
            "cash_tax_payment_rate": 0.00,  # 0 / 960000
        })

    def test_losses_and_cash_deficits_keep_their_sign(self):
        """references/data-schema.md「公式」使用有符号的利润与现金流原值。"""
        self.assert_metrics(statement_facts(
            net_profit=-96_000, profit_before_tax=-120_000,
            operating_cash_flow=48_000, current_assets=180_000,
        ), {
            "net_margin": -0.10,  # -96000 / 960000
            "roe": -0.24,  # -96000 / 400000
            "ocf_to_profit": -0.50,  # 48000 / -96000
            "interest_coverage": -7.00,  # (-120000 + 15000) / 15000
            "free_cash_flow": -15_000.00,  # 48000 - 63000
            "working_capital": -60_000.00,  # 180000 - 240000
        })

    def test_missing_statement_keys_are_rejected(self):
        """references/data-schema.md「输入 JSON」规定三表字段保留键，缺值填 null。"""
        for field in ("assets", "net_profit", "operating_cash_flow"):
            with self.subTest(field=field):
                facts = statement_facts()
                del facts[field]
                with self.assertRaisesRegex(ValueError, f"^missing fields: {field}$"):
                    calculate_metrics.calc(facts)

    def test_null_facts_are_disclosed_and_leave_unrelated_metrics_available(self):
        """references/data-schema.md「输入 JSON」保留原值和缺项。财务段落模板规定缺项展示。"""
        source = two_year_input()
        source["years"]["2025"].update(inventory_open=None, income_tax_expense=None)
        facts, summary, _ = self.calculate_files(source)
        period = facts["periods"]["2025"]
        display = summary["display_values"]["2025"]
        self.assertEqual(period["quality"]["missing_fields"], ["income_tax_expense", "inventory_open"])
        self.assertEqual(period["quality"]["status"], "unverified")
        self.assertIsNone(period["facts"]["income_tax_expense"])
        self.assertIsNone(period["metrics"]["inventory_days"])
        self.assertEqual(display["facts"]["income_tax_expense"], "待补充")
        self.assertEqual(display["metrics"]["inventory_days"], "无法计算")
        self.assertEqual(display["metrics"]["gross_margin"], "35.00%")  # (960000 - 624000) / 960000
        self.assertEqual(summary["uncomputable_indicators"], [
            {"indicator": "存货周转天数", "year": "2025", "reason": "缺少期初存货，无法计算"},
        ])

    def test_numeric_amount_strings_match_numeric_inputs(self):
        expected = calculate_metrics.calc(statement_facts(inventory_open=0))
        for field, value in (("revenue", "960000"), ("inventory_open", "0"), ("operating_cash_flow", "150000")):
            with self.subTest(field=field):
                facts = statement_facts(inventory_open=0)
                facts[field] = value
                self.assertEqual(calculate_metrics.calc(facts), expected)

    def test_large_amounts_preserve_ratios_and_cash_flow_difference(self):
        """references/data-schema.md「公式」同倍扩大三表金额后，比例不变、金额同比例扩大。"""
        large_facts = {field: value * 10**12 for field, value in statement_facts().items()}
        self.assert_metrics(large_facts, {
            "gross_margin": 0.35,  # (960000 - 624000) / 960000，同倍数约去
            "debt_ratio": 0.464285714286,  # 390000 / 840000，同倍数约去
            "ar_days": 60.833333333333,  # 160000 / 960000 * 365，同倍数约去
        })
        self.assertEqual(
            calculate_metrics.calc(large_facts)["free_cash_flow"],
            87_000_000_000_000_000,  # (150000 - 63000) * 10**12
        )

    def test_prior_year_zero_denominator_leaves_growth_uncomputable(self):
        """references/report-input-schema.md「确定性指标文件」使用上年基数。零基数无同比值。"""
        source = two_year_input()
        source["years"]["2024"].update(revenue=0, receivables=0)
        _, summary, _ = self.calculate_files(source)
        for name in ("revenue_growth", "receivables_growth"):
            with self.subTest(indicator=name):
                self.assertIsNone(summary["indicators"][name]["values"]["2025"])

    def test_cli_preserves_source_evidence_and_binds_display_values(self):
        """SKILL.md「资料与复算」及 references/data-schema.md 要求保留口径、报表原值与证据。"""
        source = two_year_input()
        source["source_artifacts"] = ["2025年测试三表"]
        source["evidence"] = {"2025": {"revenue": {"source": "2025年利润表", "page": 2}}}
        source["quality"] = {"2025": {"status": "verified", "notes": ["原报表复核"]}}
        facts, summary, receipt = self.calculate_files(source)
        period = facts["periods"]["2025"]
        self.assertEqual(facts["schema"], "enterprise-financial-facts/v1")
        self.assertEqual(summary["schema"], "manufacturing-tax-risk-metrics/v1")
        self.assertEqual(facts["company"], source["company"])
        self.assertEqual(facts["basis"]["unit"], "yuan")
        self.assertEqual(facts["basis"]["consolidation_scope"], "standalone")
        self.assertEqual(facts["source_artifacts"], ["2025年测试三表"])
        self.assertEqual(period["facts"], source["years"]["2025"])
        self.assertEqual(period["evidence"], source["evidence"]["2025"])
        self.assertEqual(period["quality"], {"status": "verified", "missing_fields": [], "notes": ["原报表复核"]})
        self.assertEqual(summary["display_values"]["2025"]["facts"]["revenue"], "96.00万元")  # 960000 / 10000
        self.assertIn("46.43%", receipt["validation_values"])  # 390000 / 840000 * 100

    def test_cli_string_tax_amount_writes_facts_and_metrics(self):
        source = two_year_input()
        source["years"]["2025"]["income_tax_expense"] = "24000"
        facts, summary, receipt = self.calculate_files(source)
        self.assertEqual(facts["periods"]["2025"]["facts"]["income_tax_expense"], 24_000)
        self.assertEqual(summary["display_values"]["2025"]["facts"]["income_tax_expense"], "2.40万元")
        self.assertIn("2.40万元", receipt["validation_values"])

    def test_cli_decimal_amount_preserves_cents_in_json(self):
        source = two_year_input()
        amount = "1000000000000000.01"
        source["years"]["2025"]["income_tax_expense"] = amount
        with TemporaryDirectory() as directory:
            result, facts_path, _ = self.run_calculation(source, directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            facts = json.loads(facts_path.read_text(encoding="utf-8"), parse_float=Decimal)
        self.assertEqual(facts["periods"]["2025"]["facts"]["income_tax_expense"], Decimal(amount))

    def test_cli_invalid_amount_names_field_and_value_without_output(self):
        for value in ("24000元", "NaN", "Infinity"):
            with self.subTest(value=value):
                source = two_year_input()
                source["years"]["2025"]["income_tax_expense"] = value
                self.assert_calculation_failure_leaves_no_output(
                    source, f"invalid amount for 2025.income_tax_expense: {value!r}",
                )

    def test_cli_summary_calculation_error_leaves_no_output(self):
        source = two_year_input()
        source["years"]["2025x"] = source["years"].pop("2025")
        self.assert_calculation_failure_leaves_no_output(source, "invalid literal for int() with base 10: '2025x'")

    def test_decimal_statement_balances_without_a_report_row(self):
        source = two_year_input()
        source["years"]["2025"].update(assets=840_000.30, liabilities=390_000.10, equity=450_000.20)
        _, summary, receipt = self.calculate_files(source)
        self.assertEqual(summary["indicators"]["balance_equation_gap"]["values"]["2025"], 0)
        self.assertNotIn("2025年资产负债表恒等式差额", [row["indicator"] for row in summary["report_rows"]])
        self.assertIn("0.00", receipt["validation_values"])
        self.assertNotIn("0.00yuan", receipt["validation_values"])
        self.assertEqual(calculate_metrics.format_amount(0, "yuan"), "0.00")

    def test_balance_tolerance_is_strict_on_both_sides_of_zero(self):
        for equity, gap, displayed in (
            (450_000.1951, 0.0049, None),
            (450_000.2049, -0.0049, None),
            (450_000.195, 0.005, "0.01元"),
            (450_000.205, -0.005, "-0.01元"),
        ):
            with self.subTest(equity=equity):
                source = two_year_input()
                source["years"]["2025"].update(assets=840_000.30, liabilities=390_000.10, equity=equity)
                _, summary, _ = self.calculate_files(source)
                self.assertEqual(summary["indicators"]["balance_equation_gap"]["values"]["2025"], gap)
                rows = {row["indicator"]: row["result"] for row in summary["report_rows"]}
                self.assertEqual(rows.get("2025年资产负债表恒等式差额"), displayed)

    def test_missing_cost_does_not_list_zero_opening_inventory_as_missing(self):
        for cost in (None, ""):
            with self.subTest(cost=cost):
                source = two_year_input()
                source["years"]["2025"].update(cost=cost, inventory_open=0)
                facts, summary, _ = self.calculate_files(source)
                self.assertEqual(facts["periods"]["2025"]["quality"]["missing_fields"], ["cost"])
                self.assertEqual(summary["uncomputable_indicators"], [
                    {"indicator": "存货周转天数", "year": "2025", "reason": "缺少营业成本，无法计算"},
                ])

    def test_zero_cost_is_a_zero_denominator_and_not_a_missing_amount(self):
        source = two_year_input()
        source["years"]["2025"].update(cost=0, inventory_open=0)
        facts, summary, _ = self.calculate_files(source)
        self.assertEqual(facts["periods"]["2025"]["quality"]["missing_fields"], [])
        self.assertIsNone(facts["periods"]["2025"]["metrics"]["inventory_days"])
        self.assertEqual(summary["uncomputable_indicators"], [
            {"indicator": "存货周转天数", "year": "2025", "reason": "营业成本为 0，无法计算"},
        ])

    def test_growth_explains_a_zero_prior_year_base(self):
        source = two_year_input()
        source["years"]["2024"].update(revenue=0, receivables=0)
        self.assert_growth_unavailable(source, "上年基数为 0，同比不成立")

    def test_growth_explains_a_missing_prior_year_base(self):
        source = two_year_input()
        source["years"]["2024"].update(revenue=None, receivables=None)
        self.assert_growth_unavailable(source, "上年基数缺失")

    def test_growth_explains_a_missing_current_year_value(self):
        source = two_year_input()
        source["years"]["2025"].update(revenue=None, receivables=None)
        self.assert_growth_unavailable(source, "本年值缺失")


if __name__ == "__main__":
    unittest.main()

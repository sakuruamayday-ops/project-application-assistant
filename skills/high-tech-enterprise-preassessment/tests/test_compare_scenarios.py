import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path("scripts/compare_scenarios.py")
POLICY = Path("references/policy-baseline-2026.json")


def scenario(name="本年度"):
    return {
        "name": name,
        "revenue": [100, 135, 182.25],
        "net_assets": [100, 125, 156.25],
        "material_coverage": dict.fromkeys(("ip", "conversion", "organization", "growth"), "complete"),
        "scores": {
            "ip": {"target": 28, "conservative": 27, "stress": 24},
            "conversion": {"target": 29, "conservative": 25, "stress": 19},
            "organization": {"target": 19, "conservative": 17, "stress": 14},
        },
    }


class CompareScenariosTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.scratch = Path(self.temp_dir.name)

    def copy_script(self):
        clone = self.scratch / "skill"
        (clone / SCRIPT).parent.mkdir(parents=True)
        (clone / POLICY).parent.mkdir()
        shutil.copyfile(SKILL_ROOT / SCRIPT, clone / SCRIPT)
        return clone

    def run_cli(self, scenarios, root=SKILL_ROOT):
        input_file = self.scratch / "input.json"
        input_file.write_text(json.dumps({"scenarios": scenarios}), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-B", str(root / SCRIPT), str(input_file)],
            cwd=self.scratch,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def report(self, scenarios, root=SKILL_ROOT):
        process = self.run_cli(scenarios, root)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["schema_version"], "high-tech-scenario-calculation-operation/v2")
        self.assertNotRegex(process.stdout, r"score|total|rating|grade|分")
        self.assertTrue(result["summary"])
        for row in result["items"]:
            self.assertEqual(set(row), {"item", "requirement", "actual", "gap", "evidence", "action", "priority"})
        return result

    def results(self, scenarios, root=SKILL_ROOT):
        return self.report(scenarios, root)["scenarios"]

    def assert_cli_error(self, process, *messages):
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(process.stdout, "")
        error = json.loads(process.stderr)["error"]
        for message in messages:
            self.assertIn(message, error)

    def select_intake(self, coverage):
        input_file = self.scratch / "intake.json"
        input_file.write_text(json.dumps({"material_coverage": coverage}), encoding="utf-8")
        process = subprocess.run(
            [sys.executable, "-B", str(SKILL_ROOT / SCRIPT), "--select-intake", str(input_file)],
            capture_output=True, encoding="utf-8", check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_intake_selects_screening_with_qualification_material_only(self):
        result = self.select_intake({"qualification": "partial"})
        self.assertEqual(result["tier"], "初筛")
        self.assertEqual(result["covered_groups"], [])
        self.assertEqual(result["material_coverage"]["growth"], "none")
        self.assertEqual(len(result["items"]), 6)
        self.assertEqual(result["items"][0]["priority"], "高")

    def test_intake_selects_partial_with_one_covered_item(self):
        result = self.select_intake({"growth": "partial"})
        self.assertEqual(result["tier"], "局部")
        self.assertEqual(result["covered_groups"], ["growth"])
        self.assertIn("财务与成长性", result["basis"])

    def test_intake_selects_full_with_all_six_material_groups_complete(self):
        coverage = dict.fromkeys(("qualification", "growth", "ip", "conversion", "organization", "next_window"), "complete")
        result = self.select_intake(coverage)
        self.assertEqual(result["tier"], "完整")
        self.assertEqual(result["missing_for_complete"], [])
        self.assertEqual(result["items"], [])

    def test_intake_limits_single_window_assessment_to_partial(self):
        coverage = dict.fromkeys(("qualification", "growth", "ip", "conversion", "organization"), "complete")
        coverage["next_window"] = "partial"
        result = self.select_intake(coverage)
        self.assertEqual(result["tier"], "局部")
        self.assertEqual(result["missing_for_complete"], ["next_window"])


    def test_growth_boundaries_match_policy(self):
        cases = [
            (17000, "35.00%", "≥35%", "无"),
            (16998, "34.99%", "≥25%", "差 0.01 pp"),
            (15000, "25.00%", "≥25%", "差 10.00 pp"),
            (14998, "24.99%", "≥15%", "差 0.01 pp"),
            (13000, "15.00%", "≥15%", "差 10.00 pp"),
            (11000, "5.00%", "≥5%", "差 10.00 pp"),
            (10000, "0.00%", "≤0%", "需由零转为正增长"),
            (9800, "-1.00%", "≤0%", "差 1.00 pp"),
        ]
        inputs = [
            dict(scenario(percentage), revenue=[10000, 10000, third], net_assets=[10000, 10000, third])
            for third, percentage, _, _ in cases
        ]
        report = self.report(inputs)
        findings = {row["item"]: row for row in report["items"]}
        self.assertEqual(len(report["scenarios"]), len(cases))
        for result, (_, percentage, band, gap) in zip(report["scenarios"], cases):
            for metric, label in (("revenue", "销售收入增长率"), ("net_assets", "净资产增长率")):
                with self.subTest(percentage=percentage, metric=metric):
                    growth = result["growth"][metric]
                    self.assertEqual(growth["percentage"], percentage)
                    self.assertEqual(growth["band"], band)
                    self.assertEqual(findings[f"{percentage} / {label}"]["gap"], gap)


    def test_changed_tier_boundary_takes_effect(self):
        clone = self.copy_script()
        policy = json.loads((SKILL_ROOT / POLICY).read_text(encoding="utf-8"))
        top_tier = policy["scoring"]["dimensions"]["growth"]["tiers"][0]
        top_tier.update(value=0.40)
        (clone / POLICY).write_text(json.dumps(policy), encoding="utf-8")
        inputs = [scenario("本年度"), dict(scenario("次年度"), revenue=[100, 140, 196])]
        report = self.report(inputs, clone)
        findings = {row["item"]: row for row in report["items"]}
        below, at = [result["growth"]["revenue"] for result in report["scenarios"]]
        self.assertEqual((below["band"], at["band"]), ("≥25%", "≥40%"))
        self.assertEqual(findings["本年度 / 销售收入增长率"]["gap"], "差 5.00 pp")
        self.assertEqual(findings["次年度 / 销售收入增长率"]["gap"], "无")


    def test_missing_coverage_leaves_gate_open_and_financial_growth_reproducible(self):
        legacy_input, explicit_input = scenario(), scenario()
        del legacy_input["material_coverage"]
        del explicit_input["material_coverage"]
        for values in explicit_input["scores"].values():
            values["coverage"] = 1
        explicit_input["scores"]["growth"] = {"coverage": 1}
        legacy, explicit = self.results([legacy_input, explicit_input])
        self.assertEqual(legacy["growth"], explicit["growth"])
        self.assertEqual(legacy["coverage"], dict.fromkeys(("ip", "conversion", "organization", "growth")))
        self.assertIsNone(legacy["innovation_requirement_met"])
        self.assertEqual(explicit["coverage"], dict.fromkeys(("ip", "conversion", "organization", "growth"), 1))
        self.assertIs(explicit["innovation_requirement_met"], True)

    def test_partial_intake_coverage_blocks_full_coverage_in_legacy_fields(self):
        data = scenario()
        data["material_coverage"]["ip"] = "partial"
        data["scores"]["ip"]["coverage"] = 1
        report = self.report([data])
        result, = report["scenarios"]
        self.assertIsNone(result["coverage"]["ip"])
        self.assertIsNone(result["innovation_requirement_met"])
        self.assertTrue(any(item["gap"] == "缺可定位的覆盖记录" for item in report["items"]))

    def test_partial_coverage_reports_named_gaps_even_above_the_pass_threshold(self):
        data = scenario()
        missing = ["技术先进程度的对比验证", "主要产品的核心支持证据"]
        data["scores"]["ip"] = {
            "target": 20, "conservative": 18, "stress": 15, "coverage": 0.7,
            "missing_evidence": missing,
        }
        report = self.report([data])
        result, = report["scenarios"]
        self.assertEqual(result["coverage"], {"ip": 0.7, "conversion": 1, "organization": 1, "growth": 1})
        self.assertIsNone(result["innovation_requirement_met"])
        for criterion, row in zip(missing, report["items"][:2]):
            self.assertEqual(row["item"], f"本年度 / {criterion}")
            self.assertEqual(row["actual"], "知识产权证据覆盖率 70.00%")
            self.assertEqual(row["gap"], "缺本项证明材料")


    def test_components_without_named_gaps_preserve_coverage(self):
        data = scenario()
        data["scores"]["organization"] = {
            "coverage": 0.375,
            "components": [
                {"target": 2.5, "conservative": 2, "stress": 1},
                {"target": 5, "conservative": 4, "stress": 3},
            ],
        }
        report = self.report([data])
        self.assertEqual(report["scenarios"][0]["coverage"]["organization"], 0.375)
        self.assertEqual(report["items"][0]["gap"], "未覆盖比例 62.50%，缺具体评价点名称")


    def test_growth_coverage_uses_only_assessed_metrics(self):
        data = scenario()
        data["scores"]["growth"] = {"coverage": 0.5, "missing_evidence": ["净资产增长率"]}
        del data["net_assets"]
        report = self.report([data])
        result, = report["scenarios"]
        self.assertEqual(result["coverage"]["growth"], 0.5)
        self.assertIsNone(result["growth"]["net_assets"]["band"])
        self.assertIsNone(result["innovation_requirement_met"])
        finding = next(row for row in report["items"] if row["item"].endswith("净资产增长率"))
        self.assertEqual(finding["gap"], "暂不能复算")

    def test_material_only_input_keeps_missing_years_and_independent_growth(self):
        current, following = scenario("2026"), scenario("2027")
        for data in (current, following):
            del data["scores"]
            data["material_coverage"]["growth"] = "partial"
        current["revenue"] = [100, 135, None]
        following["net_assets"] = [125, None, None]
        report = self.report([current, following])
        self.assertEqual(report["validation_errors"], [])
        this_year, next_year = report["scenarios"]
        self.assertIsNone(this_year["growth"]["revenue"]["rate"])
        self.assertEqual(this_year["growth"]["net_assets"]["percentage"], "25.00%")
        self.assertIsNone(next_year["growth"]["net_assets"]["rate"])
        self.assertEqual(next_year["growth"]["revenue"]["percentage"], "35.00%")
        self.assertTrue(all(item["innovation_requirement_met"] is None for item in report["scenarios"]))
        findings = {item["item"]: item for item in report["items"]}
        self.assertIn("第 3 个会计年度", findings["2026 / 销售收入增长率"]["actual"])
        self.assertEqual(findings["2027 / 创新能力资格"]["gap"], "缺该年度正式评价结果")

    def test_existing_coverage_metadata_does_not_require_scores(self):
        data = scenario()
        data["scores"] = {"ip": {"coverage": 0.5, "missing_evidence": ["对应权利要求"]}}
        report = self.report([data])
        self.assertEqual(report["scenarios"][0]["coverage"]["ip"], 0.5)
        self.assertIsNone(report["scenarios"][0]["innovation_requirement_met"])
        self.assertIn("本年度 / 对应权利要求", {item["item"] for item in report["items"]})

    def test_invalid_coverage_and_scores_over_covered_weight_fail(self):
        for coverage in (-0.1, 1.1, "0.7", True, float("nan")):
            with self.subTest(coverage=coverage):
                data = scenario()
                data["scores"]["ip"]["coverage"] = coverage
                self.assert_cli_error(self.run_cli([data]), "scores.ip.coverage")
        data = scenario()
        data["scores"]["ip"]["coverage"] = 0.7
        self.assert_cli_error(self.run_cli([data]), "scores.ip", "按证据调整已评数值或 coverage")

    def test_innovation_uses_exact_policy_threshold_and_operator(self):
        inputs = [
            dict(scenario(), revenue=[100, 100, 100], net_assets=[100, 100, 100], scores={
                "ip": 27.6, "conversion": 27.2, "organization": organization,
            })
            for organization in (15.19, 15.20, 15.21)
        ]
        results = self.results(inputs)
        self.assertEqual([result["innovation_requirement_met"] for result in results], [False, False, True])
        clone = self.copy_script()
        policy = json.loads((SKILL_ROOT / POLICY).read_text(encoding="utf-8"))
        policy["scoring"]["pass_threshold"] = {"value": 70.1, "operator": "gte"}
        (clone / POLICY).write_text(json.dumps(policy), encoding="utf-8")
        higher = dict(inputs[1], scores=dict(inputs[1]["scores"], organization=15.3))
        results = self.results([inputs[2], higher], clone)
        self.assertEqual([result["innovation_requirement_met"] for result in results], [False, True])


    def test_negative_denominator_keeps_financial_review(self):
        data = dict(scenario(), net_assets=[-100, 125, 156.25])
        report = self.report([data])
        result, = report["scenarios"]
        self.assertIsNone(result["growth"]["net_assets"]["rate"])
        self.assertIsNone(result["innovation_requirement_met"])
        finding = next(row for row in report["items"] if row["item"].endswith("净资产增长率"))
        self.assertEqual(finding["gap"], "需财务专项复核")

    def test_missing_policy_fails(self):
        clone = self.copy_script()
        self.assert_cli_error(self.run_cli([scenario()], clone), "invalid policy baseline", POLICY.name, "No such file")

    def test_invalid_policy_fails(self):
        clone = self.copy_script()
        (clone / POLICY).write_text("{", encoding="utf-8")
        self.assert_cli_error(self.run_cli([scenario()], clone), "invalid policy baseline", POLICY.name)
        policy = json.loads((SKILL_ROOT / POLICY).read_text(encoding="utf-8"))
        policy["scoring"]["dimensions"]["growth"]["tiers"] = []
        (clone / POLICY).write_text(json.dumps(policy), encoding="utf-8")
        self.assert_cli_error(self.run_cli([scenario()], clone), POLICY.name, "scoring.dimensions.growth.tiers")

    def batch_diagnostics(self, inputs):
        process = self.run_cli(inputs)
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(process.stdout, "")
        return json.loads(process.stderr)

    def test_missing_score_reports_five_fields_with_json_null(self):
        data = scenario("2026")
        del data["scores"]["ip"]["conservative"]
        error, = self.batch_diagnostics([data])["validation_errors"]
        self.assertEqual(set(error), {"field_path", "actual", "expected", "fix", "business_location"})
        self.assertEqual(error["field_path"], "scenarios[0].scores.ip.conservative")
        self.assertIsNone(error["actual"])
        self.assertTrue(error["expected"])
        self.assertTrue(error["fix"])
        self.assertEqual(error["business_location"], "2026 / 知识产权")

    def test_collects_multiple_issues_within_and_across_years(self):
        current, following = scenario("2026"), scenario("2027")
        current["revenue"][1] = "缺数"
        current["scores"]["ip"] = {"components": [
            {"target": "错误", "stress": -1},
            None,
        ], "coverage": 1.2}
        following["scores"]["organization"] = {"target": 10, "conservative": 11, "stress": 13}
        del following["net_assets"]
        issues = self.batch_diagnostics([current, following])["validation_errors"]
        self.assertEqual({item["field_path"] for item in issues}, {
            "scenarios[0].revenue[1]",
            "scenarios[0].scores.ip.coverage",
            "scenarios[0].scores.ip.components[0].target",
            "scenarios[0].scores.ip.components[0].conservative",
            "scenarios[0].scores.ip.components[0].stress",
            "scenarios[0].scores.ip.components[1]",
            "scenarios[1].scores.organization.conservative",
            "scenarios[1].scores.organization.stress",
            "scenarios[1].net_assets",
        })
        issue_by_path = {item["field_path"]: item for item in issues}
        revenue = issue_by_path["scenarios[0].revenue[1]"]
        self.assertEqual(revenue["actual"], "缺数")
        self.assertEqual(revenue["business_location"], "2026 / 财务与成长性 / 销售收入 / 第 2 个会计年度")
        self.assertIsNone(issue_by_path["scenarios[1].net_assets"]["actual"])

    def test_bad_growth_input_preserves_independent_metrics_and_other_year(self):
        current, following = scenario("2026"), scenario("2027")
        current["revenue"][0] = None
        report = self.batch_diagnostics([current, following])
        self.assertEqual(len(report["validation_errors"]), 1)
        partial, complete = report["scenarios"]
        self.assertEqual(set(partial["growth"]), {"net_assets"})
        self.assertEqual(partial["growth"]["net_assets"]["percentage"], "25.00%")
        self.assertIsNone(partial["innovation_requirement_met"])
        self.assertEqual(complete, self.results([following])[0])

    def test_corrected_input_rechecks_eligibility(self):
        current, following = scenario("2026"), scenario("2027")
        current["scores"]["conversion"]["conservative"] = 33
        failed = self.batch_diagnostics([current, following])
        self.assertEqual(len(failed["validation_errors"]), 1)
        self.assertEqual(failed["validation_errors"][0]["actual"], 33)
        self.assertIsNone(failed["scenarios"][0]["innovation_requirement_met"])
        current["scores"]["conversion"]["conservative"] = 25

        corrected = self.run_cli([current, following])
        self.assertEqual(corrected.returncode, 0, corrected.stderr)
        self.assertEqual(corrected.stderr, "")
        batch = json.loads(corrected.stdout)
        self.assertEqual(batch["validation_errors"], [])
        self.assertIs(batch["scenarios"][0]["innovation_requirement_met"], True)
        self.assertEqual(batch["scenarios"][1], failed["scenarios"][1])

    def test_bad_evidence_and_covered_weight_are_both_reported(self):
        data = scenario()
        data["scores"]["ip"].update(coverage=0.7, missing_evidence=[None])
        diagnostics = self.batch_diagnostics([data])["validation_errors"]
        self.assertEqual({item["field_path"] for item in diagnostics}, {
            "scenarios[0].scores.ip.missing_evidence[0]",
            "scenarios[0].scores.ip.target",
            "scenarios[0].scores.ip.conservative",
            "scenarios[0].scores.ip.stress",
        })

    def test_wrong_scenario_shape_does_not_stop_other_year(self):
        following = scenario("2027")
        diagnostics = self.batch_diagnostics([None, following])
        issue, = diagnostics["validation_errors"]
        self.assertEqual(issue["field_path"], "scenarios[0]")
        self.assertIsNone(issue["actual"])
        self.assertIsNone(diagnostics["scenarios"][0])
        self.assertEqual(diagnostics["scenarios"][1], self.results([following])[0])


if __name__ == "__main__":
    unittest.main()

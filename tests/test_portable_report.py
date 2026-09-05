import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PortableReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = Path(__file__).resolve().parents[1]
        cls.skills = cls.repository / "skills"
        cls.tax = cls.skills / "manufacturing-tax-risk-analysis"
        cls.runtime = cls.skills / "_runtime" / "gongchuang-branding"

    def generate_metrics(self, directory: Path) -> Path:
        facts = directory / "facts.json"
        metrics = directory / "metrics.json"
        subprocess.run(
            [
                sys.executable,
                str(self.tax / "scripts/calculate_metrics.py"),
                str(self.tax / "references/metrics-input.example.json"),
                str(facts),
                "--metrics-output",
                str(metrics),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return metrics

    def test_generator_outputs_exactly_seventeen_page_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            output = directory_path / "report.html"
            metrics = self.generate_metrics(directory_path)
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.tax / "scripts/generate_report_html.py"),
                    str(self.tax / "references/report-data.example.json"),
                    str(output),
                    "--metrics-json",
                    str(metrics),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["pages"], 17)
            self.assertEqual(
                output.read_text(encoding="utf-8").count('<section class="page'),
                17,
            )

    def test_generator_and_delivery_contract_use_the_same_visible_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            output = directory_path / "report.html"
            metrics = self.generate_metrics(directory_path)
            subprocess.run(
                [
                    sys.executable,
                    str(self.tax / "scripts/generate_report_html.py"),
                    str(self.tax / "references/report-data.example.json"),
                    str(output),
                    "--metrics-json",
                    str(metrics),
                ],
                check=True,
            )
            html = output.read_text(encoding="utf-8")
            contracts = json.loads((self.skills / "delivery-contracts.json").read_text(encoding="utf-8"))
            profile = contracts["delivery_profiles"]["manufacturing-tax-risk-report"]
            cursor = 0
            for section in profile["required_sections"]:
                cursor = html.index(section, cursor) + len(section)
            for table_rule in profile["required_tables"]:
                self.assertIn(table_rule["id"], html)
                for column in table_rule["required_columns"]:
                    self.assertIn(column, html)
            for expected in (
                "2024年营业收入同比增长率",
                "2025年研发费用率",
            ):
                self.assertIn(expected, html)

    def test_generator_rejects_structured_values_in_all_human_text_lists(self):
        mutations = (
            (
                "section action",
                lambda data: data["sections"]["profitability"]["actions"].__setitem__(0, {"text": "错误对象"}),
                "field must be text: root.sections.profitability.actions[0]",
            ),
            (
                "roadmap action",
                lambda data: data["roadmap"][0]["actions"].__setitem__(0, {"text": "错误对象"}),
                "field must be text: root.roadmap[0].actions[0]",
            ),
            (
                "p0 document",
                lambda data: data["p0_documents"].__setitem__(0, {"name": "错误对象"}),
                "field must be text: root.p0_documents[0]",
            ),
            (
                "missing document",
                lambda data: data["missing_documents"].__setitem__(0, {"name": "错误对象"}),
                "field must be text: root.missing_documents[0]",
            ),
            (
                "limitation",
                lambda data: data["limitations"].__setitem__(0, {"text": "错误对象"}),
                "field must be text: root.limitations[0]",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            metrics = self.generate_metrics(directory_path)
            example = json.loads(
                (self.tax / "references/report-data.example.json").read_text(encoding="utf-8")
            )
            for index, (label, mutate, expected) in enumerate(mutations):
                with self.subTest(label=label):
                    candidate = json.loads(json.dumps(example, ensure_ascii=False))
                    mutate(candidate)
                    input_path = directory_path / f"invalid-{index}.json"
                    input_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(self.tax / "scripts/generate_report_html.py"),
                            str(input_path),
                            "--validate-only",
                            "--metrics-json",
                            str(metrics),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)

    def test_generator_rejects_non_object_report_rows_before_rendering(self):
        mutations = (
            ("sources", "field must be an object: root.sources[0]"),
            ("executive_findings", "field must be an object: root.executive_findings[0]"),
            ("risks", "field must be an object: root.risks[0]"),
            ("calculations", "field must be an object: root.calculations[0]"),
            ("policies", "field must be an object: root.policies[0]"),
            ("monthly_indicators", "field must be an object: root.monthly_indicators[0]"),
        )
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            metrics = self.generate_metrics(directory_path)
            example = json.loads(
                (self.tax / "references/report-data.example.json").read_text(encoding="utf-8")
            )
            for index, (field, expected) in enumerate(mutations):
                with self.subTest(field=field):
                    candidate = json.loads(json.dumps(example, ensure_ascii=False))
                    candidate[field][0] = "错误字符串"
                    input_path = directory_path / f"invalid-object-{index}.json"
                    input_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(self.tax / "scripts/generate_report_html.py"),
                            str(input_path),
                            "--validate-only",
                            "--metrics-json",
                            str(metrics),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)

    def test_optional_kpi_note_and_empty_supplemental_calculations_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            metrics = self.generate_metrics(directory_path)
            candidate = json.loads(
                (self.tax / "references/report-data.example.json").read_text(encoding="utf-8")
            )
            candidate["financial_overview"]["kpis"][0].pop("note")
            candidate["calculations"] = []
            input_path = directory_path / "optional-fields.json"
            output_path = directory_path / "optional-fields.html"
            input_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(self.tax / "scripts/generate_report_html.py"),
                    str(input_path),
                    str(output_path),
                    "--metrics-json",
                    str(metrics),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            html = output_path.read_text(encoding="utf-8")
            self.assertIn("2025年研发费用率", html)
            self.assertIn("final-indicator-table", html)
            self.assertNotIn("None", html)

    def test_missing_official_policy_generates_an_explicit_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            metrics = self.generate_metrics(directory_path)
            candidate = json.loads(
                (self.tax / "references/report-data.example.json").read_text(encoding="utf-8")
            )
            candidate["policies"] = []
            input_path = directory_path / "draft.json"
            output_path = directory_path / "draft.html"
            input_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(self.tax / "scripts/generate_report_html.py"),
                    str(input_path),
                    str(output_path),
                    "--metrics-json",
                    str(metrics),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            html = output_path.read_text(encoding="utf-8")
            self.assertEqual(html.count('<section class="page'), 17)
            self.assertIn("草稿：政策原文未核验", html)
            self.assertIn("本报告为草稿，不得作为正式税务结论使用", html)

    def test_placeholder_policy_is_rejected_instead_of_presented_as_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            metrics = self.generate_metrics(directory_path)
            candidate = json.loads(
                (self.tax / "references/report-data.example.json").read_text(encoding="utf-8")
            )
            candidate["policies"] = [{
                "name": "研发费用加计扣除政策",
                "issuer": "现行状态待核验",
                "date": "待核验",
                "url": "https://example.invalid/pending",
            }]
            input_path = directory_path / "placeholder-policy.json"
            input_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(self.tax / "scripts/generate_report_html.py"),
                    str(input_path),
                    "--validate-only",
                    "--metrics-json",
                    str(metrics),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("placeholder policy is not allowed", result.stderr)

    def test_portable_scripts_do_not_contain_machine_paths(self):
        forbidden = ("/Users/", "/Volumes/", ".agents/skills")
        paths = [
            self.tax / "scripts/brand_gold_pdf.py",
            self.tax / "scripts/generate_report_html.py",
            self.tax / "scripts/render_pdf_stdout.js",
            self.tax / "scripts/verify_e2e.py",
            self.runtime / "scripts/brand_config.py",
            self.runtime / "scripts/pdf_two_pass.py",
            self.runtime / "scripts/delivery_gate.py",
        ]
        for path in paths:
            content = path.read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, content, f"{path} contains {marker}")

    def test_branding_runtime_imports_from_its_own_directory(self):
        module_path = self.runtime / "scripts/brand_config.py"
        spec = importlib.util.spec_from_file_location("portable_brand_config", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        config = module.load_config()
        self.assertEqual(config["policy"]["position"], [0.5, 0.5])
        style = module.choose_style(0.5, target="pdf", variant="gold")
        self.assertTrue(Path(style["asset_path"]).is_file())


if __name__ == "__main__":
    unittest.main()

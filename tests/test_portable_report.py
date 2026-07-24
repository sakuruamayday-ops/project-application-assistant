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
        cls.runtime = cls.skills / "_runtime" / "jiaotang-branding"

    def test_generator_outputs_exactly_seventeen_page_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.html"
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.tax / "scripts/generate_report_html.py"),
                    str(self.tax / "references/report-data.example.json"),
                    str(output),
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

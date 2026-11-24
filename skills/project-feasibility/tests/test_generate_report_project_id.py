import json
import subprocess
import sys
import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch

from docx import Document


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import generate_report as report
from select_report_template import load_registry, resolve_template, sha256_file


class GenerateReportProjectIdTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        master = self.directory / "master.docx"
        document = Document()
        document.add_paragraph("申报主体：［填写］")
        document.add_paragraph("主导产品或申报对象：［填写］")
        document.save(master)

        registry = load_registry()
        project = next(project for project in registry["projects"] if project["id"] == "green-factory")
        project["templates"] = {"preassessment": {"path": master.name, "sha256": sha256_file(master)}}
        registry["projects"] = [project]
        registry_dir = self.directory / "references"
        registry_dir.mkdir()
        self.registry_path = registry_dir / "report-template-registry.json"
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    def assert_report(self, input_id, receipt_id):
        source = self.directory / "facts.json"
        output = self.directory / "report.docx"
        source.write_text(
            json.dumps({"project_id": input_id, "enterprise": "示例企业", "project_object": "绿色工厂"}, ensure_ascii=False),
            encoding="utf-8",
        )
        with (
            patch.object(report, "load_registry", partial(load_registry, self.registry_path)),
            patch.object(report, "resolve_template", partial(resolve_template, registry_path=self.registry_path)),
        ):
            result = report.generate_report(source, output, "preassessment")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["project_id"], receipt_id)
        receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["project_id"], receipt_id)
        self.assertIn("示例企业", "\n".join(paragraph.text for paragraph in Document(output).paragraphs))

    def test_index_id_reaches_report_and_completion_receipt(self):
        matching = SKILL_ROOT.parent / "project-matching"
        filtered = subprocess.run(
            [sys.executable, "-B", str(matching / "scripts" / "filter_project_map.py"),
             str(matching / "references" / "project-map.jsonl"), "--scope", "全国", "--keyword", "绿色工厂"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        project_id = json.loads(filtered.stdout)["project_id"]
        self.assert_report(project_id, project_id)

    def test_legacy_template_alias_still_routes_to_same_template(self):
        self.assert_report("国家绿色工厂", "green-factory")

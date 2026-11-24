import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from docx import Document


SKILL = Path(__file__).resolve().parents[1]
POLICIES = SKILL.parent / "high-tech-enterprise-preassessment/references/policies"


class OfficialPolicyEvidenceTests(unittest.TestCase):
    def command(self, script, *args, code=0):
        run = subprocess.run([sys.executable, str(SKILL / "scripts" / script), *map(str, args)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, code, run.stderr or run.stdout)
        return run

    def test_original_fact_reaches_word_with_source_and_links_only_are_rejected(self):
        original_path = next(POLICIES.glob("国科发火〔2016〕32号-*.md"))
        original = original_path.read_text()
        excerpt = "企业申请认定时须注册成立一年以上；"
        self.assertIn(excerpt, original)
        url = original.split("- 官方来源：<", 1)[1].split(">", 1)[0]
        claim = "企业申请认定时须注册成立一年以上。"
        source = {"id": "S1", "kind": "official_web", "access_status": "obtained",
                  "title": "国科发火〔2016〕32号", "publisher": "科学技术部",
                  "url": url, "retrieved_at": "2026-11-20", "internal": {"path": str(original_path)}}
        fact = {"id": "F1", "subject": "高新技术企业认定管理办法", "claim": claim,
                "type": "fact", "source": "S1", "retrieved_at": "2026-11-20",
                "location": "第十一条第一项", "status": "verified", "evidence_excerpt": excerpt}
        ledger = {"schema_version": "grounded-evidence/v1", "sources": [source],
                  "records": [fact], "document": {"blocks": [{"text": claim, "claim_ids": ["F1"]}]}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "ledger.json"
            path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
            checked = self.command("validate_evidence_ledger.py", path, "--strict-grounded")
            self.assertEqual(json.loads(checked.stdout)["status"], "pass")
            report = root / "report.md"
            self.command("grounded_evidence.py", "render", path, "--mode", "report", "--output", report)
            text = report.read_text()
            self.assertIn(f"{claim}[1]", text)
            self.assertIn(url, text)
            artifact = root / "report.docx"
            self.command("create_docx_from_text.py", "--input-file", report, artifact)
            doc = Document(artifact)
            paragraphs = [p.text for p in doc.paragraphs]
            table_text = [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
            combined = "\n".join(paragraphs + table_text)
            self.assertIn(claim, combined)
            self.assertIn(source["title"], combined)

            del source["retrieved_at"]
            source.update(access_status="reference_only", registered_at="2026-11-20", registered_via="S2")
            ledger["sources"].append({"id": "S2", "kind": "user_file", "access_status": "obtained",
                                       "file_name": "样例检索登记.txt", "retrieved_at": "2026-11-20"})
            path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
            blocked = self.command("validate_evidence_ledger.py", path, "--strict-grounded", code=2)
            self.assertTrue(any("已核验记录不得直接依赖" in error for error in json.loads(blocked.stdout)["errors"]))


if __name__ == "__main__":
    unittest.main()

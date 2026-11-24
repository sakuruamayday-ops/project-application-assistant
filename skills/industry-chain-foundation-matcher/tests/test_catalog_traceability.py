import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest


SKILL = Path(__file__).resolve().parents[1]


class CatalogTraceabilityTests(unittest.TestCase):
    def search(self, query):
        run = subprocess.run([sys.executable, str(SKILL / "scripts/search_catalogs.py"), query, "--limit", "3"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_exact_and_nearby_terms_keep_their_own_source_pages(self):
        exact = self.search("六维力传感器")
        self.assertEqual(exact["search_summary"]["industry_chain"]["normalized_term_matches"], 1)
        self.assertEqual(exact["industry_chain"][0]["path"], "工业机器人->核心零部件->传感器->六维力传感器")
        self.assertEqual(exact["industry_chain"][0]["page"], 11)
        self.assertEqual(exact["search_summary"]["industry_foundation"]["normalized_term_matches"], 0)
        self.assertTrue(any(row["item"] == "宽温区压力传感器" and row["page"] == 50
                            for row in exact["industry_foundation"]))
        near = self.search("六维力矩传感器")
        self.assertEqual(near["search_summary"]["industry_chain"]["normalized_term_matches"], 0)
        self.assertEqual(near["industry_chain"][0]["page"], 11)
        manifest = json.loads((SKILL / "references/source-manifest.json").read_text())
        for catalog in ("industry_chain", "industry_foundation"):
            entry = manifest[catalog]
            pdf = SKILL / "references/source-documents" / entry["source_file"]
            self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), entry["sha256"])


if __name__ == "__main__":
    unittest.main()

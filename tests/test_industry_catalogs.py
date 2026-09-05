import json
import hashlib
import subprocess
import unittest
from collections import Counter
from pathlib import Path


class IndustryCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = Path(__file__).resolve().parents[1]
        cls.skill = cls.repository / "skills" / "industry-chain-foundation-matcher"

    @staticmethod
    def load_jsonl(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def test_industry_chain_hierarchy_is_complete(self):
        records = self.load_jsonl(self.skill / "references" / "industry-chain-index.jsonl")
        self.assertEqual(len(records), 2128)
        paths = {record["path"] for record in records}
        self.assertEqual(sum("->" not in path for path in paths), 26)
        for path in paths:
            if "->" in path:
                self.assertIn(path.rsplit("->", 1)[0], paths)

    def test_industry_foundation_counts_match_source(self):
        records = self.load_jsonl(self.skill / "references" / "industry-foundation-index.jsonl")
        self.assertEqual(len(records), 1047)
        self.assertEqual(
            Counter(record["category"] for record in records),
            Counter(
                {
                    "基础零部件和元器件": 289,
                    "基础材料": 269,
                    "工业基础软件": 100,
                    "基础制造工艺及装备": 260,
                    "产业技术基础": 129,
                }
            ),
        )
        self.assertEqual(len({record["field"] for record in records}), 21)

    def test_search_returns_known_catalog_item(self):
        result = subprocess.run(
            [
                "python3",
                str(self.skill / "scripts" / "search_catalogs.py"),
                "高性能和功能高分子复合材料层叠定构工艺",
                "--limit",
                "3",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        items = [record["item"] for record in payload["industry_foundation"]]
        self.assertIn("高性能和功能高分子复合材料层叠定构工艺", items)

    def test_source_pdfs_are_packaged_unchanged(self):
        expected = {
            "产业链架构(2).pdf": "0235e6eef74f76aa94e81e6d85294345f8b979ce3cbadef024bd684056f4bd56",
            "工业六基领域目录(2).pdf": "c19cd2af7c329b143cf4862f88deddfc79bc4f8c2a3a33e134eba3c454feb6fc",
        }
        source_documents = self.skill / "references" / "source-documents"
        for filename, digest in expected.items():
            with self.subTest(filename=filename):
                path = source_documents / filename
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def search(self, query, limit=10):
        result = subprocess.run(
            ["python3", str(self.skill / "scripts" / "search_catalogs.py"), query, "--limit", str(limit)],
            check=True, capture_output=True, text=True,
        )
        return json.loads(result.stdout)

    def test_excluded_gearbox_still_counts_as_a_search_hit(self):
        payload = self.search("齿轮箱")
        summary = payload["search_summary"]["industry_foundation"]
        self.assertEqual(summary["scanned_records"], 1047)
        self.assertEqual(summary["normalized_term_matches"], 1)
        item = next(item for item in payload["industry_foundation"] if item["item"] == "大功率掘锚机截割齿轮箱")
        self.assertEqual((item["field"], item["page"]), ("工程机械", 53))

    def test_return_limit_does_not_change_full_catalog_counts(self):
        empty = self.search("齿轮箱", 0)
        full = self.search("齿轮箱", 10)
        for catalog in ("industry_chain", "industry_foundation"):
            self.assertEqual(empty[catalog], [])
            for field in ("scanned_records", "normalized_term_matches", "scored_candidates"):
                self.assertEqual(empty["search_summary"][catalog][field], full["search_summary"][catalog][field])
            self.assertEqual(empty["search_summary"][catalog]["returned_candidates"], 0)

    def test_reducer_is_present_in_chain_not_foundation_terms(self):
        payload = self.search("减速器")
        self.assertGreater(payload["search_summary"]["industry_chain"]["normalized_term_matches"], 0)
        self.assertEqual(payload["search_summary"]["industry_foundation"]["normalized_term_matches"], 0)


if __name__ == "__main__":
    unittest.main()

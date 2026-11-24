import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "filter_project_map.py"


class FilterProjectMapTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def make_index(self, filename, records):
        index = self.directory / filename
        index.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        return index

    def run_filter(self, index, *options):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), str(index), *options],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=self.directory,
        )

    def matches(self, index, *options):
        result = self.run_filter(index, *options)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_bundled_indexes_find_the_same_project(self):
        options = ("--scope", "全国", "--keyword", "绿色工厂")
        canonical = self.matches(SKILL_ROOT / "references" / "canonical-project-index.jsonl", *options)
        project_map = self.matches(SKILL_ROOT / "references" / "project-map.jsonl", *options)
        self.assertEqual([row["canonical_project_name"] for row in canonical], ["国家绿色工厂"])
        self.assertEqual([row["title"] for row in project_map], ["国家绿色工厂"])
        self.assertEqual([row["project_id"] for row in canonical], [row["project_id"] for row in project_map])

    def test_ningbo_technology_center_does_not_take_provincial_title(self):
        script = SKILL_ROOT / "scripts/build_retrieval_gold_standard.py"
        output = self.directory / "cases.jsonl"
        help_result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--output", help_result.stdout)
        run = subprocess.run([sys.executable, str(script), "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        cases = [json.loads(line) for line in output.read_text().splitlines()]
        ningbo = next(row for row in cases if row["id"].endswith("宁波市企业技术中心:cross-project"))
        self.assertEqual(ningbo["allowed_title"], "宁波市企业技术中心管理办法")
        self.assertEqual(ningbo["excluded_title"], "浙江省企业技术中心管理办法")

    def test_provincial_research_institute_candidate_links_to_management_rule(self):
        result = self.matches(SKILL_ROOT / "references/canonical-project-index.jsonl",
                              "--scope", "浙江省", "--keyword", "省重点企业研究院")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["canonical_project_name"], "浙江省重点企业研究院")
        self.assertNotIn("year", result[0])
        management = next((SKILL_ROOT.parent / "technology-innovation-projects/references/policies").glob("浙经信高新〔2025〕169号-*.md"))
        self.assertIn(management.name, (SKILL_ROOT / "references/project-matching-rules.md").read_text())
        self.assertIn("浙江省重点企业研究院、企业研究院建设与管理办法", management.read_text())

    def test_matching_rules_point_to_management_policies(self):
        index = SKILL_ROOT / "references/high-frequency-project-rules.jsonl"
        results = self.matches(index, "--scope", "全国", "--scope", "浙江省")
        self.assertTrue(results)
        for row in results:
            with self.subTest(project=row["canonical_project_name"]):
                policy = (index.parent / row["management_rule"]).resolve()
                self.assertTrue(policy.is_file(), policy)
                self.assertIn("管理", policy.name)
                self.assertTrue(row["condition_sections"])
                self.assertTrue(row["match_by"])
        names = self.matches(index, "--scope", "全国", "--keyword", "绿色工厂")
        self.assertEqual([row["canonical_project_name"] for row in names], ["国家绿色工厂"])

    def test_name_priority_and_fallback(self):
        index = self.make_index("names.jsonl", [
            {"canonical_project_name": "标准项目", "title": "地图项目", "name": "旧名称", "primary_region": "全国"},
            {"canonical_project_name": " ", "title": "地图项目", "name": "旧名称", "primary_region": "全国"},
            {"title": None, "name": "旧名称", "primary_region": "全国"},
        ])
        for keyword in ("标准项目", "地图项目", "旧名称"):
            with self.subTest(keyword=keyword):
                matches = self.matches(index, "--scope", "全国", "--keyword", keyword)
                self.assertEqual(len(matches), 1)
                self.assertEqual(json.loads(matches[0]["project_id"].removeprefix("project:"))[0], keyword)
        self.assertEqual(len(self.matches(index, "--scope", "全国")), 3)

    def test_missing_name_reports_index_and_physical_line(self):
        index = self.directory / "bad.jsonl"
        index.write_text(
            '{"title":"项目","primary_region":"全国"}\n\n{"primary_region":"杭州市"}\n',
            encoding="utf-8",
        )
        result = self.run_filter(index, "--scope", "全国")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn(f"{index}:3", result.stderr)
        self.assertIn("缺少项目名称", result.stderr)
        for field in ("canonical_project_name", "title", "name"):
            self.assertIn(field, result.stderr)

    def test_scope_is_exact_by_default_and_contains_is_explicit(self):
        index = self.make_index("scopes.jsonl", [
            {"title": "A", "primary_region": "杭州市"},
            {"title": "B", "primary_region": "余杭区", "regions": ["余杭区", "杭州市"]},
            {"title": "C", "primary_region": "全国"},
        ])
        self.assertEqual(self.matches(index, "--scope", "杭州"), [])
        exact = self.matches(index, "--scope", "杭州市")
        self.assertEqual([row["title"] for row in exact], ["A"])
        contains = self.matches(index, "--scope-match", "contains", "--scope", "杭州", "--scope", "全国")
        self.assertEqual([row["title"] for row in contains], ["A", "C"])

    def test_id_normalizes_identity_and_distinguishes_name_region_and_year(self):
        index = self.make_index("projects.jsonl", [
            {"case": "original", "title": "ＡＢＣ　工厂", "primary_region": "杭州市 ", "year": 2026},
            {"case": "same", "name": "abc  工厂", "primary_region": "杭州市", "year": "２０２６年度"},
            {"case": "name", "name": "乙工厂", "primary_region": "杭州市", "year": 2026},
            {"case": "region", "name": "abc 工厂", "primary_region": "宁波市", "year": 2026},
            {"case": "year", "name": "abc 工厂", "primary_region": "杭州市", "year": 2025},
        ])
        options = ("--scope-match", "contains", "--scope", "杭州", "--scope", "宁波")
        matches = self.matches(index, *options)
        self.assertEqual(matches, self.matches(index, *options))
        ids = {row["case"]: row["project_id"] for row in matches}
        self.assertEqual(ids["original"], ids["same"])
        self.assertEqual(len(set(ids.values())), 4)

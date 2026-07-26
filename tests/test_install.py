import json
import sys
import tempfile
import unittest
import subprocess
import zipfile
from pathlib import Path

from project_assistant.installer import classify_skill_change, install_skills
from scripts.build_standard_package import (
    HOST_SKILL_INSTALL_PROMPT,
    PORTABLE_REPORT_REQUIRED,
    included,
    validate_release_archive,
    validate_release_source,
)


class InstallTests(unittest.TestCase):
    @staticmethod
    def suite_manifest(repository: Path) -> dict:
        return json.loads(
            (repository / "skills/suite-manifest.json").read_text(
                encoding="utf-8"
            )
        )

    def test_release_package_excludes_agent_metadata_and_cache_artifacts(self):
        self.assertFalse(included(Path("skills/example/agents/openai.yaml")))
        self.assertFalse(included(Path("skills/example/__pycache__/helper.pyc")))
        self.assertFalse(included(Path("skills/example/._SKILL.md")))
        self.assertFalse(
            included(
                Path(
                    "skills/enterprise-panorama-analysis/scripts/pdf_two_pass.py"
                )
            )
        )
        self.assertFalse(
            included(
                Path(
                    "skills/enterprise-panorama-analysis/assets/brand-gold-10.png"
                )
            )
        )
        self.assertTrue(included(Path("skills/example/SKILL.md")))

    def test_release_gates_cover_startup_evolution_and_four_questions(self):
        repository = Path(__file__).resolve().parents[1]
        validate_release_source(repository)
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "release.zip"
            subprocess.run(
                [
                    sys.executable,
                    str(repository / "scripts" / "build_standard_package.py"),
                    "--root",
                    str(repository),
                    "--output",
                    str(package),
                ],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            )
            validate_release_archive(package)
            with zipfile.ZipFile(package) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                names = set(archive.namelist())
            suite_manifest = self.suite_manifest(repository)
            expected_skill_count = len(suite_manifest["skills"])
            self.assertEqual(
                manifest["version"],
                suite_manifest["release"]["version"],
            )
            self.assertEqual(manifest["includes"]["host_skill_install_prompt"], HOST_SKILL_INSTALL_PROMPT)
            self.assertTrue(manifest["includes"]["manufacturing_tax_risk_analysis"])
            self.assertTrue(manifest["includes"]["legal_regulations_dynamic_routing"])
            self.assertTrue(manifest["includes"]["personal_preference_overlay"])
            self.assertTrue(manifest["includes"]["cross_device_preference_sync"])
            self.assertTrue(manifest["includes"]["three_way_upgrade_inheritance"])
            self.assertTrue(manifest["includes"]["direct_skill_edit_detection"])
            self.assertTrue(manifest["includes"]["legacy_skill_preference_migration"])
            self.assertTrue(
                manifest["includes"]["manufacturing_tax_17_page_generator"]
            )
            self.assertTrue(manifest["includes"]["unified_branding_runtime"])
            self.assertTrue(manifest["includes"]["portable_path_gate"])
            self.assertTrue(manifest["includes"]["tax_report_e2e_gate"])
            self.assertFalse(manifest["includes"]["clean_container_gate"])
            self.assertEqual(
                len(manifest["official_skill_hashes"]),
                expected_skill_count,
            )
            self.assertEqual(
                set(manifest["portable_runtime_hashes"]),
                set(PORTABLE_REPORT_REQUIRED),
            )
            self.assertIn("skills/manufacturing-tax-risk-analysis/SKILL.md", names)
            self.assertIn("skills/jiaotang-legal-regulations/SKILL.md", names)
            self.assertIn("skills/standard-drafting/SKILL.md", names)
            for required_path in PORTABLE_REPORT_REQUIRED:
                self.assertIn(required_path, names)
            self.assertNotIn(
                "skills/enterprise-panorama-analysis/scripts/pdf_two_pass.py",
                names,
            )
            self.assertNotIn(
                "skills/enterprise-panorama-analysis/assets/brand-gold-10.png",
                names,
            )
            self.assertNotIn("skills/manufacturing-tax-risk-analysis/agents/openai.yaml", names)
            self.assertEqual(manifest["skill_count"], expected_skill_count)
            with tempfile.TemporaryDirectory() as install_directory:
                with zipfile.ZipFile(package) as install_archive:
                    install_archive.extractall(install_directory)
                installed = Path(install_directory)
                self.assertEqual(
                    len(list((installed / "skills").glob("*/SKILL.md"))),
                    expected_skill_count,
                )
                self.assertTrue((installed / "skills/first-run-configuration/SKILL.md").is_file())
                self.assertTrue((installed / "skills/local-knowledge-retrieval/SKILL.md").is_file())
                self.assertTrue((installed / "skills/skill-evolution/SKILL.md").is_file())
                self.assertTrue((installed / "skills/experience-recorder/SKILL.md").is_file())
                self.assertTrue((installed / "skills/first-run-configuration/scripts/migrate_skill_preferences.py").is_file())
                self.assertFalse(any((installed / "skills").glob("*/agents")))

    def test_install_and_upgrade_reuse_single_knowledge_mcp(self):
        repository = Path(__file__).resolve().parents[1]
        manifest = self.suite_manifest(repository)
        self.assertEqual(manifest["external_services"].count("jiaotang-kb"), 1)
        gate_names = {item["name"] for item in manifest["release_gates"]}
        self.assertIn("single-knowledge-mcp", gate_names)
        protocol = (
            repository
            / "skills/first-run-configuration/references/first-startup-protocol.md"
        ).read_text(encoding="utf-8")
        retrieval = (
            repository / "skills/local-knowledge-retrieval/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("只允许配置一个名为 `jiaotang-kb` 的 MCP", protocol)
        self.assertIn("不得新增知识库 MCP", protocol)
        self.assertIn("MCP `three_first_analysis`", retrieval)
        subprocess.run(
            [sys.executable, str(repository / "tests/validate_single_knowledge_mcp.py")],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_copy_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            skill = source / "sample-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: sample-skill\ndescription: test\n---\n", encoding="utf-8")
            destination = root / "destination"
            installed = install_skills(source, destination, "copy", False)
            self.assertEqual(installed, ["sample-skill"])
            self.assertTrue((destination / "sample-skill" / "SKILL.md").is_file())

    def test_existing_skill_requires_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            skill = source / "sample-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("first", encoding="utf-8")
            destination = root / "destination"
            install_skills(source, destination, "copy", False)
            (skill / "SKILL.md").write_text("second", encoding="utf-8")
            self.assertEqual(install_skills(source, destination, "copy", False), [])
            config_dir = root / "config"
            install_skills(source, destination, "copy", True, config_dir, "1.1")
            self.assertEqual((destination / "sample-skill" / "SKILL.md").read_text(encoding="utf-8"), "second")
            self.assertTrue(any((config_dir / "install-backups").glob("*/sample-skill/SKILL.md")))
            self.assertTrue(any((config_dir / "upgrade-reports").glob("*.json")))

    def test_direct_skill_edit_is_detected_and_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            skill = source / "sample-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("official-v1", encoding="utf-8")
            destination = root / "destination"
            config_dir = root / "config"
            install_skills(source, destination, "copy", True, config_dir, "1.0")
            (destination / "sample-skill/SKILL.md").write_text("personal-direct-edit", encoding="utf-8")
            (skill / "SKILL.md").write_text("official-v2", encoding="utf-8")
            install_skills(source, destination, "copy", True, config_dir, "2.0")
            report_path = sorted((config_dir / "upgrade-reports").glob("*.json"))[-1]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            item = report["items"][0]
            self.assertEqual(item["status"], "both-changed-conflict")
            self.assertEqual((destination / "sample-skill/SKILL.md").read_text(encoding="utf-8"), "official-v2")
            backup = Path(item["backup"])
            self.assertEqual((backup / "SKILL.md").read_text(encoding="utf-8"), "personal-direct-edit")

    def test_skill_change_classification(self):
        self.assertEqual(classify_skill_change("a", "a", "b"), "upstream-only")
        self.assertEqual(classify_skill_change("a", "c", "a"), "local-only")
        self.assertEqual(classify_skill_change("a", "c", "b"), "both-changed-conflict")

    def test_release_contains_standard_skills_and_valid_agent_metadata(self):
        repository = Path(__file__).resolve().parents[1]
        suite_manifest = self.suite_manifest(repository)
        self.assertEqual(
            sorted(
                path.parent.name
                for path in (repository / "skills").glob("*/SKILL.md")
            ),
            suite_manifest["skills"],
        )
        agent_metadata = list((repository / "skills").glob("*/agents/openai.yaml"))
        for metadata in agent_metadata:
            self.assertTrue((metadata.parent.parent / "SKILL.md").is_file())
            self.assertTrue(metadata.read_text(encoding="utf-8").strip())
        protocol = (
            repository
            / "skills/first-run-configuration/references/first-startup-protocol.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Agent", protocol)
        self.assertIn(HOST_SKILL_INSTALL_PROMPT, protocol)

    def test_standard_drafting_skill_has_rules_templates_and_audit(self):
        repository = Path(__file__).resolve().parents[1]
        skill = (repository / "skills/standard-drafting/SKILL.md").read_text(encoding="utf-8")
        rules = (
            repository / "skills/standard-drafting/references/gbt-1-1-drafting-rules.md"
        ).read_text(encoding="utf-8")
        self.assertIn("GB/T 1.1", skill)
        self.assertIn("要求—试验方法—判定规则对应矩阵", skill)
        self.assertIn("2026-01-08复审结论：继续有效", rules)
        self.assertTrue(
            (repository / "skills/standard-drafting/assets/standard-draft-template.md").is_file()
        )
        self.assertTrue(
            (repository / "skills/standard-drafting/scripts/audit_standard_draft.py").is_file()
        )
        router = (repository / "skills/project-task-router/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("路由 `standard-drafting`", router)

    def test_local_knowledge_retrieval_has_multi_path_gates(self):
        repository = Path(__file__).resolve().parents[1]
        skill = (repository / "skills/local-knowledge-retrieval/SKILL.md").read_text(
            encoding="utf-8"
        )
        protocol = (
            repository
            / "skills/local-knowledge-retrieval/references/search-orchestration.md"
        ).read_text(encoding="utf-8")
        self.assertIn("POST /v1/lists/search", skill)
        self.assertIn("public_list_search", skill)
        self.assertIn("knowledge_search", skill)
        self.assertIn("年份替换为认定批次", protocol)
        self.assertIn("不得通过企业名称判断登记城市", protocol)
        self.assertIn("不能据此判断资料不存在", protocol)
        self.assertIn(
            "未见复核通过，原称号需按当期通知作失效核验。还可能是更名、迁址或合并。",
            protocol,
        )
        self.assertIn("专精特新产业园", protocol)
        three_first = (
            repository
            / "skills/local-knowledge-retrieval/references/three-first-project-list-schema.md"
        ).read_text(encoding="utf-8")
        self.assertIn("同一企业同年多个产品必须保留多行", three_first)
        self.assertIn("首版次必须区分省级与市级", three_first)


if __name__ == "__main__":
    unittest.main()

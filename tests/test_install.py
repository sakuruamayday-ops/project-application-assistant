import json
import sys
import tempfile
import unittest
import subprocess
import zipfile
from pathlib import Path

from project_assistant.installer import install_skills
from scripts.build_standard_package import (
    HOST_SKILL_INSTALL_PROMPT,
    included,
    validate_release_archive,
    validate_release_source,
)


class InstallTests(unittest.TestCase):
    def test_release_package_excludes_agent_metadata_and_cache_artifacts(self):
        self.assertFalse(included(Path("skills/example/agents/openai.yaml")))
        self.assertFalse(included(Path("skills/example/__pycache__/helper.pyc")))
        self.assertFalse(included(Path("skills/example/._SKILL.md")))
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
                    "--version",
                    "9.9.9",
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
            self.assertEqual(manifest["includes"]["host_skill_install_prompt"], HOST_SKILL_INSTALL_PROMPT)
            self.assertTrue(manifest["includes"]["manufacturing_tax_risk_analysis"])
            self.assertTrue(manifest["includes"]["legal_regulations_dynamic_routing"])
            self.assertIn("skills/manufacturing-tax-risk-analysis/SKILL.md", names)
            self.assertIn("skills/jiaotang-legal-regulations/SKILL.md", names)
            self.assertNotIn("skills/manufacturing-tax-risk-analysis/agents/openai.yaml", names)
            self.assertEqual(manifest["skill_count"], 53)
            with tempfile.TemporaryDirectory() as install_directory:
                with zipfile.ZipFile(package) as install_archive:
                    install_archive.extractall(install_directory)
                installed = Path(install_directory)
                self.assertEqual(len(list((installed / "skills").glob("*/SKILL.md"))), 53)
                self.assertTrue((installed / "skills/first-run-configuration/SKILL.md").is_file())
                self.assertTrue((installed / "skills/local-knowledge-retrieval/SKILL.md").is_file())
                self.assertTrue((installed / "skills/skill-evolution/SKILL.md").is_file())
                self.assertTrue((installed / "skills/experience-recorder/SKILL.md").is_file())
                self.assertFalse(any((installed / "skills").glob("*/agents")))

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
            install_skills(source, destination, "copy", True)
            self.assertEqual((destination / "sample-skill" / "SKILL.md").read_text(encoding="utf-8"), "second")

    def test_release_contains_only_standard_skills(self):
        repository = Path(__file__).resolve().parents[1]
        self.assertEqual(len(list((repository / "skills").glob("*/SKILL.md"))), 53)
        self.assertFalse(any((repository / "skills").glob("*/agents/openai.yaml")))
        protocol = (
            repository
            / "skills/first-run-configuration/references/first-startup-protocol.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Agent", protocol)
        self.assertIn(HOST_SKILL_INSTALL_PROMPT, protocol)


if __name__ == "__main__":
    unittest.main()

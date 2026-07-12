import tempfile
import unittest
import subprocess
from pathlib import Path

from project_assistant.platforms import install_skills


class InstallTests(unittest.TestCase):
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

    def test_platform_install_scripts(self):
        repository = Path(__file__).resolve().parents[1]
        for platform in ("codex", "claude-code", "hermes"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                destination = temporary / "skills"
                guide = temporary / "FIRST_RUN.md"
                subprocess.run(
                    [
                        str(repository / "scripts" / f"install-{platform}.sh"),
                        "--target",
                        str(destination),
                        "--guide",
                        str(guide),
                    ],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(len(list(destination.iterdir())), 36)
                self.assertTrue(guide.is_file())
                self.assertIn("首次使用", guide.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

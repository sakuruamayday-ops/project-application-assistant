import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


RELEASE_MANAGER = (
    Path.home() / ".codex/skills/skill-release-manager/scripts"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


BRIDGE = load_module(
    "workbuddy_preference_bridge",
    RELEASE_MANAGER / "workbuddy_preference_bridge.py",
)
PACKAGER = load_module(
    "package_skill_release",
    RELEASE_MANAGER / "package_skill_release.py",
)


class WorkBuddyRuntimeHardeningTests(unittest.TestCase):
    def test_runtime_exception_degrades_but_integrity_error_blocks(self):
        options = Namespace(command="prompt", plugin_root="/tmp/plugin")
        with mock.patch.object(BRIDGE, "arguments", return_value=options):
            with mock.patch.object(
                BRIDGE,
                "data_directory",
                return_value=Path("/tmp/plugin-data"),
            ):
                with mock.patch.object(
                    BRIDGE,
                    "prompt_event",
                    side_effect=RuntimeError("状态缓存损坏"),
                ):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = BRIDGE.main()
                    payload = json.loads(output.getvalue())
                    self.assertEqual(code, 0)
                    self.assertTrue(payload["continue"])
                    self.assertIn("已降级", payload["systemMessage"])

                with mock.patch.object(
                    BRIDGE,
                    "prompt_event",
                    side_effect=BRIDGE.PluginIntegrityError(
                        "文件哈希不一致"
                    ),
                ):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = BRIDGE.main()
                    payload = json.loads(output.getvalue())
                    self.assertEqual(code, 2)
                    self.assertFalse(payload["continue"])

    def test_plugin_verification_cache_skips_repeated_signature_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            data_dir = Path(directory) / "data"
            root.mkdir()
            payload_path = root / "payload.txt"
            payload_path.write_text("verified", encoding="utf-8")
            manifest = {
                "files": {
                    "payload.txt": hashlib.sha256(
                        payload_path.read_bytes()
                    ).hexdigest()
                }
            }
            (root / "plugin-release-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            (root / "plugin-release-manifest.json.sig").write_bytes(b"sig")
            (root / "publisher-ed25519.pub").write_text(
                "ssh-ed25519 AAAATEST publisher",
                encoding="utf-8",
            )
            (root / "plugin-release-signature.json").write_text(
                json.dumps(
                    {
                        "signature_namespace": (
                            "codex-workbuddy-plugin-manifest"
                        )
                    }
                ),
                encoding="utf-8",
            )
            completed = Namespace(returncode=0, stdout=b"", stderr=b"")
            with mock.patch.object(
                BRIDGE.shutil,
                "which",
                return_value="/usr/bin/ssh-keygen",
            ):
                with mock.patch.object(
                    BRIDGE.subprocess,
                    "run",
                    return_value=completed,
                ) as signer:
                    first = BRIDGE.verify_plugin(
                        root,
                        data_dir=data_dir,
                        allow_cache=False,
                    )
                    self.assertEqual(first["verification"], "full")
                    self.assertEqual(signer.call_count, 1)
                with mock.patch.object(
                    BRIDGE.subprocess,
                    "run",
                    side_effect=AssertionError("不得重复调用验签进程"),
                ):
                    second = BRIDGE.verify_plugin(
                        root,
                        data_dir=data_dir,
                        allow_cache=True,
                    )
                    self.assertEqual(second["verification"], "cached")

    def test_workbuddy_copy_uses_shared_runtime_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample"
            destination = root / "plugin/skills/sample"
            (source / "scripts").mkdir(parents=True)
            (source / "references").mkdir()
            (source / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: sample",
                        "description: 示例",
                        "---",
                        "# 示例",
                        (
                            '!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/'
                            'portable_skill_runtime.py" prepare`'
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            for name in (
                "portable_skill_runtime.py",
                "verify_skill_installation.py",
            ):
                (source / "scripts" / name).write_text(
                    "print('duplicate')",
                    encoding="utf-8",
                )
            (source / "references/portable-runtime-protocol.md").write_text(
                "protocol",
                encoding="utf-8",
            )
            (source / "release-manifest.json").write_text(
                json.dumps(
                    {
                        "skill_name": "sample",
                        "release_tag": "V1.1",
                        "required_paths": [
                            "SKILL.md",
                            "scripts/portable_skill_runtime.py",
                            "scripts/verify_skill_installation.py",
                        ],
                        "mutable_paths": [],
                        "runtime_requirements": {},
                    }
                ),
                encoding="utf-8",
            )
            for name in (
                "release-manifest.json.sig",
                "release-signature.json",
                "publisher-ed25519.pub",
            ):
                (source / name).write_text("signed", encoding="utf-8")

            PACKAGER.copy_workbuddy_skill(source, destination)

            self.assertFalse(
                (destination / "scripts/portable_skill_runtime.py").exists()
            )
            self.assertFalse(
                (destination / "scripts/verify_skill_installation.py").exists()
            )
            text = (destination / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("${CODEBUDDY_PLUGIN_ROOT}/scripts/", text)
            manifest = json.loads(
                (destination / "release-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["integrity_mode"],
                "plugin-release-manifest",
            )
            self.assertEqual(manifest["required_paths"], ["SKILL.md"])

    def test_preference_migration_does_not_use_exec(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "skills/first-run-configuration/scripts/"
            "migrate_skill_preferences.py"
        )
        self.assertNotIn("exec(", script.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

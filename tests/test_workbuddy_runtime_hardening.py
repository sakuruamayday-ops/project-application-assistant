import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
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
sys.path.insert(0, str(RELEASE_MANAGER))
SUITE_PACKAGER = load_module(
    "package_workbuddy_suite",
    RELEASE_MANAGER / "package_workbuddy_suite.py",
)
WORKBUDDY_CLI = SUITE_PACKAGER.discover_workbuddy_cli() or Path(
    "/Applications/WorkBuddy.app/Contents/Resources/"
    "app.asar.unpacked/cli/bin/codebuddy"
)
SIGNING_KEY = (
    Path.home()
    / ".codex/skill-signing/jiaotang-skill-release-ed25519"
)
PUBLIC_KEY = SIGNING_KEY.with_suffix(".pub")


class WorkBuddyRuntimeHardeningTests(unittest.TestCase):
    def write_marketplace_fixture(
        self,
        root: Path,
        *,
        marketplace_name: str = "jiaotang-test",
        plugin_name: str = "jiaotang-test-skills",
        version: str = "1.2.3",
    ) -> Path:
        marketplace = root / marketplace_name
        plugin = marketplace / "plugins" / plugin_name
        (marketplace / ".codebuddy-plugin").mkdir(parents=True)
        (plugin / ".codebuddy-plugin").mkdir(parents=True)
        (marketplace / ".codebuddy-plugin/marketplace.json").write_text(
            json.dumps(
                {
                    "name": marketplace_name,
                    "description": "隔离安装回归测试市场",
                    "owner": {"name": "Jiaotang"},
                    "plugins": [
                        {
                            "name": plugin_name,
                            "description": "隔离安装回归测试插件",
                            "version": version,
                            "source": f"./plugins/{plugin_name}",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (plugin / ".codebuddy-plugin/plugin.json").write_text(
            json.dumps(
                {
                    "name": plugin_name,
                    "version": version,
                    "description": "隔离安装回归测试插件",
                    "author": {"name": "Jiaotang"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return marketplace

    @unittest.skipUnless(
        WORKBUDDY_CLI.is_file(),
        "当前主机未安装WorkBuddy，跳过真实宿主回归",
    )
    def test_real_marketplace_add_install_enable_uses_isolated_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marketplace = self.write_marketplace_fixture(root)
            result = SUITE_PACKAGER.run_host_install_regression(
                workbuddy_cli=WORKBUDDY_CLI,
                marketplace_root=marketplace,
                marketplace_name="jiaotang-test",
                plugin_name="jiaotang-test-skills",
                isolated_root=root / "isolated",
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(
                [item["name"] for item in result["commands"]],
                [
                    "validate-marketplace",
                    "validate-plugin",
                    "marketplace-add",
                    "plugin-install",
                    "plugin-enable",
                ],
            )
            settings = json.loads(
                (
                    root / "isolated/config/settings.json"
                ).read_text(encoding="utf-8")
            )
            self.assertTrue(
                settings["enabledPlugins"][
                    "jiaotang-test-skills@jiaotang-test"
                ]
            )

    @unittest.skipUnless(
        WORKBUDDY_CLI.is_file(),
        "当前主机未安装WorkBuddy，跳过一键安装器安全实测",
    )
    def test_one_click_installer_rejects_hash_mismatch_before_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            marketplace = self.write_marketplace_fixture(source)
            archive = root / "suite.zip"
            with zipfile.ZipFile(
                archive,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as bundle:
                for path in sorted(marketplace.rglob("*")):
                    if path.is_file():
                        bundle.write(
                            path,
                            (
                                Path("jiaotang-test")
                                / path.relative_to(marketplace)
                            ).as_posix(),
                        )
            installer = root / "install.command"
            installer.write_text(
                SUITE_PACKAGER.installer_script(
                    archive_name=archive.name,
                    marketplace_name="jiaotang-test",
                    plugin_name="jiaotang-test-skills",
                    release_version="1.2.3",
                    smoke_skill="enterprise-profile",
                    expected_archive_sha256="0" * 64,
                ),
                encoding="utf-8",
            )
            installer.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "CODEBUDDY_CONFIG_DIR": str(root / "config"),
                    "HOME": str(root / "home"),
                    "JIAOTANG_WORKBUDDY_INSTALL_ROOT": str(root / "installed"),
                    "DISABLE_AUTOUPDATER": "1",
                }
            )
            (root / "config").mkdir()
            (root / "home").mkdir()
            process = SUITE_PACKAGER.subprocess.run(
                ["/bin/zsh", str(installer), str(archive)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=120,
            )

            self.assertNotEqual(process.returncode, 0)
            self.assertIn(
                "发布包SHA-256不匹配",
                process.stdout + process.stderr,
            )
            self.assertFalse((root / "config/plugins").exists())

    def test_windows_installer_covers_discovery_safe_extract_and_trigger(self):
        script = SUITE_PACKAGER.windows_installer_script(
            archive_name="suite.zip",
            marketplace_name="jiaotang-test",
            plugin_name="jiaotang-test-skills",
            release_version="1.2.3",
            smoke_skill="enterprise-profile",
            expected_archive_sha256="a" * 64,
        )
        launcher = SUITE_PACKAGER.windows_launcher_script(
            "install-jiaotang-test.ps1"
        )

        self.assertIn("Get-WorkBuddyInstallLocations", script)
        self.assertIn("app.asar.unpacked\\cli\\bin\\codebuddy", script)
        self.assertIn("Expand-SafeZip", script)
        self.assertIn("ExternalAttributes", script)
        self.assertIn("COM[1-9]", script)
        self.assertIn("$unsafeWindowsPart", script)
        self.assertIn("Get-FileHash", script)
        self.assertIn('"--permission-mode", "dontAsk"', script)
        self.assertIn('"--tools", "Skill"', script)
        self.assertIn("active_skills", script)
        self.assertIn("enterprise-profile", script)
        self.assertIn("WorkBuddy透明安装计划", script)
        self.assertIn("不执行远程返回命令", script)
        self.assertIn("插件内含签名jiaotang-kb连接器", script)
        self.assertIn("Read-Host", script)
        self.assertIn("plugin marketplace remove", script)
        self.assertNotIn("Invoke-Expression", script)
        self.assertNotIn("ExecutionPolicy Bypass", script)
        self.assertNotIn("-ExecutionPolicy", launcher)
        self.assertIn("-NoProfile -File", launcher)

    def test_signed_plugin_embeds_mcp_connector_and_sensitive_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills_root = root / "skills"
            plugin_root = root / "plugin"
            source = skills_root / "_runtime/jiaotang-kb/jiaotang-agent.mjs"
            source.parent.mkdir(parents=True)
            source.write_text(
                "#!/usr/bin/env node\n// plugin-serve\n",
                encoding="utf-8",
            )
            (plugin_root / ".codebuddy-plugin").mkdir(parents=True)
            manifest = SUITE_PACKAGER.embed_workbuddy_mcp_connector(
                plugin_root=plugin_root,
                skills_root=skills_root,
                suite_manifest={
                    "workbuddy_plugin": {
                        "mcp_connector": {
                            "name": "jiaotang-kb",
                            "source": "_runtime/jiaotang-kb/jiaotang-agent.mjs",
                            "entry_command": "plugin-serve",
                            "bootstrap_option": "bootstrap_url",
                            "bootstrap_option_sensitive": True,
                        }
                    }
                },
            )

            self.assertEqual(manifest["mcpServers"], "./.mcp.json")
            self.assertTrue(
                manifest["userConfig"]["bootstrap_url"]["sensitive"]
            )
            mcp = json.loads(
                (plugin_root / ".mcp.json").read_text(encoding="utf-8")
            )
            server = mcp["mcpServers"]["jiaotang-kb"]
            self.assertEqual(
                server["command"],
                "${CODEBUDDY_PLUGIN_ROOT}/bin/run-node",
            )
            self.assertEqual(server["args"][-1], "plugin-serve")
            self.assertTrue((plugin_root / "bin/run-node").is_file())
            self.assertTrue((plugin_root / "bin/run-node.cmd").is_file())
            self.assertEqual(
                (plugin_root / "mcp/jiaotang-agent.mjs").read_bytes(),
                source.read_bytes(),
            )
            plugin_manifest = {
                "name": "jiaotang-mcp-regression",
                "version": "1.2.3",
                "description": "MCP清单回归",
                "author": {"name": "Jiaotang"},
                **manifest,
            }
            (plugin_root / ".codebuddy-plugin/plugin.json").write_text(
                json.dumps(plugin_manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            if WORKBUDDY_CLI.is_file():
                validation_command = [
                    str(WORKBUDDY_CLI),
                    "plugin",
                    "validate",
                    str(plugin_root),
                ]
                if (
                    os.name == "nt"
                    and WORKBUDDY_CLI.suffix.lower() in {".cmd", ".bat"}
                ):
                    validation_command = [
                        os.environ.get("COMSPEC", "cmd.exe"),
                        "/d",
                        "/s",
                        "/c",
                        *validation_command,
                    ]
                validated = subprocess.run(
                    validation_command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=90,
                )
                self.assertEqual(
                    validated.returncode,
                    0,
                    validated.stdout + validated.stderr,
                )

    def test_safe_extract_rejects_traversal_symlink_and_duplicates(self):
        cases = {
            "traversal.zip": [("../escape.txt", b"x", None)],
            "windows-traversal.zip": [(r"..\\escape.txt", b"x", None)],
            "symlink.zip": [("link", b"target", 0o120777 << 16)],
            "duplicate.zip": [
                ("same.txt", b"a", None),
                ("same.txt", b"b", None),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for archive_name, entries in cases.items():
                archive = root / archive_name
                with zipfile.ZipFile(archive, "w") as bundle:
                    for name, payload, attributes in entries:
                        info = zipfile.ZipInfo(name)
                        if attributes is not None:
                            info.create_system = 3
                            info.external_attr = attributes
                        bundle.writestr(info, payload)
                with self.subTest(archive=archive_name):
                    with self.assertRaises(RuntimeError):
                        SUITE_PACKAGER.safe_extract_zip(
                            archive,
                            root / f"extract-{archive.stem}",
                        )

    @unittest.skipUnless(
        WORKBUDDY_CLI.is_file()
        and SIGNING_KEY.is_file()
        and PUBLIC_KEY.is_file(),
        "当前主机缺少WorkBuddy或测试签名身份，跳过完整发布回归",
    )
    def test_packager_emits_signed_sidecar_and_runs_real_install_gate(self):
        source_skill = (
            Path(__file__).resolve().parents[1]
            / "skills/enterprise-profile"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills_root = root / "skills"
            output = root / "output"
            shutil.copytree(
                source_skill,
                skills_root / "enterprise-profile",
            )
            text = (
                skills_root / "enterprise-profile/SKILL.md"
            ).read_text(encoding="utf-8")
            references = sorted(
                set(
                    re.findall(
                        r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`",
                        text,
                    )
                )
                - {"enterprise-profile"}
            )
            (skills_root / "suite-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "product_name": "WorkBuddy发布回归",
                        "product_slug": "workbuddy-release-regression",
                        "install_mode": "bundle-only",
                        "release": {
                            "tag": "V9.9",
                            "version": "9.9.0",
                        },
                        "skills": ["enterprise-profile"],
                        "allowed_external_skills": references,
                        "external_services": [],
                        "ignored_reference_tokens": [],
                        "shared_paths": [],
                        "dependencies": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            options = Namespace(
                skills_root=str(skills_root),
                output_dir=str(output),
                release_tag="V9.9",
                signing_key=str(SIGNING_KEY),
                public_key=str(PUBLIC_KEY),
                plugin_name="jiaotang-regression-skills",
                marketplace_name="jiaotang-regression",
                workbuddy_cli=str(WORKBUDDY_CLI),
                smoke_skill="enterprise-profile",
            )
            stdout = io.StringIO()
            with mock.patch.object(
                SUITE_PACKAGER,
                "arguments",
                return_value=options,
            ):
                with contextlib.redirect_stdout(stdout):
                    returncode = SUITE_PACKAGER.main()

            self.assertEqual(returncode, 0, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(
                payload["download_regression"][
                    "host_install_regression"
                ]["status"],
                "pass",
            )
            self.assertEqual(
                payload["download_regression"][
                    "host_install_regression"
                ]["smoke_trigger"]["active_skills"],
                ["enterprise-profile"],
            )
            self.assertEqual(
                payload["download_regression"][
                    "host_install_regression"
                ]["smoke_trigger"]["status"],
                "pass",
            )
            archive = Path(payload["archive"])
            installer = Path(payload["installer"]["archive"])
            windows_installer = Path(
                payload["installers"]["windows"]["archive"]
            )
            windows_launcher = Path(
                payload["installers"]["windows_launcher"]["archive"]
            )
            self.assertTrue(archive.is_file())
            self.assertTrue(installer.is_file())
            self.assertTrue(windows_installer.is_file())
            self.assertTrue(windows_launcher.is_file())
            self.assertTrue(
                Path(payload["installer"]["signature"]).is_file()
            )
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                install_text = bundle.read(
                    "jiaotang-regression/INSTALL.md"
                ).decode("utf-8")
            self.assertIn(
                "jiaotang-regression/install-jiaotang-workbuddy.command",
                names,
            )
            self.assertIn(
                "jiaotang-regression/install-jiaotang-workbuddy.ps1",
                names,
            )
            self.assertIn(
                "jiaotang-regression/install-jiaotang-workbuddy.cmd",
                names,
            )
            self.assertIn("不能直接传ZIP", install_text)
            self.assertIn("真实调用enterprise-profile技能", install_text)
            self.assertIn(
                "plugin marketplace add <解压目录>/jiaotang-regression",
                install_text,
            )

            sidecar_environment = os.environ.copy()
            sidecar_environment.update(
                {
                    "CODEBUDDY_CONFIG_DIR": str(
                        root / "sidecar-config"
                    ),
                    "JIAOTANG_WORKBUDDY_INSTALL_ROOT": str(
                        root / "sidecar-install"
                    ),
                    "JIAOTANG_WORKBUDDY_INSTALL_CONFIRM": "INSTALL",
                    "DISABLE_AUTOUPDATER": "1",
                }
            )
            (root / "sidecar-config").mkdir()
            if os.name == "nt":
                sidecar_command = [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-File",
                    str(windows_installer),
                    "-ArchivePath",
                    str(archive),
                    "-CodeBuddyCli",
                    str(WORKBUDDY_CLI),
                    "-InstallRoot",
                    str(root / "sidecar-install"),
                ]
            else:
                sidecar_command = ["/bin/zsh", str(installer), str(archive)]
            sidecar_process = subprocess.run(
                sidecar_command,
                check=False,
                capture_output=True,
                text=True,
                env=sidecar_environment,
                timeout=180,
            )
            self.assertEqual(
                sidecar_process.returncode,
                0,
                sidecar_process.stdout + sidecar_process.stderr,
            )
            self.assertIn("enterprise-profile", sidecar_process.stdout)
            self.assertIn(
                "WorkBuddy透明安装计划",
                sidecar_process.stdout,
            )
            self.assertIn(
                "不执行远程返回命令",
                sidecar_process.stdout,
            )

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

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


RELEASE_MANAGER = Path(
    os.environ.get(
        "JIAOTANG_RELEASE_MANAGER_SCRIPTS",
        Path.home() / ".codex/skills/skill-release-manager/scripts",
    )
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

    def test_packager_has_no_external_installer_or_host_cli_api(self):
        for removed in (
            "discover_workbuddy_cli",
            "installer_script",
            "windows_installer_script",
            "windows_launcher_script",
            "write_windows_installer",
            "run_host_install_regression",
        ):
            self.assertFalse(
                hasattr(SUITE_PACKAGER, removed),
                f"已停用的外部安装接口仍可调用：{removed}",
            )

    @unittest.skipUnless(
        SIGNING_KEY.is_file() and PUBLIC_KEY.is_file(),
        "发布签名密钥不可用，跳过WorkBuddy市场包构建回归",
    )
    def test_packager_emits_only_cross_platform_marketplace_package(self):
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
            self.assertEqual(payload["fixed_installers"], [])
            self.assertEqual(
                payload["install_mode"],
                "workbuddy-in-app-local-marketplace",
            )
            self.assertEqual(
                payload["download_regression"][
                    "host_install_regression"
                ]["status"],
                "manual-in-app-required",
            )
            self.assertNotIn("installer", payload)
            self.assertNotIn("installers", payload)
            archive = Path(payload["archive"])
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                guide = bundle.read(
                    "jiaotang-regression/INSTALL.md"
                ).decode("utf-8")
            self.assertFalse(
                any(
                    name.endswith((".command", ".ps1"))
                    or (
                        name.endswith(".cmd")
                        and "/plugins/" not in name
                    )
                    for name in names
                )
            )
            self.assertIn("WorkBuddy 应用内完成", guide)
            self.assertIn("不需要退出", guide)
            self.assertIn("/plugin", guide)
            self.assertIn("plugins/marketplaces/jiaotang", guide)
            self.assertIn("不得直接注册临时下载", guide)
            self.assertIn("不得删除已注册的持久市场", guide)

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
                            "configuration_mode": (
                                "inline_plugin_manifest"
                            ),
                            "source": "_runtime/jiaotang-kb/jiaotang-agent.mjs",
                            "entry_command": "plugin-serve",
                            "bootstrap_option": "bootstrap_url",
                            "bootstrap_option_sensitive": True,
                        }
                    }
                },
            )

            self.assertEqual(
                manifest["mcpServers"],
                {
                    "jiaotang-kb": {
                        "command": (
                            "${CODEBUDDY_PLUGIN_ROOT}/bin/run-node"
                        ),
                        "args": [
                            (
                                "${CODEBUDDY_PLUGIN_ROOT}/mcp/"
                                "jiaotang-agent.mjs"
                            ),
                            "plugin-serve",
                        ],
                    }
                },
            )
            self.assertTrue(
                manifest["userConfig"]["bootstrap_url"]["sensitive"]
            )
            self.assertFalse((plugin_root / ".mcp.json").exists())
            server = manifest["mcpServers"]["jiaotang-kb"]
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

    def test_hook_json_transport_is_ascii_safe_on_windows(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            BRIDGE.hook_result(reason="缺少文件：.mcp.json")

        raw = output.getvalue()
        self.assertTrue(raw.isascii())
        payload = json.loads(raw)
        self.assertEqual(payload["reason"], "缺少文件：.mcp.json")

    def test_workbuddy_mcp_connector_has_only_one_packaged_runtime_copy(self):
        skills_root = Path(__file__).resolve().parents[1] / "skills"
        suite_manifest = json.loads(
            (skills_root / "suite-manifest.json").read_text(encoding="utf-8")
        )
        connector = suite_manifest["workbuddy_plugin"]["mcp_connector"]
        self.assertEqual(
            connector["configuration_mode"],
            "inline_plugin_manifest",
        )
        source = Path(connector["source"])

        self.assertTrue((skills_root / source).is_file())
        self.assertFalse(
            any(
                source == Path(shared) or source.is_relative_to(Path(shared))
                for shared in suite_manifest["shared_paths"]
            ),
            "MCP连接器已由打包器复制到mcp/，不得再作为shared_path重复入包",
        )

    def test_workbuddy_connector_matches_portal_installer_and_preserves_query(self):
        root = Path(__file__).resolve().parents[1]
        connector = root / "skills/_runtime/jiaotang-kb/jiaotang-agent.mjs"
        installer = (
            root
            / "services/knowledge-portal/installers/jiaotang-agent.mjs"
        )
        self.assertEqual(connector.read_bytes(), installer.read_bytes())
        script = "\n".join(
            (
                (
                    "import {appendUrlPath, expectedInstallerSha256} from "
                    f"{json.dumps(installer.as_uri())};"
                ),
                (
                    "const manifest = {installer_sha256: 'a'.repeat(64), "
                    "workbuddy_plugin: {connector_sha256: 'b'.repeat(64)}};"
                ),
                (
                    "if (expectedInstallerSha256(manifest, false) !== "
                    "'a'.repeat(64)) process.exit(1);"
                ),
                (
                    "if (expectedInstallerSha256(manifest, true) !== "
                    "'b'.repeat(64)) process.exit(1);"
                ),
                (
                    "const endpoint = appendUrlPath("
                    "'https://zshjiaotang.cn/v1/agent-bootstrap/jbe_test"
                    "?platform=unified', 'register');"
                ),
                (
                    "if (endpoint.toString() !== "
                    "'https://zshjiaotang.cn/v1/agent-bootstrap/jbe_test/"
                    "register?platform=unified') process.exit(1);"
                ),
            )
        )
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_source_use_license_is_packaged_but_not_rendered_on_website(self):
        root = Path(__file__).resolve().parents[1]
        skills_root = root / "skills"
        suite_manifest = json.loads(
            (skills_root / "suite-manifest.json").read_text(encoding="utf-8")
        )
        license_name = "SOURCE-USE-LICENSE.txt"
        protected_text = (
            "未经著作权人事先书面许可，不得用于客户交付、咨询服务、"
            "SaaS、产品集成、付费培训或其他直接、间接商业用途。"
        )

        self.assertIn(license_name, suite_manifest["shared_paths"])
        self.assertNotIn(license_name, suite_manifest["skills"])
        self.assertIn(
            protected_text,
            (skills_root / license_name).read_text(encoding="utf-8"),
        )
        website_source = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for directory in (
                root / "services/knowledge-portal/templates",
                root / "services/knowledge-portal/static",
            )
            for path in directory.rglob("*")
            if path.is_file()
        )
        self.assertNotIn(protected_text, website_source)

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

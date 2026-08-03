import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
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
REQUIRED_RELEASE_MANAGER_SCRIPTS = (
    "workbuddy_preference_bridge.py",
    "workbuddy_behavior_hook.py",
    "workbuddy_hook_macos.sh",
    "workbuddy_hook_windows.cmd",
    "package_skill_release.py",
    "package_workbuddy_suite.py",
)
if not all(
    (RELEASE_MANAGER / filename).is_file()
    for filename in REQUIRED_RELEASE_MANAGER_SCRIPTS
):
    raise unittest.SkipTest(
        "requires the separately installed skill-release-manager host integration"
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
BEHAVIOR = load_module(
    "workbuddy_behavior_hook",
    RELEASE_MANAGER / "workbuddy_behavior_hook.py",
)
REPOSITORY = Path(__file__).resolve().parents[1]
ADVERSARIAL_EVAL = load_module(
    "run_adversarial_eval",
    REPOSITORY / "tests/run_adversarial_eval.py",
)
ALL_SKILL_EVAL = load_module(
    "run_all_skill_activation_eval",
    REPOSITORY / "tests/run_all_skill_activation_eval.py",
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
    def test_packager_emits_windows_native_marketplace_package(self):
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
                platform="windows",
            )
            stdout = io.StringIO()

            @contextlib.contextmanager
            def isolated_release_workspace(prefix: str):
                workspace = root / "release-work" / prefix
                workspace.mkdir(parents=True, exist_ok=False)
                yield workspace

            with mock.patch.object(
                SUITE_PACKAGER,
                "arguments",
                return_value=options,
            ), mock.patch.object(
                SUITE_PACKAGER,
                "recoverable_workspace",
                isolated_release_workspace,
            ):
                with contextlib.redirect_stdout(stdout):
                    returncode = SUITE_PACKAGER.main()

            self.assertEqual(returncode, 0, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["fixed_installers"], [])
            self.assertEqual(
                payload["install_mode"],
                "one-copy-workbuddy-prompt",
            )
            self.assertEqual(
                payload["download_regression"][
                    "host_install_regression"
                ]["status"],
                "prompt-driven-installation-required",
            )
            self.assertNotIn("installer", payload)
            self.assertNotIn("installers", payload)
            self.assertEqual(payload["platform"], "windows")
            archive = Path(payload["archive"])
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                guide = bundle.read(
                    "jiaotang-regression/INSTALL.md"
                ).decode("utf-8")
                skill_entry = bundle.read(
                    "jiaotang-regression/plugins/jiaotang-regression-skills/"
                    "skills/enterprise-profile/SKILL.md"
                ).decode("utf-8")
                hooks = bundle.read(
                    "jiaotang-regression/plugins/jiaotang-regression-skills/"
                    "hooks/hooks.json"
                ).decode("utf-8")
            self.assertFalse(
                any(
                    name.endswith((".command", ".ps1"))
                    for name in names
                )
            )
            self.assertFalse(
                any(
                    name.endswith(".sh")
                    and not name.endswith("/scripts/workbuddy_hook_windows.sh")
                    for name in names
                )
            )
            self.assertTrue(
                any(name.endswith("/scripts/workbuddy_hook_windows.cmd") for name in names)
            )
            self.assertTrue(
                any(name.endswith("/scripts/workbuddy_hook_windows.sh") for name in names)
            )
            self.assertIn("workbuddy_hook_windows.sh", hooks)
            self.assertNotIn("cmd.exe /d /s /c", hooks.casefold())
            self.assertIn("WorkBuddy 应用内完成", guide)
            self.assertIn("/plugin", guide)
            self.assertIn("plugins/marketplaces/jiaotang", guide)
            self.assertIn("不得直接注册临时下载", guide)
            self.assertIn("不得删除已注册的持久市场", guide)
            self.assertIn("只替换用户配置中的 `mcpServers.jiaotang-kb`", guide)
            self.assertIn("保留其他 MCP 条目", guide)
            self.assertIn("重载 WorkBuddy 一次", guide)
            self.assertIn("connected: true", guide)
            self.assertTrue(skill_entry.startswith("---\nname: enterprise-profile\n"))
            self.assertGreater(
                skill_entry.index("<!-- BEGIN WORKBUDDY BEHAVIOR HOOK -->"),
                skill_entry.index("\n---\n"),
            )
            self.assertIn("os.path.expanduser('~')", skill_entry)
            self.assertIn("'.workbuddy'", skill_entry)
            self.assertIn("'.codebuddy'", skill_entry)
            self.assertIn("os.path.join", skill_entry)
            self.assertNotIn("/Users/", skill_entry)
            self.assertNotRegex(skill_entry, r"[A-Za-z]:\\\\Users\\\\")

    def test_behavior_hook_uses_signals_and_blocks_unrouted_formal_delivery(self):
        contract = json.loads(
            (REPOSITORY / "skills/delivery-contracts.json").read_text(
                encoding="utf-8"
            )
        )
        signals = BEHAVIOR.prompt_signals(
            "请按现行政策形成报告并交付文件。", contract
        )

        self.assertTrue(signals["formal_business_delivery"])
        self.assertTrue(signals["business_domain"])
        self.assertEqual(
            BEHAVIOR.audit_delivery_completion(
                prompt="",
                answer="已经完成。",
                active_skills=[],
                contract=contract,
                signals=signals,
            ),
            [
                "NO_PRIMARY_BUSINESS_SKILL：正式业务交付未激活主业务Skill；"
                "辅助Skill和质量闸门不能替代主业务Skill"
            ],
        )
        self.assertEqual(
            BEHAVIOR.audit_delivery_completion(
                prompt="解释一下今天的安排。",
                answer="说明如下。",
                active_skills=[],
                contract=contract,
            ),
            [],
        )

    def test_behavior_hook_formal_delivery_negation_and_policy_qa_regressions(self):
        contract = json.loads(
            (REPOSITORY / "skills/delivery-contracts.json").read_text(
                encoding="utf-8"
            )
        )

        negated = BEHAVIOR.prompt_signals(
            "不要生成报告，只解释申报条件",
            contract,
        )
        self.assertFalse(negated["formal_business_delivery"])
        self.assertEqual(
            BEHAVIOR.audit_delivery_completion(
                prompt="",
                answer="这里只解释通常条件。",
                active_skills=[{"skill": "policy-retrieval"}],
                contract=contract,
                signals=negated,
            ),
            [],
        )

        simple_policy = BEHAVIOR.prompt_signals("简单解释申报条件", contract)
        self.assertFalse(simple_policy["formal_business_delivery"])
        self.assertEqual(
            BEHAVIOR.audit_delivery_completion(
                prompt="",
                answer="申报条件通常包括主体、门槛和排除项。",
                active_skills=[{"skill": "policy-retrieval"}],
                contract=contract,
                signals=simple_policy,
            ),
            [],
        )

        no_primary = BEHAVIOR.audit_delivery_receipt(
            prompt="请生成政府项目报告",
            answer="已经生成。",
            active_skills=[{"skill": "consistency-check"}],
            contract=contract,
        )
        self.assertEqual(no_primary["error_code"], "NO_PRIMARY_BUSINESS_SKILL")

        missing_template = BEHAVIOR.audit_delivery_receipt(
            prompt="请生成政府项目可行性报告",
            answer="总体结论：可申报。",
            active_skills=[{"skill": "project-feasibility"}],
            contract=contract,
        )
        self.assertFalse(missing_template["delivery_check_ok"])
        self.assertIn(
            "skills.project-feasibility.7",
            missing_template["missing_requirement_ids"],
        )

    def test_behavior_hook_requires_primary_role_and_classifies_all_49_skills(self):
        contract = json.loads(
            (REPOSITORY / "skills/delivery-contracts.json").read_text(
                encoding="utf-8"
            )
        )
        suite = json.loads(
            (REPOSITORY / "skills/suite-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        roles = contract["skill_roles"]
        self.assertEqual(set(roles), set(suite["skills"]))
        self.assertEqual(
            {
                str(definition.get("role") or "")
                for definition in roles.values()
            },
            {
                "primary_business",
                "supporting_business",
                "quality_gate",
                "infrastructure",
            },
        )

        signals = BEHAVIOR.prompt_signals(
            "请按现行政策形成报告并交付文件。", contract
        )
        quality_only = BEHAVIOR.audit_delivery_receipt(
            prompt="",
            answer="已经完成。",
            active_skills=[{"skill": "consistency-check"}],
            contract=contract,
            signals=signals,
        )
        self.assertFalse(quality_only["delivery_check_ok"])
        self.assertEqual(
            quality_only["error_code"], "NO_PRIMARY_BUSINESS_SKILL"
        )
        self.assertEqual(
            quality_only["quality_gate_skills"], ["consistency-check"]
        )

        supporting_only = BEHAVIOR.audit_delivery_receipt(
            prompt="",
            answer="已经完成。",
            active_skills=[{"skill": "policy-retrieval"}],
            contract=contract,
            signals=signals,
        )
        self.assertFalse(supporting_only["delivery_check_ok"])
        self.assertEqual(
            supporting_only["error_code"], "NO_PRIMARY_BUSINESS_SKILL"
        )

        primary = BEHAVIOR.audit_delivery_receipt(
            prompt="",
            answer="已经完成。",
            active_skills=[{"skill": "application-writing"}],
            contract=contract,
            signals=signals,
        )
        self.assertTrue(primary["delivery_check_ok"])
        self.assertEqual(
            primary["primary_business_skills"], ["application-writing"]
        )

    def test_behavior_hook_rejects_na_and_negative_completion_markers(self):
        contract = {
            "formal_business_delivery_markers": ["形成报告"],
            "business_domain_markers": ["政策"],
            "skill_roles": {
                "sample-primary": {
                    "role": "primary_business",
                    "owns": ["sample-report"],
                }
            },
            "skills": {
                "sample-primary": {
                    "applies_when_prompt_contains": ["专项"],
                    "required_marker_groups": [
                        ["交付PDF"],
                        ["品牌审计通过"],
                    ],
                }
            },
        }
        receipt = BEHAVIOR.audit_delivery_receipt(
            prompt="请按政策形成报告并完成专项交付。",
            answer="N/A：未生成交付PDF；未运行品牌审计通过。",
            active_skills=[{"skill": "sample-primary"}],
            contract=contract,
        )
        self.assertFalse(receipt["delivery_check_ok"])
        self.assertEqual(
            receipt["missing_requirement_ids"],
            ["skills.sample-primary.1", "skills.sample-primary.2"],
        )
        self.assertEqual(receipt["accepted_na_items"], [])

    def test_behavior_stop_returns_machine_readable_success_receipt(self):
        contract_path = REPOSITORY / "skills/delivery-contracts.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_root = root / "plugin"
            data_root = root / "behavior"
            plugin_root.mkdir()
            (plugin_root / "delivery-contracts.json").write_bytes(
                contract_path.read_bytes()
            )
            state_path, _ = BEHAVIOR.state_paths(data_root, "session-success")
            BEHAVIOR.atomic_json(
                state_path,
                {
                    "schema_version": 3,
                    "session_id": "session-success",
                    "turn_id": "turn-success",
                    "state_origin": "user_prompt_submit",
                    "prompt_context_ok": True,
                    "prompt_sha256": "abc",
                    "prompt_signals": {
                        "formal_business_delivery": True,
                        "business_domain": True,
                        "complex_task": False,
                        "policy_task": False,
                        "peer_task": False,
                        "skill_applicability": {},
                    },
                    "active_skills": [
                        {"skill": "application-writing"},
                        {"skill": "consistency-check"},
                    ],
                    "status": "pending",
                },
            )
            output = io.StringIO()
            with mock.patch.object(
                BEHAVIOR,
                "read_stdin",
                return_value={
                    "session_id": "session-success",
                    "last_assistant_message": "正式材料已经完成。",
                },
            ), contextlib.redirect_stdout(output):
                self.assertEqual(
                    BEHAVIOR.stop_event(
                        data_root,
                        plugin_root,
                        "workbuddy-marketplace",
                        "workbuddy-macos",
                    ),
                    0,
                )

            receipt = json.loads(output.getvalue())
            self.assertTrue(receipt["delivery_check_ok"])
            self.assertEqual(
                receipt["primary_business_skills"], ["application-writing"]
            )
            self.assertEqual(
                receipt["quality_gate_skills"], ["consistency-check"]
            )
            self.assertEqual(receipt["missing_requirement_ids"], [])
            self.assertEqual(
                BEHAVIOR.load_state(state_path)["status"], "completed"
            )

    def test_delivery_contract_uses_specific_not_generic_trigger_markers(self):
        contract = json.loads(
            (REPOSITORY / "skills/delivery-contracts.json").read_text(
                encoding="utf-8"
            )
        )
        forbidden = {"报告", "分析", "材料", "比较"}
        for skill, specification in contract["skills"].items():
            with self.subTest(skill=skill):
                markers = set(specification["applies_when_prompt_contains"])
                self.assertFalse(markers & forbidden)

    def test_simplified_plugin_uses_user_remote_mcp_without_local_connector(self):
        suite_manifest = json.loads(
            (REPOSITORY / "skills/suite-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        plugin = suite_manifest["workbuddy_plugin"]
        self.assertEqual(plugin["hook_mode"], "behavior_only_fail_open")
        self.assertEqual(
            plugin["mcp_configuration_mode"],
            "user_remote_streamable_http",
        )
        self.assertNotIn("mcp_connector", plugin)
        self.assertFalse(
            hasattr(SUITE_PACKAGER, "embed_workbuddy_mcp_connector")
        )

    def test_hook_json_transport_is_ascii_safe_on_windows(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            BRIDGE.hook_result(reason="缺少文件：.mcp.json")

        raw = output.getvalue()
        self.assertTrue(raw.isascii())
        payload = json.loads(raw)
        self.assertEqual(payload["reason"], "缺少文件：.mcp.json")

    def test_delivery_contract_blocks_omitted_policy_peer_and_four_question_parts(self):
        contract = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "skills/delivery-contracts.json"
            ).read_text(encoding="utf-8")
        )
        missing = BRIDGE.audit_delivery_completion(
            prompt="请形成企业全景分析报告，核对政策并做同行对标。",
            answer="总体结论：企业可以继续准备。",
            active_skills=[
                {"skill": "project-application-assistant"},
                {"skill": "enterprise-panorama-analysis"},
            ],
            contract=contract,
        )

        self.assertTrue(any("四问复盘缺项" in item for item in missing))
        self.assertTrue(any("政策选择缺项" in item for item in missing))
        self.assertTrue(any("同行对比缺项" in item for item in missing))
        self.assertTrue(
            any("enterprise-panorama-analysis模板缺项" in item for item in missing)
        )

    def test_delivery_contract_accepts_complete_workbuddy_answer(self):
        contract = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "skills/delivery-contracts.json"
            ).read_text(encoding="utf-8")
        )
        answer = """
        完成结果与结论：已形成企业全景分析。
        报告版本：B深度顾问版。企业主体与工商信息已经锚定。
        共同事实底稿中的事实数据与判断建议分开列示。
        政策选择与适用版本：以现行管理办法和当期年度通知为依据；
        当期通知尚未命中的字段保持未知，来源均回指政府官网官方原文。
        同行对比与同行项目对比表：选择官方公示名单中的可比企业，按技术和市场比较维度
        给出可比性评分；同时列明口径差异、不可比较项和数据缺口。
        风险与下一步行动已进入90天整改表，可申报项目矩阵和五年规划表均已生成。
        来源清单和证据台账已经绑定；professional_report_pdf交付PDF
        已通过金色居中水印审计通过。
        最没有把握：同行未公开指标。
        最大遗漏：企业研发台账尚未取得。
        最有价值的创新改进：增加政策变化影响模拟器。
        提高本次任务效率：复用政策内容哈希。
        """
        missing = BRIDGE.audit_delivery_completion(
            prompt="请形成企业全景分析报告，核对政策并做同行对标。",
            answer=answer,
            active_skills=[
                {"skill": "project-application-assistant"},
                {"skill": "enterprise-panorama-analysis"},
            ],
            contract=contract,
        )

        self.assertEqual(missing, [])

    def test_delivery_contract_covers_report_branding_tables_and_artifacts(self):
        contract = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "skills/delivery-contracts.json"
            ).read_text(encoding="utf-8")
        )
        scenarios = {
            "enterprise-panorama-analysis": (
                "请生成专业版企业全景分析报告。",
                ("同行项目对比表", "交付PDF", "水印审计"),
            ),
            "manufacturing-tax-risk-analysis": (
                "请生成金税四期分析报告。",
                ("财务总览", "四项交付产物", "居中金色水印"),
            ),
            "sme-score-preassessment": (
                "请生成专精特新前期预评估报告。",
                ("2026质量评价输入清单", "平台质量分状态", "四项独立判断"),
            ),
            "sme-development-projects": (
                "请生成专精特新后期体检报告。",
                ("四项独立判断表", "validate_sme_assessment.py", "报告水印"),
            ),
        }

        for skill_name, (prompt, expected_markers) in scenarios.items():
            with self.subTest(skill=skill_name):
                missing = BRIDGE.audit_delivery_completion(
                    prompt=prompt,
                    answer="总体结论：已完成。",
                    active_skills=[{"skill": skill_name}],
                    contract=contract,
                )
                joined = "；".join(missing)
                for marker in expected_markers:
                    self.assertIn(marker, joined)

    def test_patent_full_case_contract_blocks_missing_case_chain(self):
        contract = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "skills/delivery-contracts.json"
            ).read_text(encoding="utf-8")
        )
        missing = BRIDGE.audit_delivery_completion(
            prompt="请撰写专利并形成完整申请文件。",
            answer="申请文件已经完成。",
            active_skills=[{"skill": "jiaotang-patent-router"}],
            contract=contract,
        )
        joined = "；".join(missing)

        self.assertIn("全案唯一清单", joined)
        self.assertIn("权利要求现有技术矩阵", joined)
        self.assertIn("核稿验证", joined)
        self.assertIn("提交清单", joined)

    def test_stop_hook_keeps_blocking_after_repeated_quality_failures(self):
        contract_path = (
            Path(__file__).resolve().parents[1]
            / "skills/delivery-contracts.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_root = root / "plugin"
            data_dir = root / "data"
            plugin_root.mkdir()
            (plugin_root / "delivery-contracts.json").write_bytes(
                contract_path.read_bytes()
            )
            state_path, _ = BRIDGE.state_paths(data_dir, "session-quality")
            BRIDGE.atomic_json(
                state_path,
                {
                    "status": "active",
                    "prompt": "请形成企业全景分析报告，核对政策并做同行对标。",
                    "active_skills": [
                        {"skill": "project-application-assistant"},
                        {"skill": "enterprise-panorama-analysis"},
                    ],
                },
            )
            payload = {
                "session_id": "session-quality",
                "last_assistant_message": "总体结论：企业可以继续准备。",
            }

            for attempt in range(1, 5):
                output = io.StringIO()
                with mock.patch.object(
                    BRIDGE,
                    "verify_plugin",
                    return_value={"status": "pass"},
                ):
                    with mock.patch.object(
                        BRIDGE,
                        "read_stdin",
                        return_value=payload,
                    ):
                        with contextlib.redirect_stdout(output):
                            code = BRIDGE.stop_event(data_dir, plugin_root)
                result = json.loads(output.getvalue())
                self.assertEqual(code, 2)
                self.assertIn(f"第{attempt}次校验", result["reason"])

            state = BRIDGE.load_state(state_path)
            self.assertEqual(state["quality_retry_count"], 4)
            self.assertEqual(state["status"], "quality-blocked")

    def test_workbuddy_package_declares_no_local_mcp_runtime(self):
        skills_root = Path(__file__).resolve().parents[1] / "skills"
        suite_manifest = json.loads(
            (skills_root / "suite-manifest.json").read_text(encoding="utf-8")
        )
        plugin = suite_manifest["workbuddy_plugin"]
        self.assertEqual(
            plugin["mcp_configuration_mode"],
            "user_remote_streamable_http",
        )
        self.assertNotIn("mcp_connector", plugin)
        self.assertFalse(
            any("jiaotang-kb" in Path(shared).parts for shared in suite_manifest["shared_paths"])
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

    def test_unbound_workbuddy_plugin_exposes_local_setup_tools(self):
        root = Path(__file__).resolve().parents[1]
        connector = root / "skills/_runtime/jiaotang-kb/jiaotang-agent.mjs"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            credential_file = temporary / "missing-credential"
            plugin_data = temporary / "plugin-data"
            requests = "\n".join(
                json.dumps(payload)
                for payload in (
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "workbuddy-regression",
                                "version": "1.0.0",
                            },
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "jiaotang_kb_setup_status",
                            "arguments": {},
                        },
                    },
                )
            )
            completed = subprocess.run(
                [
                    "node",
                    str(connector),
                    "plugin-serve",
                    "--platform",
                    "darwin",
                    "--home",
                    str(temporary),
                ],
                input=f"{requests}\n",
                capture_output=True,
                check=False,
                text=True,
                env={
                    **os.environ,
                    "JIAOTANG_ENABLE_TEST_CREDENTIAL_FILE": "1",
                    "JIAOTANG_TEST_CREDENTIAL_FILE": str(credential_file),
                    "CODEBUDDY_PLUGIN_DATA": str(plugin_data),
                },
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        responses = {
            payload["id"]: payload
            for line in completed.stdout.splitlines()
            if line.strip()
            for payload in [json.loads(line)]
            if "id" in payload
        }
        self.assertEqual(responses[1]["result"]["serverInfo"]["name"], "jiaotang-kb")
        tools = {
            item["name"] for item in responses[2]["result"]["tools"]
        }
        self.assertEqual(
            tools,
            {"jiaotang_kb_setup", "jiaotang_kb_setup_status"},
        )
        status = responses[3]["result"]["structuredContent"]
        self.assertEqual(status["status"], "setup_required")
        self.assertFalse(status["configured"])
        self.assertNotIn("jbe_", completed.stdout)
        self.assertNotIn("jtk_", completed.stdout)

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

    def test_real_host_gate_extractors_reject_cross_platform_zip_attacks(self):
        cases = {
            "backslash.zip": [(r"folder\\escape.txt", b"x", None)],
            "drive.zip": [("C:/escape.txt", b"x", None)],
            "colon.zip": [("folder/stream:ads", b"x", None)],
            "symlink.zip": [
                (
                    "plugin/link",
                    b"target",
                    (stat.S_IFLNK | 0o777) << 16,
                )
            ],
            "duplicate.zip": [
                ("plugin/same.txt", b"a", None),
                ("plugin/same.txt", b"b", None),
            ],
            "case-collision.zip": [
                ("plugin/SKILL.md", b"a", None),
                ("plugin/skill.md", b"b", None),
            ],
        }
        extractors = {
            "adversarial": lambda archive, destination: (
                ADVERSARIAL_EVAL.extract_plugin(archive, destination)
            ),
            "all-skills": ALL_SKILL_EVAL.safe_extract,
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
                for extractor_name, extractor in extractors.items():
                    with self.subTest(
                        archive=archive_name,
                        extractor=extractor_name,
                    ):
                        with self.assertRaisesRegex(
                            RuntimeError,
                            "不安全|重复",
                        ):
                            extractor(
                                archive,
                                root
                                / f"{archive.stem}-{extractor_name}",
                            )

    def test_adversarial_gate_workspace_honors_release_work_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.dict(
                os.environ,
                {"JIAOTANG_RELEASE_WORK_ROOT": str(root)},
            ):
                workspace = ADVERSARIAL_EVAL.recoverable_workspace(
                    "adversarial-"
                )
            self.assertEqual(workspace.parent, root.resolve())
            self.assertTrue(workspace.is_dir())

    def test_adversarial_gate_prompt_is_bounded_route_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = Namespace(
                stdout=(
                    'ROUTE_JSON: {"primary_skill":"policy-retrieval",'
                    '"activated_skills":["policy-retrieval"],'
                    '"clarification_required":false,'
                    '"policy_status":"stale","claims_limited":true}\n'
                ),
                stderr="",
                returncode=0,
            )
            with mock.patch.object(
                ADVERSARIAL_EVAL.subprocess,
                "run",
                return_value=completed,
            ) as runner:
                result = ADVERSARIAL_EVAL.run_case(
                    item={
                        "case_id": "ADV-TEST",
                        "category": "stale-policy",
                        "prompt": "只核验已截止政策的效力。",
                    },
                    expected={
                        "expected_primary_skill": "policy-retrieval",
                        "required_skills": ["policy-retrieval"],
                        "forbidden_skills": ["project-feasibility"],
                        "clarification_required": False,
                        "category": "stale-policy",
                    },
                    output=root,
                    plugin_root=root / "plugin",
                    codebuddy_cli="/tmp/codebuddy",
                    max_turns=6,
                    timeout_seconds=120,
                )
            prompt = runner.call_args.args[0][2]
            self.assertIn("只输出下面格式的一行", prompt)
            self.assertIn("不要输出解释、标题、表格或建议", prompt)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(
                result["effective_primary_skill"],
                "policy-retrieval",
            )

    def test_stale_policy_competitors_defer_to_policy_retrieval(self):
        competitors = (
            "agriculture-and-rural-projects",
            "digitalization-projects",
            "green-development-projects",
            "intellectual-property-projects",
            "investment-subsidy-projects",
            "peer-benchmarking",
            "quality-brand-projects",
            "regional-special-projects",
            "talent-projects",
            "technology-innovation-projects",
            "trade-and-open-economy-projects",
        )
        expected = (
            "若只核验旧通知、政策版本、效力或完整文件链，"
            "本技能不适用，必须以policy-retrieval为主技能"
        )
        for skill in competitors:
            with self.subTest(skill=skill):
                source = (
                    REPOSITORY / "skills" / skill / "SKILL.md"
                ).read_text(encoding="utf-8")
                self.assertIn(expected, source)

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

    def test_plugin_verification_cache_never_replaces_signature_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            data_dir = Path(directory) / "data"
            root.mkdir()
            payload_path = root / "payload.txt"
            payload_path.write_text("verified", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "artifact_type": "workbuddy-plugin",
                "plugin_name": "cache-fixture",
                "integrity_excludes": list(
                    BRIDGE.PLUGIN_INTEGRITY_COMPANIONS
                ),
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
                        "algorithm": "OpenSSH-Ed25519",
                        "signature_namespace": (
                            "codex-workbuddy-plugin-manifest"
                        ),
                        "signed_file": "plugin-release-manifest.json",
                        "signature": "plugin-release-manifest.json.sig",
                        "public_key": "publisher-ed25519.pub",
                        "public_key_fingerprint": (
                            BRIDGE.OFFICIAL_PUBLISHER_FINGERPRINT
                        ),
                    }
                ),
                encoding="utf-8",
            )
            fingerprint = Namespace(
                returncode=0,
                stdout=(
                    "256 "
                    + BRIDGE.OFFICIAL_PUBLISHER_FINGERPRINT
                    + " publisher (ED25519)\n"
                ),
                stderr="",
            )
            verified = Namespace(returncode=0, stdout=b"", stderr=b"")
            with mock.patch.object(
                BRIDGE.shutil,
                "which",
                return_value="/usr/bin/ssh-keygen",
            ):
                with mock.patch.object(
                    BRIDGE.subprocess,
                    "run",
                    side_effect=[fingerprint, verified],
                ) as signer:
                    first = BRIDGE.verify_plugin(
                        root,
                        data_dir=data_dir,
                        allow_cache=False,
                    )
                    self.assertEqual(first["verification"], "full")
                    self.assertEqual(signer.call_count, 2)
                with mock.patch.object(
                    BRIDGE.subprocess,
                    "run",
                    side_effect=[fingerprint, verified],
                ) as signer:
                    second = BRIDGE.verify_plugin(
                        root,
                        data_dir=data_dir,
                        allow_cache=True,
                    )
                    self.assertEqual(
                        second["verification"],
                        "full-content-cache-hit",
                    )
                    self.assertEqual(signer.call_count, 2)

    def test_workbuddy_copy_strips_portable_runtime_and_adds_minimal_hook(self):
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
                        "<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->",
                        (
                            '!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/'
                            'portable_skill_runtime.py" prepare`'
                        ),
                        "<!-- END MANAGED PORTABLE SKILL RUNTIME -->",
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
            self.assertIn("BEGIN WORKBUDDY BEHAVIOR HOOK", text)
            self.assertIn("workbuddy_behavior_hook.py", text)
            self.assertIn("CODEBUDDY_PLUGIN_ROOT", text)
            self.assertIn("activation_ok", text)
            self.assertNotIn("portable_skill_runtime.py", text)
            self.assertFalse(
                (destination / "release-manifest.json").exists()
            )
            self.assertFalse(
                (destination / "release-manifest.json.sig").exists()
            )

    def test_workbuddy_activation_uses_plugin_root_and_confirms_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_root = root / "plugin"
            skill_root = plugin_root / "skills" / "policy-retrieval"
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                "---\nname: policy-retrieval\ndescription: test\n---\n",
                encoding="utf-8",
            )
            data_root = root / "behavior"
            data_root.mkdir()
            (data_root / "current-turn.json").write_text(
                json.dumps(
                    {
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                    }
                ),
                encoding="utf-8",
            )
            state_path, _ = BEHAVIOR.state_paths(data_root, "session-1")
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "state_origin": "user_prompt_submit",
                        "prompt_context_ok": True,
                        "prompt_sha256": "abc",
                        "prompt_signals": {},
                        "active_skills": [],
                        "status": "pending",
                    }
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = BEHAVIOR.activate(
                    data_root,
                    plugin_root,
                    "",
                    "policy-retrieval",
                    Path(""),
                )

            self.assertEqual(result, 0)
            receipt = json.loads(output.getvalue())
            self.assertTrue(receipt["activation_ok"])
            self.assertEqual(receipt["skill"], "policy-retrieval")
            self.assertEqual(receipt["turn_id"], "turn-1")
            self.assertEqual(receipt["root_source"], "direct")
            self.assertTrue(receipt["state_persisted"])
            self.assertEqual(
                receipt["active_skills_after"],
                ["policy-retrieval"],
            )
            self.assertEqual(receipt["active_skill_count"], 1)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [item["skill"] for item in state["active_skills"]],
                ["policy-retrieval"],
            )

    def test_generated_activation_runner_discovers_default_marketplace_layouts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for home_name, storage, expected_source in (
                ("home-workbuddy", ".workbuddy", "workbuddy-marketplace"),
                ("home-codebuddy", ".codebuddy", "codebuddy-marketplace"),
            ):
                with self.subTest(storage=storage):
                    home = root / home_name
                    plugin_root = (
                        home
                        / storage
                        / "plugins/marketplaces/jiaotang/plugins/plugin"
                    )
                    source = root / f"source-{storage[1:]}" / "sample"
                    destination = plugin_root / "skills" / "sample"
                    source.mkdir(parents=True)
                    (source / "SKILL.md").write_text(
                        "---\nname: sample\ndescription: test\n---\n# test\n",
                        encoding="utf-8",
                    )
                    PACKAGER.copy_workbuddy_skill(source, destination)
                    (plugin_root / "scripts").mkdir()
                    shutil.copy2(
                        RELEASE_MANAGER / "workbuddy_behavior_hook.py",
                        plugin_root / "scripts" / "workbuddy_behavior_hook.py",
                    )
                    (plugin_root / ".codebuddy-plugin").mkdir()
                    (plugin_root / ".codebuddy-plugin/plugin.json").write_text(
                        json.dumps({"name": "plugin", "version": "9.9.0"}),
                        encoding="utf-8",
                    )
                    if storage == ".codebuddy":
                        decoy = (
                            home
                            / ".workbuddy/plugins/marketplaces/decoy/plugins/plugin"
                        )
                        (decoy / "scripts").mkdir(parents=True)
                        shutil.copy2(
                            RELEASE_MANAGER / "workbuddy_behavior_hook.py",
                            decoy / "scripts/workbuddy_behavior_hook.py",
                        )
                    data_root = plugin_root / ".behavior-data"
                    data_root.mkdir()
                    (data_root / "current-turn.json").write_text(
                        json.dumps(
                            {
                                "session_id": "session-2",
                                "turn_id": f"turn-{storage[1:]}",
                            }
                        ),
                        encoding="utf-8",
                    )
                    state_path, _ = BEHAVIOR.state_paths(data_root, "session-2")
                    state_path.parent.mkdir(parents=True)
                    state_path.write_text(
                        json.dumps(
                            {
                                "schema_version": 2,
                                "session_id": "session-2",
                                "turn_id": f"turn-{storage[1:]}",
                                "prompt_sha256": "",
                                "prompt_signals": {},
                                "active_skills": [],
                                "status": "pending",
                            }
                        ),
                        encoding="utf-8",
                    )
                    text = (destination / "SKILL.md").read_text(encoding="utf-8")
                    match = re.search(r"!`(.+?)`", text)
                    self.assertIsNotNone(match)
                    environment = os.environ.copy()
                    environment["HOME"] = str(home)
                    environment.pop("CODEBUDDY_PLUGIN_ROOT", None)
                    environment.pop("CODEBUDDY_SKILL_DIR", None)
                    environment.pop("CODEBUDDY_SESSION_ID", None)

                    process = subprocess.run(
                        match.group(1),
                        shell=True,
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                        cwd=root,
                    )

                    self.assertEqual(process.returncode, 0, process.stderr)
                    receipt = json.loads(process.stdout)
                    self.assertTrue(receipt["activation_ok"])
                    self.assertEqual(receipt["skill"], "sample")
                    self.assertEqual(receipt["root_source"], expected_source)
                    self.assertTrue(receipt["state_persisted"])
                    self.assertEqual(receipt["active_skills_after"], ["sample"])
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        [item["skill"] for item in state["active_skills"]],
                        ["sample"],
                    )

    def test_behavior_hook_runner_discovers_workbuddy_layout_without_host_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            plugin_root = (
                home
                / ".workbuddy/plugins/marketplaces/jiaotang/plugins/plugin"
            )
            (plugin_root / "scripts").mkdir(parents=True)
            (plugin_root / ".codebuddy-plugin").mkdir()
            (plugin_root / ".codebuddy-plugin/plugin.json").write_text(
                json.dumps({"name": "plugin", "version": "9.9.0"}),
                encoding="utf-8",
            )
            PACKAGER.deploy_workbuddy_behavior_runtime(plugin_root)
            command = PACKAGER.workbuddy_behavior_hooks("plugin")["hooks"][
                "UserPromptSubmit"
            ][0]["hooks"][0]["command"]
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            environment.pop("CODEBUDDY_PLUGIN_ROOT", None)
            environment.pop("CODEBUDDY_SKILL_DIR", None)

            process = subprocess.run(
                command,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                input=json.dumps(
                    {"session_id": "session-hook", "prompt": "测试提示词"}
                ),
                env=environment,
                cwd=root,
            )

            self.assertEqual(process.returncode, 0, process.stderr)
            receipt = json.loads(process.stdout)
            self.assertIn("hookSpecificOutput", receipt)
            state_path, _ = BEHAVIOR.state_paths(
                plugin_root / ".behavior-data",
                "session-hook",
            )
            self.assertTrue(state_path.is_file())

    def test_all_49_generated_skill_runners_activate_from_default_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            plugin_root = (
                home
                / ".workbuddy/plugins/marketplaces/jiaotang/plugins/"
                "jiaotang-workbuddy-skills"
            )
            suite = json.loads(
                (REPOSITORY / "skills/suite-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            skills = list(suite["skills"])
            self.assertEqual(len(skills), 49)
            self.assertEqual(len(set(skills)), 49)
            commands = {}
            for skill in skills:
                source = REPOSITORY / "skills" / skill
                destination = plugin_root / "skills" / skill
                PACKAGER.copy_workbuddy_skill(source, destination)
                text = (destination / "SKILL.md").read_text(encoding="utf-8")
                match = re.search(r"!`(.+?)`", text)
                self.assertIsNotNone(match, skill)
                commands[skill] = match.group(1)
            (plugin_root / "scripts").mkdir()
            shutil.copy2(
                RELEASE_MANAGER / "workbuddy_behavior_hook.py",
                plugin_root / "scripts/workbuddy_behavior_hook.py",
            )
            (plugin_root / ".codebuddy-plugin").mkdir()
            (plugin_root / ".codebuddy-plugin/plugin.json").write_text(
                json.dumps(
                    {
                        "name": "jiaotang-workbuddy-skills",
                        "version": "1.5.0",
                    }
                ),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            environment["CODEBUDDY_SESSION_ID"] = "suite-session"
            environment.pop("CODEBUDDY_PLUGIN_ROOT", None)
            environment.pop("CODEBUDDY_SKILL_DIR", None)
            environment.pop("CODEBUDDY_PLUGIN_DATA", None)
            receipts = []
            for skill in skills:
                process = subprocess.run(
                    commands[skill],
                    shell=True,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                    cwd=root,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                receipt = json.loads(process.stdout)
                self.assertTrue(receipt["activation_ok"], skill)
                self.assertEqual(receipt["skill"], skill)
                self.assertEqual(
                    receipt["root_source"],
                    "workbuddy-marketplace",
                )
                self.assertTrue(receipt["state_persisted"])
                receipts.append(receipt)

            self.assertEqual(receipts[-1]["active_skill_count"], 49)
            self.assertEqual(
                set(receipts[-1]["active_skills_after"]),
                set(skills),
            )
            state_path, _ = BEHAVIOR.state_paths(
                plugin_root / ".behavior-data",
                "suite-session",
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {item["skill"] for item in state["active_skills"]},
                set(skills),
            )

    def test_workbuddy_activation_rejects_fallback_outside_plugin_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_root = root / "plugin"
            plugin_root.mkdir()
            external = root / "external" / "policy-retrieval"
            external.mkdir(parents=True)
            (external / "SKILL.md").write_text(
                "---\nname: policy-retrieval\ndescription: test\n---\n",
                encoding="utf-8",
            )
            data_root = root / "behavior"
            data_root.mkdir()

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = BEHAVIOR.activate(
                    data_root,
                    plugin_root,
                    "session-3",
                    "policy-retrieval",
                    external,
                )

            self.assertEqual(result, 0)
            receipt = json.loads(output.getvalue())
            self.assertFalse(receipt["activation_ok"])
            self.assertEqual(
                receipt["error_code"],
                "SKILL_DIRECTORY_UNAVAILABLE",
            )

    def test_preference_migration_does_not_use_exec(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "skills/first-run-configuration/scripts/"
            "migrate_skill_preferences.py"
        )
        self.assertNotIn("exec(", script.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

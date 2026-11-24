import json
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preflight.py"
PROVINCIAL = "省级专精特新中小企业"
LITTLE_GIANT = "专精特新“小巨人”"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )


class PreflightTests(unittest.TestCase):
    def preflight(
        self, *, task_type="quality-preassessment", project_level=PROVINCIAL,
        application_type="新申报", has_standard_input=False, exit_code=0,
    ):
        """按 SKILL.md「政策与接口」从命令行读取机器预检结果。"""
        args = []
        for flag, value in (
            ("--task-type", task_type),
            ("--project-level", project_level),
            ("--application-type", application_type),
        ):
            if value is not None:
                args.extend((flag, value))
        if has_standard_input:
            args.append("--has-standard-input")
        result = run_cli(*args)
        self.assertEqual(result.returncode, exit_code, f"{result.stderr}\n{result.stdout}")
        return json.loads(result.stdout)

    def assert_blocked_on(self, result, keys):
        """SKILL.md「政策与接口」要求先补齐决定适用口径的上下文。"""
        self.assertEqual(result["status"], "needs-user-input")
        self.assertIs(result["can_start_substantive_work"], False)
        self.assertIs(result["can_issue_full_score"], False)
        self.assertEqual([item["key"] for item in result["high_impact_gaps"]], keys)

    def test_documented_provincial_recognition_context_is_ready(self):
        """以 SKILL.md「政策与接口」的省级新申报参数验证 2026 政策路由与平台分边界。"""
        result = self.preflight(has_standard_input=True)
        self.assertEqual(result["schema_version"], 1)
        # references/current-policy-baseline-2026.json 固定机器记录的基线版本与日期。
        self.assertEqual(result["policy_version"], "2026.1")
        self.assertEqual(result["policy_as_of"], "2026-08-02")
        self.assertEqual(result["status"], "ready")
        self.assertIs(result["can_start_substantive_work"], True)
        self.assertIs(result["can_issue_full_score"], False)
        self.assertEqual(result["quality_score_mode"], "platform-only")
        self.assertIs(result["requires_task_specific_rerun"], False)
        self.assertEqual(result["high_impact_gaps"], [])
        self.assertIsNone(result["blocking_question"])
        # current-policy-baseline-2026.md「当前规则」规定省级新申报的平台分不低于 50。
        self.assertEqual(result["selected_policy"], {
            "project_level": PROVINCIAL,
            "project_id": "zhejiang-specialized-sme",
            "application_type": "recognition",
            "rule_branch": "2026-current",
            "quality_score_threshold": 50,
            "operator": "gte",
            "rule_id": "specialized-sme-quality-score",
        })
        # current-policy-baseline-2026.md「方法边界」保留门槛评估和平台分状态。
        self.assertEqual(result["low_impact_assumptions"], [{
            "key": "output_format",
            "assumed_value": "结构化预评估表",
            "reason": "技能不再生成内部评分工作簿",
        }])
        self.assertEqual(result["method_boundary"], {
            "official_evaluation": "质量得分只接受主管部门平台实际结果及其可验证记录。",
            "internal_preassessment": "本技能只做2026硬门槛和质量评价输入预评估，不生成内部总分。",
            "quality_score_statuses": ["verified-platform-score", "pending-platform-evaluation"],
            "prohibited_outputs": ["内部百分制总分", "区间估分", "保守分", "基于未达条件的假设估分", "获批概率"],
        })

    def test_provincial_review_keeps_50_point_gate(self):
        """references/current-policy-baseline-2026.md「当前规则」省级复核采用管理办法的 50 分线。"""
        result = self.preflight(project_level="省专", application_type="复核")
        self.assertEqual(result["selected_policy"], {
            "project_level": PROVINCIAL,
            "project_id": "zhejiang-specialized-sme",
            "application_type": "review",
            "rule_branch": "2026-management-review",
            "quality_score_threshold": 50,
            "operator": "gte",
            "rule_id": "specialized-sme-quality-score",
        })

    def test_little_giant_recognition_resolves_aliases_and_60_point_gate(self):
        """references/current-policy-baseline-2026.md「当前规则」小巨人新申报的平台分不低于 60。"""
        result = self.preflight(project_level=" 小巨人 ", application_type=" new-recognition ")
        self.assertEqual(result["selected_policy"], {
            "project_level": LITTLE_GIANT,
            "project_id": "little-giant",
            "application_type": "recognition",
            "rule_branch": "2026-current",
            "quality_score_threshold": 60,
            "operator": "gte",
            "rule_id": "little-giant-quality-score",
        })

    def test_little_giant_review_has_management_baseline(self):
        """references/current-policy-baseline-2026.md「当前规则」小巨人普通复核按管理办法基线核对。"""
        result = self.preflight(project_level=LITTLE_GIANT, application_type="复核")
        self.assertEqual(result["selected_policy"], {
            "project_level": LITTLE_GIANT,
            "project_id": "little-giant",
            "application_type": "review",
            "rule_branch": "2026-management-review",
            "quality_score_threshold": 60,
            "operator": "gte",
            "rule_id": "little-giant-quality-score",
        })
        self.assertIs(result["can_issue_full_score"], False)

    def test_missing_standard_input_keeps_gate_work_available(self):
        """references/data-contract.md「缺失处理」和政策基线「方法边界」允许继续门槛和差距分析。"""
        for task_type in ("quality-preassessment", "gate-only"):
            with self.subTest(task_type=task_type):
                result = self.preflight(task_type=task_type)
                self.assertEqual(result["status"], "ready")
                self.assertIs(result["can_start_substantive_work"], True)
                self.assertIs(result["can_issue_full_score"], False)
                self.assertEqual(result["quality_score_mode"], "platform-only")
                self.assertEqual(result["high_impact_gaps"], [])
                self.assertIn("pending-platform-evaluation", result["method_boundary"]["quality_score_statuses"])

    def test_missing_task_type_blocks_preassessment(self):
        """SKILL.md「政策与接口」要求从任务类型确定是否启动当前门槛预评估。"""
        result = self.preflight(task_type=None, exit_code=2)
        self.assert_blocked_on(result, ["task_type"])
        self.assertEqual(result["high_impact_gaps"][0]["allowed_values"], [
            "quality-preassessment", "gate-only", "explanation",
        ])
        self.assertIn("任务类型", result["blocking_question"])

    def test_missing_project_level_blocks_scoring_context(self):
        """SKILL.md「政策与接口」要求先确定层级，才能选择 50 分线或 60 分线。"""
        for task_type in ("quality-preassessment", "gate-only"):
            with self.subTest(task_type=task_type):
                result = self.preflight(task_type=task_type, project_level=None, exit_code=2)
                self.assert_blocked_on(result, ["project_level"])
                self.assertEqual(result["high_impact_gaps"][0]["allowed_values"], [PROVINCIAL, LITTLE_GIANT])
                self.assertIsNone(result["selected_policy"])
                self.assertIn("项目层级", result["blocking_question"])

    def test_missing_application_type_blocks_scoring_context(self):
        """SKILL.md「政策与接口」要求先明确新申报或复核，才能选择相应分支。"""
        for task_type in ("quality-preassessment", "gate-only"):
            with self.subTest(task_type=task_type):
                result = self.preflight(task_type=task_type, application_type=None, exit_code=2)
                self.assert_blocked_on(result, ["application_type"])
                self.assertEqual(result["high_impact_gaps"][0]["allowed_values"], ["新申报", "复核"])
                self.assertIsNone(result["selected_policy"])
                self.assertIn("申请类型", result["blocking_question"])

    def test_two_context_gaps_are_reported_in_one_question(self):
        """SKILL.md「政策与接口」要求层级和申请类型共同决定政策口径。"""
        result = self.preflight(project_level=None, application_type=None, exit_code=2)
        self.assert_blocked_on(result, ["project_level", "application_type"])
        self.assertIn("一次确认或补充", result["blocking_question"])
        self.assertIn("项目层级", result["blocking_question"])
        self.assertIn("申请类型", result["blocking_question"])

    def test_explanation_can_continue_and_preassessment_requires_its_own_run(self):
        """SKILL.md「政策与接口」要求做具体 2026 门槛预评估时再确定层级和申请类型。"""
        result = self.preflight(task_type="explanation", project_level=None, application_type=None)
        self.assertEqual(result["status"], "ready")
        self.assertIs(result["can_start_substantive_work"], True)
        self.assertIs(result["can_issue_full_score"], False)
        self.assertIs(result["requires_task_specific_rerun"], True)
        self.assertEqual(result["high_impact_gaps"], [])
        self.assertIsNone(result["blocking_question"])
        self.assertIsNone(result["selected_policy"])

    def test_invalid_project_and_application_values_return_allowed_values(self):
        """references/current-policy-baseline-2026.json 的项目层级和申请类型限定支持分支。"""
        result = self.preflight(project_level="99", application_type="续期", exit_code=2)
        self.assert_blocked_on(result, ["project_level", "application_type"])
        self.assertEqual([gap["allowed_values"] for gap in result["high_impact_gaps"]], [
            [PROVINCIAL, LITTLE_GIANT], ["新申报", "复核"],
        ])
        self.assertIsNone(result["selected_policy"])

    def test_legacy_full_score_does_not_start_a_scoring_task(self):
        """references/current-policy-baseline-2026.md「方法边界」将历史评分工具保留为历史参考。"""
        result = self.preflight(task_type="full-score", exit_code=2)
        self.assert_blocked_on(result, ["task_type"])
        self.assertEqual(result["quality_score_mode"], "platform-only")

    def test_reported_platform_score_thresholds_include_equality(self):
        """references/current-policy-baseline-2026.md「当前规则」的“不低于”包含门槛值。"""
        for level, application, scores in (
            (PROVINCIAL, "新申报", (49, 50, 51)),
            (PROVINCIAL, "复核", (49, 50, 51)),
            (LITTLE_GIANT, "新申报", (59, 60, 61)),
        ):
            with self.subTest(level=level, application=application):
                policy = self.preflight(project_level=level, application_type=application)["selected_policy"]
                # 按预检给出的比较符和分数线解释固定的已核平台分。
                self.assertEqual(policy["operator"], "gte")
                threshold = policy["quality_score_threshold"]
                self.assertEqual([score >= threshold for score in scores], [False, True, True])

    def test_cli_rejects_flag_without_required_value(self):
        """SKILL.md「政策与接口」运行命令中，层级选项须带一个项目名称。"""
        result = run_cli("--task-type", "quality-preassessment", "--project-level")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("--project-level: expected one argument", result.stderr)

    def test_cli_rejects_a_platform_score_argument(self):
        """SKILL.md「政策与接口」预检入口接收政策上下文，平台分由事实与判断流程采用。"""
        result = run_cli(
            "--task-type", "quality-preassessment", "--project-level", PROVINCIAL,
            "--application-type", "新申报", "--quality-score", "50",
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("unrecognized arguments: --quality-score 50", result.stderr)


if __name__ == "__main__":
    unittest.main()

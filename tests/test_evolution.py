import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    import importlib.util

    path = ROOT / "skills" / "skill-curator" / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EvolutionTests(unittest.TestCase):
    def test_multiline_backticks_are_not_treated_as_paths(self):
        module = load_script("build_impact_graph.py")
        self.assertIsNone(module.resolve_reference("一段很长的说明\n仍然不是路径", ROOT / "docs/config/evolution.md", ROOT))

    def test_impact_graph_links_resources_and_invoked_skills(self):
        module = load_script("build_impact_graph.py")
        graph = module.build_graph(ROOT)
        edges = {(edge["source"], edge["target"], edge["type"]) for edge in graph["edges"]}
        self.assertIn(
            (
                "skills/skill-curator/scripts/aggregate_corrections.py",
                "skills/skill-curator/SKILL.md",
                "owned-by-skill",
            ),
            edges,
        )
        self.assertIn(
            (
                "skills/evolution-governance/SKILL.md",
                "skills/skill-evolution/SKILL.md",
                "invoked-by",
            ),
            edges,
        )

    def test_threshold_requires_three_signals_and_two_tasks(self):
        module = load_script("aggregate_corrections.py")
        policy = {
            "min_signal_count": 3,
            "min_distinct_tasks": 2,
            "max_batch_skills": 2,
            "cooldown_days": 7,
            "require_verified": True,
        }
        records = [
            {
                "_id": str(index),
                "task_id": task,
                "skill": "sme-development-projects",
                "rule_key": "product-name-specificity",
                "summary": f"signal {index}",
                "verified": True,
                "sensitive": False,
            }
            for index, task in enumerate(("task-a", "task-a", "task-b"), start=1)
        ]
        result = module.aggregate(records, policy, {}, datetime(2026, 7, 18, tzinfo=timezone.utc))
        self.assertTrue(result["ready"])
        self.assertEqual(result["selected_skills"], ["sme-development-projects"])

        result = module.aggregate(records[:2], policy, {}, datetime(2026, 7, 18, tzinfo=timezone.utc))
        self.assertFalse(result["ready"])
        self.assertEqual(result["groups"][0]["needed_signals"], 1)
        self.assertEqual(result["groups"][0]["needed_tasks"], 1)

    def test_sensitive_unverified_and_cooldown_do_not_enter_batch(self):
        module = load_script("aggregate_corrections.py")
        policy = {
            "min_signal_count": 1,
            "min_distinct_tasks": 1,
            "max_batch_skills": 2,
            "cooldown_days": 7,
            "require_verified": True,
        }
        records = [
            {"_id": "a", "task_id": "t1", "skill": "x", "rule_key": "r", "summary": "a", "verified": False, "sensitive": False},
            {"_id": "b", "task_id": "t2", "skill": "y", "rule_key": "r", "summary": "b", "verified": True, "sensitive": True},
            {"_id": "c", "task_id": "t3", "skill": "z", "rule_key": "r", "summary": "c", "verified": True, "sensitive": False},
        ]
        state = {"last_planned_at_by_skill": {"z": "2026-07-15T00:00:00+00:00"}}
        result = module.aggregate(records, policy, state, datetime(2026, 7, 18, tzinfo=timezone.utc))
        self.assertFalse(result["ready"])
        self.assertEqual(result["excluded"], {"cooldown": 1, "sensitive": 1, "unverified": 1})


if __name__ == "__main__":
    unittest.main()

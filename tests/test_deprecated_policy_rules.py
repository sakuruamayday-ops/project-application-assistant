import importlib.util
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "validate_deprecated_policy_rules.py"
SPEC = importlib.util.spec_from_file_location("deprecated_policy_gate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_repository_deprecated_policy_semantics_are_blocked():
    result = MODULE.validate_repository(REPOSITORY)
    assert result["status"] == "pass", result["errors"]


def test_active_reuse_of_2022_standard_is_rejected():
    assert MODULE.line_has_active_old_policy_semantics(
        "2027年度复核继续使用2022年标准计算分数。"
    )


def test_historical_fact_with_explicit_prohibition_is_allowed():
    assert not MODULE.line_has_active_old_policy_semantics(
        "历史事实：2026年度复核曾按2022年标准执行，但不得用于当前或未来复核。"
    )

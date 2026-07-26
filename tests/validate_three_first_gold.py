from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTAL_ROOT = ROOT / "services/knowledge-portal"
sys.path.insert(0, str(PORTAL_ROOT))

from app.three_first_routing import plan_three_first_analysis


FIXTURE = ROOT / "tests/fixtures/three_first_analysis_gold.jsonl"
MAIN = PORTAL_ROOT / "app/main.py"


def assert_expected(case_id: str, actual: object, expected: object, path: str = "") -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise AssertionError(f"{case_id}:{path} 预期对象，实际为 {type(actual).__name__}")
        for key, value in expected.items():
            if key not in actual:
                raise AssertionError(f"{case_id}:{path}.{key} 缺少字段")
            assert_expected(case_id, actual[key], value, f"{path}.{key}")
        return
    if actual != expected:
        raise AssertionError(f"{case_id}:{path} 预期 {expected!r}，实际 {actual!r}")


def main() -> None:
    cases = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failures: list[str] = []
    for case in cases:
        try:
            result = plan_three_first_analysis(case["query"], **case.get("inputs", {}))
            clarification = case["expected"].get("clarification_contains")
            expected = {
                key: value
                for key, value in case["expected"].items()
                if key != "clarification_contains"
            }
            assert_expected(case["id"], result, expected)
            if clarification and clarification not in result["clarifications"]:
                raise AssertionError(f"{case['id']}:缺少追问 {clarification}")
        except AssertionError as error:
            failures.append(str(error))

    source = MAIN.read_text(encoding="utf-8")
    visible_tools = set(
        re.findall(
            r"@knowledge_mcp\.tool\(\)\s*\ndef\s+(three_first_[a-z0-9_]+)\s*\(",
            source,
        )
    )
    if visible_tools != {"three_first_analysis"}:
        failures.append(
            "三首MCP可见入口必须且只能是 three_first_analysis，"
            f"当前为 {sorted(visible_tools)}"
        )

    summary = {
        "status": "fail" if failures else "pass",
        "cases": len(cases),
        "passed": len(cases) - len(failures),
        "visible_mcp_tools": sorted(visible_tools),
        "failures": failures,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

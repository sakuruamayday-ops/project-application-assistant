from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Sequence


Adapter = Callable[
    [Mapping[str, object], Mapping[str, object]],
    tuple[bool, object, Sequence[str]],
]


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    suite: str
    severity: str
    description: str
    adapter: str
    passed: bool
    observed: object
    evidence: tuple[str, ...]


class AcceptanceHarness:
    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}

    def register(self, name: str, adapter: Adapter) -> None:
        normalized = name.strip()
        if not normalized:
            raise ValueError("adapter name must not be empty")
        if normalized in self._adapters:
            raise ValueError(f"adapter already registered: {normalized}")
        self._adapters[normalized] = adapter

    def run(
        self,
        profile: Mapping[str, object],
        context: Mapping[str, object],
        *,
        suites: Sequence[str] = (),
    ) -> dict[str, object]:
        blocking = {
            str(item)
            for item in profile.get("blocking_severities", ["P0", "P1"])
        }
        raw_checks = profile.get("checks", [])
        if not isinstance(raw_checks, list):
            raise ValueError("profile.checks must be a list")
        if not raw_checks:
            raise ValueError("profile.checks must not be empty")
        available_suites = {
            str(check.get("suite") or "default")
            for check in raw_checks
            if isinstance(check, Mapping)
        }
        raw_suite_groups = profile.get("suite_groups", {})
        if not isinstance(raw_suite_groups, Mapping):
            raise ValueError("profile.suite_groups must be an object")
        suite_groups: dict[str, set[str]] = {}
        for name, members in raw_suite_groups.items():
            if not isinstance(members, Sequence) or isinstance(members, str):
                raise ValueError(f"suite group {name} must be a list")
            suite_groups[str(name)] = {
                str(member).strip() for member in members if str(member).strip()
            }

        requested_suites = [suite.strip() for suite in suites if suite.strip()]
        selected_suites: set[str] = set()
        for requested in requested_suites:
            if requested in suite_groups:
                selected_suites.update(suite_groups[requested])
            elif requested in available_suites:
                selected_suites.add(requested)
            else:
                raise ValueError(f"unknown acceptance suite or group: {requested}")
        unknown_group_members = sorted(selected_suites - available_suites)
        if unknown_group_members:
            raise ValueError(
                "suite group references unknown suites: "
                + ", ".join(unknown_group_members)
            )

        results: list[CheckResult] = []
        for raw_check in raw_checks:
            if not isinstance(raw_check, Mapping):
                raise ValueError("each profile check must be an object")
            suite = str(raw_check.get("suite") or "default")
            if selected_suites and suite not in selected_suites:
                continue
            adapter_name = str(raw_check.get("adapter") or "")
            adapter = self._adapters.get(adapter_name)
            if adapter is None:
                raise ValueError(f"unknown adapter: {adapter_name}")
            config = raw_check.get("config", {})
            if not isinstance(config, Mapping):
                raise ValueError(
                    f"check {raw_check.get('id')} config must be an object"
                )
            try:
                passed, observed, evidence = adapter(config, context)
            except Exception as error:
                passed = False
                observed = {"error": type(error).__name__}
                evidence = (str(error),)
            results.append(
                CheckResult(
                    check_id=str(raw_check.get("id") or ""),
                    suite=suite,
                    severity=str(raw_check.get("severity") or "P1"),
                    description=str(raw_check.get("description") or ""),
                    adapter=adapter_name,
                    passed=bool(passed),
                    observed=observed,
                    evidence=tuple(str(item) for item in evidence),
                )
            )

        failures = [result for result in results if not result.passed]
        blocking_failures = [
            result for result in failures if result.severity in blocking
        ]
        return {
            "schema_version": 1,
            "profile_id": str(profile.get("profile_id") or "unnamed"),
            "target_type": str(profile.get("target_type") or "unknown"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "requested_suites": requested_suites,
            "selected_suites": sorted(selected_suites),
            "blocking_severities": sorted(blocking),
            "status": "pass" if not blocking_failures else "fail",
            "release_allowed": not blocking_failures,
            "summary": {
                "checks": len(results),
                "passed": len(results) - len(failures),
                "failed": len(failures),
                "blocking_failed": len(blocking_failures),
                "failures_by_severity": dict(
                    sorted(Counter(result.severity for result in failures).items())
                ),
            },
            "results": [asdict(result) for result in results],
        }

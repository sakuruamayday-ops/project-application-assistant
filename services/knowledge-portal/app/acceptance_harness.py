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
    status: str
    passed: bool
    depends_on: tuple[str, ...]
    blocked_by: tuple[str, ...]
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
        check_ids: list[str] = []
        for raw_check in raw_checks:
            if not isinstance(raw_check, Mapping):
                raise ValueError("each profile check must be an object")
            check_id = str(raw_check.get("id") or "").strip()
            if not check_id:
                raise ValueError("each profile check must have a non-empty id")
            check_ids.append(check_id)
        duplicate_ids = sorted(
            check_id
            for check_id, count in Counter(check_ids).items()
            if count > 1
        )
        if duplicate_ids:
            raise ValueError(
                "duplicate acceptance check ids: " + ", ".join(duplicate_ids)
            )
        known_check_ids = set(check_ids)
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

        selected_checks = [
            raw_check
            for raw_check in raw_checks
            if not selected_suites
            or str(raw_check.get("suite") or "default") in selected_suites
        ]
        selected_check_ids = {
            str(raw_check.get("id") or "") for raw_check in selected_checks
        }
        results: list[CheckResult] = []
        results_by_id: dict[str, CheckResult] = {}
        for raw_check in selected_checks:
            check_id = str(raw_check.get("id") or "")
            suite = str(raw_check.get("suite") or "default")
            raw_dependencies = raw_check.get("depends_on", [])
            if not isinstance(raw_dependencies, Sequence) or isinstance(
                raw_dependencies, str
            ):
                raise ValueError(f"check {check_id} depends_on must be a list")
            depends_on = tuple(
                str(item).strip()
                for item in raw_dependencies
                if str(item).strip()
            )
            unknown_dependencies = sorted(set(depends_on) - known_check_ids)
            if unknown_dependencies:
                raise ValueError(
                    f"check {check_id} references unknown dependencies: "
                    + ", ".join(unknown_dependencies)
                )
            unselected_dependencies = sorted(
                set(depends_on) - selected_check_ids
            )
            if unselected_dependencies:
                raise ValueError(
                    f"check {check_id} dependencies were not selected: "
                    + ", ".join(unselected_dependencies)
                )
            forward_dependencies = [
                dependency
                for dependency in depends_on
                if dependency not in results_by_id
            ]
            if forward_dependencies:
                raise ValueError(
                    f"check {check_id} dependencies must appear earlier: "
                    + ", ".join(forward_dependencies)
                )
            adapter_name = str(raw_check.get("adapter") or "")
            adapter = self._adapters.get(adapter_name)
            if adapter is None:
                raise ValueError(f"unknown adapter: {adapter_name}")
            config = raw_check.get("config", {})
            if not isinstance(config, Mapping):
                raise ValueError(
                    f"check {raw_check.get('id')} config must be an object"
                )
            blocked_by = tuple(
                dependency
                for dependency in depends_on
                if results_by_id[dependency].status != "pass"
            )
            if blocked_by:
                result = CheckResult(
                    check_id=check_id,
                    suite=suite,
                    severity=str(raw_check.get("severity") or "P1"),
                    description=str(raw_check.get("description") or ""),
                    adapter=adapter_name,
                    status="blocked",
                    passed=False,
                    depends_on=depends_on,
                    blocked_by=blocked_by,
                    observed={"blocked_by": list(blocked_by)},
                    evidence=(
                        "prerequisite check did not pass: "
                        + ", ".join(blocked_by),
                    ),
                )
            else:
                try:
                    passed, observed, evidence = adapter(config, context)
                except Exception as error:
                    passed = False
                    observed = {"error": type(error).__name__}
                    evidence = (str(error),)
                result = CheckResult(
                    check_id=check_id,
                    suite=suite,
                    severity=str(raw_check.get("severity") or "P1"),
                    description=str(raw_check.get("description") or ""),
                    adapter=adapter_name,
                    status="pass" if passed else "fail",
                    passed=bool(passed),
                    depends_on=depends_on,
                    blocked_by=(),
                    observed=observed,
                    evidence=tuple(str(item) for item in evidence),
                )
            results.append(result)
            results_by_id[check_id] = result

        failures = [result for result in results if result.status == "fail"]
        blocked_results = [
            result for result in results if result.status == "blocked"
        ]
        blocking_failures = [
            result for result in failures if result.severity in blocking
        ]
        blocking_blocked = [
            result for result in blocked_results if result.severity in blocking
        ]
        release_allowed = not blocking_failures and not blocking_blocked
        return {
            "schema_version": 1,
            "profile_id": str(profile.get("profile_id") or "unnamed"),
            "target_type": str(profile.get("target_type") or "unknown"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "requested_suites": requested_suites,
            "selected_suites": sorted(selected_suites),
            "blocking_severities": sorted(blocking),
            "status": "pass" if release_allowed else "fail",
            "release_allowed": release_allowed,
            "summary": {
                "checks": len(results),
                "passed": sum(result.status == "pass" for result in results),
                "failed": len(failures),
                "blocked": len(blocked_results),
                "blocking_failed": len(blocking_failures),
                "blocking_blocked": len(blocking_blocked),
                "failures_by_severity": dict(
                    sorted(Counter(result.severity for result in failures).items())
                ),
            },
            "results": [asdict(result) for result in results],
        }

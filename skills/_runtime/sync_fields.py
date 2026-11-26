"""Field differences for the JSON snapshots used during synchronization."""

from result_digest import canonical_json


_MISSING = object()


def differences(expected, actual, path=""):
    if actual is _MISSING:
        return [{"path": path, "kind": "missing", "expected": expected, "actual": None}]
    if expected is _MISSING:
        return [{"path": path, "kind": "unexpected", "expected": None, "actual": actual}]
    if isinstance(expected, list) and isinstance(actual, list):
        expected = dict(enumerate(expected))
        actual = dict(enumerate(actual))
    if isinstance(expected, dict) and isinstance(actual, dict):
        changes = []
        for key in sorted(expected.keys() | actual.keys()):
            segment = str(key).replace("~", "~0").replace("/", "~1")
            changes.extend(
                differences(expected.get(key, _MISSING), actual.get(key, _MISSING), f"{path}/{segment}")
            )
        return changes
    if canonical_json(expected) != canonical_json(actual):
        return [{"path": path, "kind": "mismatch", "expected": expected, "actual": actual}]
    return []

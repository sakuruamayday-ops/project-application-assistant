import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/project-rule-manager/scripts/local_rules.py"
spec = importlib.util.spec_from_file_location("local_rules", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_create_keeps_one_source_real_audit_and_unknown_dates(tmp_path):
    data = {"rules": [
        {"id": "P1", "year": "2025", "status": "stale", "threshold": 5},
        {"id": "P5", "year": "2026", "status": "draft", "effective_date": None, "threshold": 6},
    ], "relationships": [{"old_status": "superseded", "old_value": 150, "new_value": 200}]}
    start = datetime.now(timezone.utc)
    output = tmp_path / "new-rules"
    module.create(data, output)
    saved = json.loads((output / "rule.yaml").read_text())
    audit = json.loads((output / "audit.jsonl").read_text())
    assert start <= datetime.fromisoformat(audit["at"]) <= datetime.now(timezone.utc)
    assert audit["at"] == saved["recorded_at"]
    assert saved["rules"] == data["rules"]
    assert not (output / "rules.json").exists()
    assert module.query(saved, ["candidate", "verified"], "2026") == []
    assert module.query(saved, ["draft"], "2026") == [data["rules"][1]]


@pytest.mark.parametrize("value", ["supersedes", "corrected_value", None, []])
def test_rejects_invalid_nested_status_before_writing(tmp_path, value):
    data = {"rules": [{"id": "P4", "status": "stale"}], "comparison": [{"status": value}]}
    with pytest.raises((ValueError, TypeError), match="status|unhashable"):
        module.create(data, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_rejects_new_verified_duplicate_ids_and_existing_directory(tmp_path):
    with pytest.raises(ValueError, match="cannot claim verified"):
        module.create({"rules": [{"id": "P1", "status": "verified"}]}, tmp_path / "bad")
    with pytest.raises(ValueError, match="duplicate"):
        module.create({"rules": [{"id": "P1", "status": "candidate"}] * 2}, tmp_path / "bad")
    original = tmp_path / "rule.yaml"
    original.write_text("original")
    with pytest.raises(FileExistsError):
        module.create({"rules": [{"id": "P1", "status": "candidate"}]}, tmp_path)
    assert original.read_text() == "original"

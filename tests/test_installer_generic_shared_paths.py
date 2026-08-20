from __future__ import annotations

import json
from pathlib import Path

from project_assistant.installer import _managed_entries


def test_generic_shared_paths_are_managed_by_generic_installer(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "sample"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: sample\n---\n", encoding="utf-8")
    runtime = tmp_path / "_runtime/jiaotang-kb"
    runtime.mkdir(parents=True)
    (runtime / "jiaotang-agent.mjs").write_text("runtime", encoding="utf-8")
    (tmp_path / "suite-manifest.json").write_text(
        json.dumps(
            {
                "skills": ["sample"],
                "shared_paths": [],
                "generic_shared_paths": ["_runtime/jiaotang-kb"],
            }
        ),
        encoding="utf-8",
    )

    entries, _manifest = _managed_entries(tmp_path)

    assert any(
        entry["relative"] == Path("_runtime/jiaotang-kb")
        and entry["kind"] == "shared"
        for entry in entries
    )

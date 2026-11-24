#!/usr/bin/env python3
"""Lightweight zero-dependency runtime helper for WorkBuddy standalone skills."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def skill_root(script_file: str | Path) -> Path:
    return Path(script_file).resolve().parents[1]


def skill_asset(script_file: str | Path, *parts: str) -> Path:
    return skill_root(script_file).joinpath(*parts)


def check_optional_packages(*names: str) -> dict[str, bool]:
    return {name: importlib.util.find_spec(name) is not None for name in names}


def emit_json(payload: dict[str, Any], *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


if __name__ == "__main__":
    root = skill_root(__file__)
    emit_json(
        {
            "runtime": "workbuddy-light-runtime/v1",
            "skill_root": str(root),
            "python": sys.version.split()[0],
            "optional_packages": check_optional_packages("docx", "lxml", "openpyxl"),
        }
    )

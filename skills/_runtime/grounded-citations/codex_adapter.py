#!/usr/bin/env python3
"""Thin Codex host adapter for the shared grounded-evidence engine."""

from __future__ import annotations

import runpy
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]
ENGINE = SKILLS_ROOT / "evidence-ledger" / "scripts" / "grounded_evidence.py"


if __name__ == "__main__":
    runpy.run_path(str(ENGINE), run_name="__main__", init_globals={"HOST_ADAPTER": "codex"})

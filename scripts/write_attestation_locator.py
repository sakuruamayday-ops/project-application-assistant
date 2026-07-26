#!/usr/bin/env python3
"""Persist non-secret GitHub attestation outputs beside signed host evidence."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    attestation_id = os.environ.get("ATTESTATION_ID", "")
    attestation_url = os.environ.get("ATTESTATION_URL", "")
    if not attestation_id or not attestation_url.startswith("https://github.com/"):
        raise SystemExit("GitHub attestation outputs are missing or invalid")
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "jiaotang-github-attestation-locator/v1",
        "attestation_id": attestation_id,
        "attestation_url": attestation_url,
    }
    (arguments.output_dir / "attestation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    bundle = Path(os.environ.get("ATTESTATION_BUNDLE", ""))
    if bundle.is_file():
        shutil.copy2(bundle, arguments.output_dir / "attestation-bundle.jsonl")


if __name__ == "__main__":
    main()

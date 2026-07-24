#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combine the installed Graphify extraction spec with the Jiaotang overlay."
    )
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    upstream = args.upstream.expanduser().resolve() if args.upstream else None
    overlay = args.overlay.expanduser().resolve()
    output = args.output.expanduser().resolve()

    if upstream is not None and not upstream.is_file():
        raise SystemExit(f"upstream spec not found: {upstream}")
    if not overlay.is_file():
        raise SystemExit(f"overlay not found: {overlay}")

    sections = []
    if upstream is not None:
        sections.append(upstream.read_text(encoding="utf-8").rstrip())
    sections.append(overlay.read_text(encoding="utf-8").rstrip())
    content = "\n\n".join(sections) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

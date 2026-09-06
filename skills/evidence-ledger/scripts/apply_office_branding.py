#!/usr/bin/env python3
"""Apply the signed shared brand runtime to one workspace Office artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]
BRANDING_SCRIPTS = SKILLS_ROOT / "_runtime" / "gongchuang-branding" / "scripts"
sys.path.insert(0, str(BRANDING_SCRIPTS))

from office_watermark import apply_office_watermark  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()

    # 品牌必须在正文和版式全部保存后一次性写入。随后再改文件会使
    # 专业正文、品牌和文件哈希回执失配，因此本操作只做最终保存步骤。
    result = apply_office_watermark(args.artifact.resolve())
    print(json.dumps({
        "schema_version": "gongchuang-office-branding-operation/v1",
        "status": "passed",
        "artifact": str(result),
        "format": result.suffix.lower().lstrip("."),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

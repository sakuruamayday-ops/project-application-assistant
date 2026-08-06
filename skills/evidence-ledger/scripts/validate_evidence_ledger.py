#!/usr/bin/env python3
"""兼容入口：校验证据台账JSON、JSONL或grounded-evidence/v1对象。"""

import argparse
import json
from pathlib import Path

from grounded_evidence import load_payload, validate_payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    parser.add_argument("--strict-grounded", action="store_true")
    parser.add_argument("--market-share", action="store_true")
    args = parser.parse_args()
    result = validate_payload(
        load_payload(Path(args.ledger)),
        strict_grounded=args.strict_grounded,
        require_market_share=args.market_share,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()

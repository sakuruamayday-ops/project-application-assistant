#!/usr/bin/env python3
"""校验或读取外置项目状态，不把客户数据写入技能目录。"""

import argparse
import json
from datetime import datetime
from pathlib import Path

REQUIRED = {"identity", "policy", "facts", "decisions", "pending", "artifacts", "updated_at"}


def validate(value):
    errors = [f"缺少字段:{key}" for key in sorted(REQUIRED - set(value))]
    try:
        datetime.fromisoformat(str(value.get("updated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("updated_at不是ISO日期时间")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "get"))
    parser.add_argument("state_file")
    args = parser.parse_args()
    path = Path(args.state_file).expanduser()
    value = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(value)
    result = {"status": "pass" if not errors else "fail", "errors": errors}
    if args.command == "get" and not errors:
        result["state"] = value
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 2)


if __name__ == "__main__":
    main()

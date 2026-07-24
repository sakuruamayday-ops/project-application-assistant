#!/usr/bin/env python3
"""比较两个已结构化为键值对象的材料JSON。"""

import argparse
import json
from pathlib import Path


def flatten(value, prefix=""):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result.update(flatten(child, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.update(flatten(child, f"{prefix}[{index}]"))
    else:
        result[prefix] = value
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old")
    parser.add_argument("new")
    args = parser.parse_args()
    old = flatten(json.loads(Path(args.old).read_text(encoding="utf-8")))
    new = flatten(json.loads(Path(args.new).read_text(encoding="utf-8")))
    changes = []
    for key in sorted(set(old) | set(new)):
        if key not in old:
            changes.append({"path": key, "kind": "added", "new": new[key]})
        elif key not in new:
            changes.append({"path": key, "kind": "deleted", "old": old[key]})
        elif old[key] != new[key]:
            changes.append({"path": key, "kind": "modified", "old": old[key], "new": new[key]})
    print(json.dumps({"status": "pass", "change_count": len(changes), "changes": changes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

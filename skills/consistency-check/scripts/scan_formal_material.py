#!/usr/bin/env python3
"""对已提取的正式正文做括号与待核验标记初筛。"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text_file")
    args = parser.parse_args()
    text = Path(args.text_file).read_text(encoding="utf-8")
    findings = []
    for token, label in (("(", "英文左括号"), (")", "英文右括号"), ("（", "中文左括号"), ("）", "中文右括号")):
        count = text.count(token)
        if count:
            findings.append({"rule": "parentheses", "token": token, "label": label, "count": count})
    for token in ("待核验", "待补充", "TBD", "TODO"):
        count = text.count(token)
        if count:
            findings.append({"rule": "placeholder", "token": token, "count": count})
    print(json.dumps({"status": "pass" if not findings else "review", "findings": findings}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

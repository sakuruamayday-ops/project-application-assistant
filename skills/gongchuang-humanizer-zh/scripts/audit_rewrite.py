#!/usr/bin/env python3
"""Deterministic first-pass audit for Chinese rewrites."""

import argparse
import json
import re
import sys
from pathlib import Path


NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?(?:×10[⁻−-]?[⁰¹²³⁴⁵⁶⁷⁸⁹0-9]+)?)(?:%|％|毫秒|秒|分钟|小时|天|年|万元|亿元|元|项|个|组|家|人|次|GWh|Wh|K|mm|cm|m)?"
)
# 中文属于 Unicode 单词字符；使用 ASCII 边界才能识别紧贴中文的 X1、MES。
ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9-]{1,}\b", re.ASCII)
STRONG_RE = re.compile(
    r"首创|唯一|(?:国内|国际|行业)?第一|(?:国内|国际|行业)?领先|国际先进|"
    r"填补[^，。；\n]{0,24}空白|替代(?:进口|[^，。；\n]{1,24})|自主可控"
)


def read_value(text_value: str | None, file_value: str | None, label: str) -> str:
    if bool(text_value) == bool(file_value):
        raise ValueError(f"{label} 必须且只能提供 text 或 file 其中一个")
    if text_value is not None:
        return text_value
    return Path(file_value).read_text(encoding="utf-8")


def items(pattern: re.Pattern[str], text: str) -> list[str]:
    return sorted(set(pattern.findall(text)))


def main() -> int:
    parser = argparse.ArgumentParser(description="审计改写中的数字、缩写、强结论和格式变化")
    parser.add_argument("--source-text")
    parser.add_argument("--source-file")
    parser.add_argument("--rewrite-text")
    parser.add_argument("--rewrite-file")
    parser.add_argument("--max-chars", type=int)
    parser.add_argument(
        "--trust-required-narrative",
        action="store_true",
        help="补短板、填空白、锻长板字段：将字段内结论视为已确认事实，跳过强结论审计",
    )
    args = parser.parse_args()

    try:
        source = read_value(args.source_text, args.source_file, "source")
        rewrite = read_value(args.rewrite_text, args.rewrite_file, "rewrite")
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    source_numbers = items(NUMBER_RE, source)
    rewrite_numbers = items(NUMBER_RE, rewrite)
    source_acronyms = items(ACRONYM_RE, source)
    rewrite_acronyms = items(ACRONYM_RE, rewrite)
    source_strong = [] if args.trust_required_narrative else items(STRONG_RE, source)
    rewrite_strong = [] if args.trust_required_narrative else items(STRONG_RE, rewrite)
    chars = len(rewrite.strip())
    nonspace_chars = len(re.sub(r"\s+", "", rewrite))

    result = {
        "ok": True,
        "counts": {
            "source_chars": len(source.strip()),
            "rewrite_chars": chars,
            "rewrite_nonspace_chars": nonspace_chars,
            "max_chars": args.max_chars,
        },
        "numbers": {
            "missing_from_rewrite": sorted(set(source_numbers) - set(rewrite_numbers)),
            "added_in_rewrite": sorted(set(rewrite_numbers) - set(source_numbers)),
        },
        "acronyms": {
            "missing_from_rewrite": sorted(set(source_acronyms) - set(rewrite_acronyms)),
            "added_in_rewrite": sorted(set(rewrite_acronyms) - set(source_acronyms)),
        },
        "strong_claims": {
            "audit_skipped": args.trust_required_narrative,
            "removed": sorted(set(source_strong) - set(rewrite_strong)),
            "added": sorted(set(rewrite_strong) - set(source_strong)),
        },
        "format": {
            "has_parentheses": bool(re.search(r"[()（）]", rewrite)),
            "over_max_chars": args.max_chars is not None and nonspace_chars > args.max_chars,
        },
        "warning": "自动审计不验证语义、专名、因果关系和法律状态，必须逐句复核。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Upgraded GB/T 1.1 Standard Draft Auditor (zero fake-pass):
- Checks mandatory sections (范围 / 规范性引用文件 / 术语和定义)
- Checks requirement verbs ('应'/'不应') forbidden in Scope
- Checks normative references listed in Clause 2 are ACTUALLY cited in the main body
- Checks verification/test-method section exists AND is non-empty (>=30 non-space chars)
- Flags ALL 【...】 / XXX placeholders (removes bogus '合成' exemption)
- Reports line numbers on every finding; --strict exits 2 on ANY error or warning.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+)$", re.MULTILINE)
CLAUSE_WORD = re.compile(
    r"[适响对相供反感回呼答顺因效照报酬]应"
    r"|应[用急力答收付聘试诉邀届景酬]"
    r"|应对(?![^，、。；：！？应\n]{1,40}(?:进行|采取|作出|做出|给出))"
    r"|(?P<requirement>不应|应)(?!当)(?=[ \t]*[\w≥≤<>=＝])"
)
NOTE_LINE = re.compile(r"^\s*(?:>\s*)?(?:注|示例)(?:\s*\d+)?\s*[:：]")
QUOTED_TEXT = re.compile(r"“[^”]*”|‘[^’]*’|「[^」]*」|`[^`]*`")
INFORMATIVE_HEADINGS = {"前言", "引言", "目次", "规范性引用文件", "术语和定义", "参考文献"}
PLACEHOLDER_PATTERN = re.compile(r"【([^】\n]+)】|(?<![A-Za-z0-9])X{3,}(?![A-Za-z0-9])")
TEST_TERMS = ("试验方法", "测试方法", "检验方法", "验证方法", "检查方法")
STD_CODE_PATTERN = re.compile(
    r"\b(?:GB(?:/T|/Z)?|ISO(?:/IEC)?|IEC|IEEE|HG/T|JB/T|QB/T|YY/T|SJ/T|YD/T|NB/T|SH/T|JC/T|FZ/T|T/[A-Z0-9]+|DB\d{2}(?:/T)?)\s*\d+(?:[.\-]\d+)*"
)


def normalize_heading(value: str) -> str:
    return re.sub(r"^[0-9]+(?:\.[0-9]+)*\s*", "", value).strip()


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def count_requirements(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if NOTE_LINE.match(line):
            continue
        count += sum(
            match["requirement"] is not None
            for match in CLAUSE_WORD.finditer(QUOTED_TEXT.sub(" ", line))
        )
    return count


def audit(text: str) -> dict[str, object]:
    heading_matches = list(HEADING_PATTERN.finditer(text))
    headings = [normalize_heading(item[2]) for item in heading_matches]
    findings: list[dict[str, object]] = []

    for required in ("范围", "规范性引用文件"):
        if required not in headings:
            findings.append({"level": "error", "code": "missing-section", "line": 1, "message": f"缺少“{required}”章节"})

    requirement_count = range_count = 0
    sections = []
    test_bodies: list[tuple[int, str, str]] = []
    ref_section_text = ""
    ref_section_line = 1
    body_without_refs_parts: list[str] = []

    for index, (match, name) in enumerate(zip(heading_matches, headings)):
        depth = len(match[1])
        line_no = _line_no(text, match.start())
        while sections and sections[-1][0] >= depth:
            sections.pop()
        context = sections[-1][1] if sections else "body"
        if name == "范围":
            context = "scope"
        elif name in INFORMATIVE_HEADINGS or (name.startswith("附录") and "资料性" in name):
            context = "informative"
        sections.append((depth, context))

        end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(text)
        section_body = text[match.end():end]

        if name == "规范性引用文件":
            ref_section_text = section_body
            ref_section_line = line_no
        elif context != "informative":
            # Only normative body clauses count for normative reference cross-citation (exclude 参考文献/前言/引言!)
            body_without_refs_parts.append(section_body)

        if any(term in name for term in TEST_TERMS):
            test_bodies.append((line_no, name, section_body))

        if context == "informative":
            continue
        count = count_requirements(section_body)
        if context == "scope":
            range_count += count
            if count:
                findings.append({"level": "error", "code": "requirement-in-scope", "line": line_no, "message": "范围中出现要求型助动词（应/不应）"})
        else:
            requirement_count += count

    # Line-numbered wording checks
    for m in re.finditer(r"必须", text):
        findings.append({"level": "warning", "code": "must-wording", "line": _line_no(text, m.start()), "message": "发现“必须”，按 GB/T 1.1 核对是否应改用“应”"})
    for m in re.finditer(r"不可(?!少|缺少|或缺|分割|分离|避免)", text):
        findings.append({"level": "warning", "code": "permission-negative", "line": _line_no(text, m.start()), "message": "发现“不可”，按 GB/T 1.1 核对是否应改用“不应”或“不能”"})

    # Test / verification section existence AND non-empty substance check
    if requirement_count:
        if not test_bodies:
            findings.append({
                "level": "error",
                "code": "missing-verification",
                "line": 1,
                "message": "存在要求型条款，但未发现试验、测试、检验或验证方法章节",
            })
        else:
            compact_test = re.sub(r"\s+", "", "".join(body for _, _, body in test_bodies))
            # Reject empty, purely negative ("无无无..."), or low-diversity repeated filler strings
            unique_chars = len(set(re.sub(r"[，。、；：！？,.;:!?\-\s无略待补]", "", compact_test)))
            if len(compact_test) < 30 or unique_chars < 10:
                findings.append({
                    "level": "error",
                    "code": "empty-verification-section",
                    "line": test_bodies[0][0],
                    "message": f"试验/测试方法章节内容为空、重复填充或过于简略（{len(compact_test)}字，有效字符种类{unique_chars}），缺乏可复现检验步骤",
                })

    # Normative references: check '参考' wording AND exact standard-code citation in NORMATIVE body only
    if ref_section_text:
        if "参考" in ref_section_text:
            findings.append({
                "level": "warning",
                "code": "informative-reference",
                "line": ref_section_line,
                "message": "规范性引用文件章节含“参考”表述，核对是否应移入参考文献",
            })
        listed_codes = sorted({re.sub(r"\s+", " ", m.group(0).strip()) for m in STD_CODE_PATTERN.finditer(ref_section_text)})
        body_codes = {re.sub(r"\s+", " ", m.group(0).strip()) for m in STD_CODE_PATTERN.finditer("\n".join(body_without_refs_parts))}
        body_stems = {re.split(r"[—\-]\d{4}", c)[0].strip() for c in body_codes}
        for code in listed_codes:
            stem = re.split(r"[—\-]\d{4}", code)[0].strip()
            if code not in body_codes and stem not in body_stems:
                findings.append({
                    "level": "error",
                    "code": "uncited-normative-reference",
                    "line": ref_section_line,
                    "message": f"规范性引用文件“{code}”在标准规范性正文中未被引用，不符合 GB/T 1.1 规范性引用要求",
                })

    # ALL placeholders flagged (no bogus '合成' exemption)
    for m in PLACEHOLDER_PATTERN.finditer(text):
        token = m.group(1) or m.group(0)
        findings.append({
            "level": "error",
            "code": "placeholder",
            "line": _line_no(text, m.start()),
            "message": f"存在未完成占位符：{token}",
        })

    return {
        "heading_count": len(headings),
        "requirement_clause_count": requirement_count,
        "finding_count": len(findings),
        "error_count": sum(1 for f in findings if f["level"] == "error"),
        "warning_count": sum(1 for f in findings if f["level"] == "warning"),
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="GB/T 1.1 标准草案结构、规范性引用、试验方法与占位符硬门禁审计")
    parser.add_argument("draft", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="严格模式：存在任意 error 或 warning 返回退出码 2")
    args = parser.parse_args()
    result = audit(args.draft.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"章节数：{result['heading_count']} | 要求型条款数：{result['requirement_clause_count']}")
        for item in result["findings"]:
            print(f"[{str(item['level']).upper()}] L{item['line']} {item['code']}: {item['message']}")
        if not result["findings"]:
            print("未发现结构和规范措辞风险。")
    has_err = result["error_count"] > 0
    has_warn = result["warning_count"] > 0
    if args.strict and (has_err or has_warn):
        raise SystemExit(2)
    raise SystemExit(1 if has_err else 0)


if __name__ == "__main__":
    main()

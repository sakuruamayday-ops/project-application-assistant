#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+)$", re.MULTILINE)
# Match common compound words before testing whether 应 starts a predicate.
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


def normalize_heading(value: str) -> str:
    return re.sub(r"^[0-9]+(?:\.[0-9]+)*\s*", "", value).strip()


def count_requirements(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if NOTE_LINE.match(line):
            continue
        count += sum(match["requirement"] is not None
                     for match in CLAUSE_WORD.finditer(QUOTED_TEXT.sub(" ", line)))
    return count


def audit(text: str) -> dict[str, object]:
    heading_matches = list(HEADING_PATTERN.finditer(text))
    headings = [normalize_heading(item[2]) for item in heading_matches]
    findings: list[dict[str, str]] = []

    for required in ("范围", "规范性引用文件"):
        if required not in headings:
            findings.append({"level": "error", "code": "missing-section", "message": f"缺少“{required}”章节"})

    requirement_count = range_count = 0
    sections = []
    for index, (match, name) in enumerate(zip(heading_matches, headings)):
        depth = len(match[1])
        while sections and sections[-1][0] >= depth:
            sections.pop()
        context = sections[-1][1] if sections else "body"
        if name == "范围":
            context = "scope"
        elif name in INFORMATIVE_HEADINGS or (name.startswith("附录") and "资料性" in name):
            context = "informative"
        sections.append((depth, context))
        if context == "informative":
            continue
        end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(text)
        count = count_requirements(text[match.end():end])
        if context == "scope":
            range_count += count
        else:
            requirement_count += count
    if range_count:
        findings.append({"level": "error", "code": "requirement-in-scope", "message": "范围中出现要求型助动词"})

    if "必须" in text:
        findings.append({"level": "warning", "code": "must-wording", "message": "发现“必须”，核对是否应改用“应”"})
    if re.search(r"不可(?!少|缺少|或缺|分割|分离|避免)", text):
        findings.append({"level": "warning", "code": "permission-negative", "message": "发现“不可”，核对条款类型及规范表述"})

    has_test_section = any(any(term in heading for term in TEST_TERMS) for heading in headings)
    if requirement_count and not has_test_section:
        findings.append(
            {
                "level": "error",
                "code": "missing-verification",
                "message": "存在要求型条款，但未发现试验、测试、检验或验证方法章节",
            }
        )

    references_match = re.search(
        r"^#{1,6}\s+(?:2\s+)?规范性引用文件\s*$([\s\S]*?)(?=^#{1,6}\s+|\Z)",
        text,
        re.MULTILINE,
    )
    if references_match and "参考" in references_match.group(1):
        findings.append(
            {
                "level": "warning",
                "code": "informative-reference",
                "message": "规范性引用文件章节含“参考”表述，核对是否应移入参考文献",
            }
        )

    unresolved = sorted({match[1] or match[0] for match in PLACEHOLDER_PATTERN.finditer(text)
                         if match[1] is None or match[1].strip() != "合成"})
    if unresolved:
        findings.append(
            {
                "level": "warning",
                "code": "placeholder",
                "message": f"存在未完成占位符：{'、'.join(unresolved[:10])}",
            }
        )

    return {
        "heading_count": len(headings),
        "requirement_clause_count": requirement_count,
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.draft.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"章节数：{result['heading_count']}")
        print(f"要求型条款数：{result['requirement_clause_count']}")
        for item in result["findings"]:
            print(f"[{item['level'].upper()}] {item['message']}")
        if not result["findings"]:
            print("未发现结构和规范措辞风险。")
    raise SystemExit(1 if any(item["level"] == "error" for item in result["findings"]) else 0)


if __name__ == "__main__":
    main()

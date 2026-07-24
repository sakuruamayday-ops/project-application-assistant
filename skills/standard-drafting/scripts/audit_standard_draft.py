#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
REQUIREMENT_PATTERN = re.compile(r"(?<!不)(应|不应)(?!当)")
TEST_TERMS = ("试验方法", "测试方法", "检验方法", "验证方法", "检查方法")


def normalize_heading(value: str) -> str:
    return re.sub(r"^[0-9]+(?:\.[0-9]+)*\s*", "", value).strip()


def audit(text: str) -> dict[str, object]:
    headings = [normalize_heading(item) for item in HEADING_PATTERN.findall(text)]
    findings: list[dict[str, str]] = []

    for required in ("范围", "规范性引用文件"):
        if not any(heading == required for heading in headings):
            findings.append({"level": "error", "code": "missing-section", "message": f"缺少“{required}”章节"})

    range_match = re.search(
        r"^#{1,6}\s+(?:1\s+)?范围\s*$([\s\S]*?)(?=^#{1,6}\s+|\Z)",
        text,
        re.MULTILINE,
    )
    if range_match and REQUIREMENT_PATTERN.search(range_match.group(1)):
        findings.append({"level": "error", "code": "requirement-in-scope", "message": "范围中出现要求型助动词"})

    if "必须" in text:
        findings.append({"level": "warning", "code": "must-wording", "message": "发现“必须”，核对是否应改用“应”"})
    if re.search(r"不可(?!少|缺少|或缺|分割|分离|避免)", text):
        findings.append({"level": "warning", "code": "permission-negative", "message": "发现“不可”，核对条款类型及规范表述"})

    requirement_count = len(REQUIREMENT_PATTERN.findall(text))
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

    unresolved = sorted(set(re.findall(r"【([^】]+)】", text)))
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

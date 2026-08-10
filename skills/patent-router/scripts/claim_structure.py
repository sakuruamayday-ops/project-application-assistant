#!/usr/bin/env python3
"""解析权利要求中的嵌套逻辑、择一关系、数值范围和马库什结构。"""

import re


BRACKET_PAIRS = {"(": ")", "（": "）", "[": "]", "【": "】", "{": "}"}


def nesting_depth(text):
    depth = 0
    maximum = 0
    stack = []
    for char in text:
        if char in BRACKET_PAIRS:
            stack.append(BRACKET_PAIRS[char])
            depth += 1
            maximum = max(maximum, depth)
        elif stack and char == stack[-1]:
            stack.pop()
            depth -= 1
    return maximum


def split_options(text):
    values = []
    buffer = []
    stack = []
    for char in text:
        if char in BRACKET_PAIRS:
            stack.append(BRACKET_PAIRS[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if not stack and char in "、,，或和及":
            value = "".join(buffer).strip(" ：:；;")
            if value:
                values.append(value)
            buffer = []
        else:
            buffer.append(char)
    value = "".join(buffer).strip(" ：:；;")
    if value:
        values.append(value)
    return [value for value in values if len(value) >= 1]


def alternative_groups(text, feature_id):
    groups = []
    patterns = [
        (
            r"选自(.{1,180}?)(?:中的|中)(一种或多种|至少一种|任一种|一种)",
            "selection",
        ),
        (r"(.{1,120}?)(?:之一|中的任一种)", "one_of"),
    ]
    for pattern, group_type in patterns:
        for index, match in enumerate(re.finditer(pattern, text), 1):
            options = split_options(match.group(1))
            if len(options) < 2:
                continue
            selector = match.group(2) if match.lastindex and match.lastindex >= 2 else "一种"
            groups.append(
                {
                    "group_id": f"{feature_id}-ALT{len(groups) + 1}",
                    "group_type": group_type,
                    "selector": selector,
                    "options": options,
                    "source_text": match.group(0),
                }
            )
    for match in re.finditer(r"[（(]([^（）()]{2,120}?(?:或|或者)[^（）()]{2,120}?)[）)]", text):
        options = re.split(r"或|或者", match.group(1))
        options = [value.strip() for value in options if value.strip()]
        if len(options) >= 2 and not any(
            set(options).issubset(set(group["options"])) for group in groups
        ):
            groups.append(
                {
                    "group_id": f"{feature_id}-ALT{len(groups) + 1}",
                    "group_type": "parenthetical_or",
                    "selector": "one_or_more_requires_context",
                    "options": options,
                    "source_text": match.group(0),
                }
            )
    return groups


def markush_groups(text, feature_id):
    groups = []
    plural = re.compile(
        r"((?:R\d+|X\d*|Y\d*|Z\d*)(?:\s*[、,，和及]\s*(?:R\d+|X\d*|Y\d*|Z\d*))+)"
        r"\s*各自独立地\s*(?:为|选自)(.{2,220}?)(?:；|。|$)"
    )
    for match in plural.finditer(text):
        variables = re.findall(r"R\d+|X\d*|Y\d*|Z\d*", match.group(1))
        options = split_options(match.group(2))
        groups.append(
            {
                "group_id": f"{feature_id}-M{len(groups) + 1}",
                "variables": variables,
                "independent_selection": True,
                "options": options,
                "source_text": match.group(0),
            }
        )
    singular = re.compile(
        r"\b(R\d+|X\d*|Y\d*|Z\d*)\s*(?:为|表示|选自)(.{2,160}?)(?:；|。|$)"
    )
    for match in singular.finditer(text):
        variable = match.group(1)
        if any(variable in group["variables"] for group in groups):
            continue
        options = split_options(match.group(2))
        if len(options) >= 2:
            groups.append(
                {
                    "group_id": f"{feature_id}-M{len(groups) + 1}",
                    "variables": [variable],
                    "independent_selection": False,
                    "options": options,
                    "source_text": match.group(0),
                }
            )
    return groups


def numeric_ranges(text):
    rows = []
    pattern = re.compile(
        r"(?<![A-Za-z])(?P<low>-?\d+(?:\.\d+)?)\s*(?:-|～|~|至|到)\s*"
        r"(?P<high>-?\d+(?:\.\d+)?)\s*(?P<unit>%|wt%|质量份|份|℃|°C|MPa|kPa|Pa|nm|μm|mm|cm|mL|L|h|min|s)?",
        re.I,
    )
    for match in pattern.finditer(text):
        rows.append(
            {
                "source_text": match.group(0),
                "lower": match.group("low"),
                "upper": match.group("high"),
                "unit": match.group("unit"),
            }
        )
    return rows


def analyze_feature(feature_id, text):
    alternatives = alternative_groups(text, feature_id)
    markush = markush_groups(text, feature_id)
    depth = nesting_depth(text)
    figures = []
    for value in re.findall(r"(?:附图|图)\s*\d+[A-Za-z]?|附图标记\s*\d+", text):
        normalized = re.sub(r"\s+", "", value)
        if normalized not in figures:
            figures.append(normalized)
    logic_type = (
        "MARKUSH"
        if markush
        else "ALTERNATIVE"
        if alternatives
        else "CONJUNCTION"
    )
    return {
        "logic_type": logic_type,
        "nesting_depth": depth,
        "alternative_groups": alternatives,
        "markush_groups": markush,
        "numeric_ranges": numeric_ranges(text),
        "figure_markers": figures,
        "requires_boundary_review": bool(markush or len(alternatives) > 1 or depth >= 3),
        "review_reasons": [
            reason
            for condition, reason in (
                (bool(markush), "包含马库什变量或独立择一取代基"),
                (len(alternatives) > 1, "同一技术特征包含多组择一关系"),
                (depth >= 3, "括号或限定关系嵌套达到三层以上"),
            )
            if condition
        ],
    }

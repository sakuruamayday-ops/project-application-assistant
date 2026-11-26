"""Parse and format RD/PS identifiers throughout the application."""

from __future__ import annotations

import re
from collections.abc import Iterator


FORM_LABELS = {"RD": "研发活动编号", "PS": "编号"}
_CODE = re.compile(r"(?<![A-Za-z_\d])(?:RD|PS)\d+(?![A-Za-z_\d])", re.IGNORECASE)
_FORM_LABEL = re.compile(r"(研发活动编号|编号)\s*[:：]?\s*\Z")


def iter_codes(text: str) -> Iterator[re.Match[str]]:
    return _CODE.finditer(text)


def parse_form_code(text: str, kind: str) -> str | None:
    for match in iter_codes(text):
        code = match[0].upper()
        if code.startswith(kind):
            label = _FORM_LABEL.search(text, 0, match.start())
            if label and label[1] == FORM_LABELS[kind]:
                return code
    return None


def number_width(count: int) -> int:
    return max(2, len(str(count)))


def number_code(prefix: str, index: int, count: int) -> str:
    return f"{prefix.upper()}{index:0{number_width(count)}d}"

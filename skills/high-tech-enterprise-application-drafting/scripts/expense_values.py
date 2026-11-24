"""Text representation of separate years in an existing expense table."""

import re


YEAR = r"(?:19|20)[0-9]{2}"
YEAR_SEPARATOR = "/"
MISSING_AMOUNT = "—"
EXPENSE_YEAR_PATTERN = re.compile(rf"(?<!\d)({YEAR})\s*年|年度\s*[:：]?\s*({YEAR})(?!\d)")
COMPACT_YEARS = re.compile(rf"^\s*({YEAR}(?:/{YEAR})+)\s*年度")


def expense_years(heading):
    compact = COMPACT_YEARS.match(heading)
    if compact:
        return tuple(compact[1].split(YEAR_SEPARATOR))
    single = EXPENSE_YEAR_PATTERN.search(heading)
    return (single[1] or single[2],) if single else ()


def expense_text(values):
    if len(values) == 1:
        return values[0]
    if not any(values):
        return ""
    return YEAR_SEPARATOR.join(value or MISSING_AMOUNT for value in values)


def expense_value(value, index, year_count):
    value = value.strip()
    if not value or year_count == 1:
        return value
    parts = value.split(YEAR_SEPARATOR)
    if len(parts) != year_count:
        return None
    return "" if parts[index] == MISSING_AMOUNT else parts[index]

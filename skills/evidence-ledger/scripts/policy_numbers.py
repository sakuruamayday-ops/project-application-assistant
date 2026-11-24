"""Check quantitative policy quotations against the cited local originals."""

from decimal import Decimal
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_runtime"))
from policy_original_text import read_policy_text


POLICY_TITLE = re.compile(r"管理.{0,4}办法|管理规定|工作指引|申报指南|条例|实施细则|实施办法|政策|申报通知|若干措施")
HAN_NUMBERS = "零〇一二两三四五六七八九十百千万亿"
LOCATOR = re.compile(rf"第([{HAN_NUMBERS}\d]+)条(?:\s*第([{HAN_NUMBERS}\d]+)项)?")
ARTICLE = re.compile(rf"(?m)^[ \t\u3000#*]*第([{HAN_NUMBERS}\d]+)条")
ITEM = re.compile(rf"(?m)^[ \t\u3000]*\(([{HAN_NUMBERS}\d]+)\)")
ARABIC = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
COUNT = rf"(?:{ARABIC}|[{HAN_NUMBERS}]+)"
AMOUNT_OR_UNIT = r"个百分点|万元|亿元|元|%|个月|年|月|日|天|分(?!钟|之|析|类|期|贝)|家|项|件|人|个|倍|台|吨|平方米"
NUMBERS = re.compile(rf"百分之{COUNT}|{COUNT}(?:{AMOUNT_OR_UNIT})")
NUMBER_PARTS = re.compile(rf"({COUNT})({AMOUNT_OR_UNIT})")
MONEY = {"元": 1, "万元": 10_000, "亿元": 100_000_000}
PERIODS = {"个月": "月", "天": "日"}
HAN_DIGITS = dict(zip("零一二三四五六七八九", range(10), strict=True)) | {"〇": 0, "两": 2}
HAN_PLACES = {"十": 10, "百": 100, "千": 1000}


def as_number(text):
    if text[0].isdigit():
        return Decimal(text.replace(",", ""))
    for unit, place in (("亿", 100_000_000), ("万", 10_000)):
        if unit in text:
            left, _, right = text.partition(unit)
            return (as_number(left) if left else 1) * place + (as_number(right) if right else 0)
    if all(char in HAN_DIGITS for char in text):
        return Decimal("".join(str(HAN_DIGITS[char]) for char in text))
    value = digit = 0
    for char in text:
        if char in HAN_DIGITS:
            digit = HAN_DIGITS[char]
        else:
            value += (digit or 1) * HAN_PLACES[char]
            digit = 0
    return Decimal(value + digit)


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)))


def fingerprint(text):
    result = {}
    for match in NUMBERS.finditer(normalize(text)):
        token = match.group()
        if token.startswith("百分之"):
            number, unit = token[3:], "%"
        else:
            number, unit = NUMBER_PARTS.fullmatch(token).groups()
        value = as_number(number)
        family = PERIODS.get(unit, unit)
        if unit in MONEY:
            family, value = "元", value * MONEY[unit]
        display = f"{value.normalize():f}%" if unit == "%" else token
        result.setdefault(family, []).append((value, display))
    return result


def differences(expected, actual, *, permit_unquoted=False):
    result = []
    if permit_unquoted and not actual:
        return result
    for unit in expected.keys() | actual.keys():
        left, right = expected.get(unit, []), actual.get(unit, [])
        if [value for value, _ in left] != [value for value, _ in right]:
            original = "、".join(name for _, name in left) or "无该项"
            quotation = "、".join(name for _, name in right) or "未列"
            result.append(f"原文 {original}、引用 {quotation}")
    return sorted(result)


def _located_text(raw, locator):
    marker = LOCATOR.search(unicodedata.normalize("NFKC", str(locator)))
    if not marker:
        return raw
    article, item = marker.groups()
    text = unicodedata.normalize("NFKC", raw)
    articles = list(ARTICLE.finditer(text))
    for index, match in enumerate(articles):
        if as_number(match[1]) != as_number(article):
            continue
        excerpt = text[match.start():articles[index + 1].start() if index + 1 < len(articles) else None]
        if not item:
            return excerpt
        entries = list(ITEM.finditer(excerpt))
        for position, entry in enumerate(entries):
            if as_number(entry[1]) == as_number(item):
                return excerpt[entry.start():entries[position + 1].start() if position + 1 < len(entries) else None]
    raise ValueError(f"原文缺引文位置「{locator}」")


def _original_fingerprint(source, record, read_source):
    internal = source.get("internal")
    path = internal.get("path") if isinstance(internal, dict) else None
    if not isinstance(path, str) or not path.strip():
        raise ValueError("缺政策原件 internal.path")
    text = read_source(Path(path).expanduser(), str(internal.get("sha256") or ""))
    locator = record.get("location") or internal.get("locator")
    located = normalize(_located_text(text, locator))
    excerpt = normalize(record.get("evidence_excerpt") or "").strip("。；;")
    parts = []
    position = 0
    for match in NUMBERS.finditer(excerpt):
        parts.extend([re.escape(excerpt[position:match.start()]), f"(?:{NUMBERS.pattern})"])
        position = match.end()
    parts.append(re.escape(excerpt[position:]))
    found = {match.group() for match in re.finditer("".join(parts), located)} if excerpt else set()
    if not found:
        raise ValueError(f"证据摘录未命中原文「{locator}」")
    fingerprints = [fingerprint(candidate) for candidate in sorted(found)]
    if any(differences(fingerprints[0], other) for other in fingerprints[1:]):
        raise ValueError(f"原文「{locator}」内摘录对应多组数值")
    return fingerprints[0]


def validate_policy_numbers(records, sources, blocks):
    @lru_cache(maxsize=None)
    def read_source(path, digest):
        if digest:
            with path.open("rb") as stream:
                # Use hashlib.update on chunks for supported Python 3.10 hosts.
                actual = hashlib.sha256()
                for chunk in iter(lambda: stream.read(65536), b""):
                    actual.update(chunk)
            if actual.hexdigest() != digest.removeprefix("sha256:").lower():
                raise ValueError(f"政策原件 SHA-256 不一致：{path.name}")
        return read_policy_text(path)

    errors = []
    checked = {}
    for record_id, record in records.items():
        if record.get("type") != "fact" or record.get("status") != "verified":
            continue
        ids = record.get("source")
        ids = ids if isinstance(ids, list) else [ids]
        quote = fingerprint(record.get("claim") or "")
        excerpt = fingerprint(record.get("evidence_excerpt") or "")
        if not quote and not excerpt:
            continue
        candidates = []
        for source_id in ids:
            if not isinstance(source_id, str) or source_id not in sources:
                continue
            source = sources[source_id]
            title = str(source.get("title") or source.get("file_name") or "")
            if (source.get("access_status") == "obtained"
                    and source.get("kind") in {"official_web", "public_web", "user_file", "knowledge_base"}
                    and (POLICY_TITLE.search(title) or LOCATOR.search(str(record.get("location") or "")))):
                candidates.append(source)
        issues = []
        for source in candidates:
            try:
                expected = _original_fingerprint(source, record, read_source)
            except (OSError, ValueError) as error:
                issues.append(f"来源 {source.get('id')} {error}")
                continue
            issue = differences(expected, quote) or differences(expected, excerpt)
            if not issue:
                checked[record_id] = expected
                break
            issues.extend(issue)
        else:
            errors.extend(f"证据 {record_id}：{issue}" for issue in dict.fromkeys(issues))

    for index, block in enumerate(blocks if isinstance(blocks, list) else [], 1):
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            continue
        ids = block.get("claim_ids")
        ids = ids if isinstance(ids, list) else [ids]
        references = [claim for claim in ids if isinstance(claim, str) and claim in checked]
        if not references:
            continue
        actual = fingerprint(block["text"])
        if len(ids) == 1:
            issues = differences(checked[references[0]], actual, permit_unquoted=True)
        else:
            supported = {}
            for claim in ids:
                if isinstance(claim, str) and claim in records:
                    for unit, values in fingerprint(records[claim].get("claim") or "").items():
                        supported.setdefault(unit, []).extend(values)
            policy_units = set().union(*(checked[claim] for claim in references))
            unexpected = {unit: values for unit, values in actual.items() if unit in policy_units
                          and any(value not in {entry[0] for entry in supported.get(unit, [])} for value, _ in values)}
            expected = {unit: supported[unit] for unit in unexpected}
            issues = differences(expected, unexpected)
        errors.extend(f"文档块 {index}：{issue}" for issue in issues)
    return errors

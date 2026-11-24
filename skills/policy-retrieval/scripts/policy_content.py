"""Verify policy identity and attachment links in the actual document text."""

from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_runtime"))
from policy_original_text import read_policy_text


ARTICLE = r"第[一二三四五六七八九十百零〇0-9]+条"
CLAUSE = re.compile(r"(?m)^[ \t\u3000#*]*(?:" + ARTICLE + r"|[一二三四五六七八九十]+[、.])")
DOC_NUMBER = re.compile(r"[\u4e00-\u9fff]{2,18}(?:函)?[〔\[（(【](?:19|20)\d{2}[〕\]）)】]\s*\d+\s*号")
ATTACHMENT_PREFIX = re.compile(r"(?:^|[-—])附件\s*\d*\s*[:：、.\-—]\s*")


def compact(text):
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", text))


def numbers_in(text):
    return {compact(match.group()) for match in DOC_NUMBER.finditer(unicodedata.normalize("NFKC", text))}


def heading_text(text):
    first_clause = CLAUSE.search(text)
    return text[:min(1600, first_clause.start())] if first_clause else text[:1600]


def short_title(title):
    title = title.strip()
    title = DOC_NUMBER.sub("", title, count=1).lstrip("-— ")
    marker = ATTACHMENT_PREFIX.search(title)
    return title[marker.end():] if marker else title


def missing_clauses(text, record):
    clauses = record.get("key_clauses", [])
    if not isinstance(clauses, list) or any(not isinstance(item, str) or not compact(item) for item in clauses):
        return ["关键条款 key_clauses 须为非空原文短句数组"]
    content = compact(text)
    return [f"原件缺登记的关键条款「{clause}」" for clause in clauses if compact(clause) not in content]


def body_differences(text, record, root):
    differences = missing_clauses(text, record)
    header = heading_text(text)
    title = str(record.get("title") or "").strip()
    if title and compact(title) not in compact(header):
        differences.append(f"正文标题应为「{title}」，正文开头为「{' '.join(header.split())[:90]}」")
    if not CLAUSE.search(text) and not record.get("key_clauses"):
        differences.append("正文未见条款、分节或可核对的关键条款")
    number = str(record.get("number") or "").strip()
    if not number:
        return differences

    found = numbers_in(header)
    if not found and record.get("number_source"):
        try:
            cover = heading_text(read_policy_text(root / record["number_source"]))
            if title and compact(title) not in compact(cover):
                differences.append(f"发文原件缺对应政策名称「{title}」")
            found = numbers_in(cover)
        except (TypeError, ValueError) as error:
            differences.append(str(error))
    if compact(number) not in found:
        actual = "、".join(sorted(found)) if found else "未见文号"
        differences.append(f"登记文号「{number}」，正文或随文发文原件为「{actual}」")
    return differences


def has_annex_heading(text, title):
    lines = [compact(line) for line in text[:1000].splitlines() if compact(line)]
    for index, line in enumerate(lines):
        candidate = re.sub(r"^附件[0-9]*", "", line) if not title.startswith("附件") else line
        for following in lines[index + 1:]:
            if not candidate or candidate == title or not title.startswith(candidate):
                break
            candidate += following
        if candidate == title:
            return True
    return False


def attachment_differences(text, attachment, body, record):
    title = short_title(attachment["title"])
    expected = compact(title)
    content = compact(text)
    differences = missing_clauses(text, attachment)
    marker = attachment.get("marker")
    # Some official forms print an annex number above an image-only title.
    numbered_form = (isinstance(marker, str) and re.fullmatch(r"附件\s*[1-9]\d*", marker)
                     and re.search(re.escape(compact(marker)) + r"(?!\d)", compact(heading_text(text)))
                     and attachment.get("key_clauses") and not differences)
    if not expected or (not has_annex_heading(text, expected) and not numbered_form):
        differences.append(f"附件标题应为「{title}」，附件开头为「{' '.join(text.split())[:80]}」")
    if expected and len(content) <= len(expected) and not numbered_form:
        differences.append("附件缺标题以外的内容")
    if body and expected and expected not in compact(body):
        differences.append(f"正文未列示附件「{title}」")
    found = numbers_in(heading_text(text))
    number = str(attachment.get("number") or record.get("number") or "").strip()
    if found and number and compact(number) not in found:
        differences.append(f"附件关联文号「{'、'.join(sorted(found))}」，正文登记文号「{number}」")

    # When the same annex is printed inside the body, verify the enclosed content too.
    if body and expected and record.get("attachments_expected") == 1:
        headings = re.findall(r"(?m)^[ \t\u3000#*]*" + re.escape(title) + r"[ \t\u3000]*$", body)
        if headings:
            included = compact(body[body.rfind(headings[-1]) + len(headings[-1]):])
            if len(included) >= 32 and included not in content:
                differences.append(f"附件「{title}」与正文所附条款内容不一致")
    return differences

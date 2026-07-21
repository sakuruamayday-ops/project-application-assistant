from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


POLICY_TERMS = (
    "政策",
    "通知",
    "办法",
    "细则",
    "指南",
    "条例",
    "规定",
    "目录",
    "评价标准",
    "认定标准",
    "建设标准",
    "意见",
    "工作指引",
    "实施方案",
    "申报要求",
)
NON_POLICY_TERMS = (
    "内部培训",
    "周报",
    "周总结",
    "证书",
    "专利",
    "考核表",
    "发票",
    "合同",
    "验收记录",
    "试验记录",
    "国家标准参与",
    "申报材料清单",
)
STATUS_PATTERNS = {
    "invalid": ("废止", "失效", "停止执行", "不再执行", "已取消"),
    "draft": ("征求意见", "征求意见稿", "草案", "送审稿"),
    "trial": ("试行", "暂行"),
    "revised": ("修订", "修正版", "修正案"),
}
SELF_REFERENCE_PATTERN = re.compile(r"本(?:办法|通知|规定|细则|文件|意见|方案|指南|政策|目录)")
INVALID_TERM_PATTERN = re.compile(r"废止|失效|停止执行|不再执行|终止执行")
REPLACEMENT_TERM_PATTERN = re.compile(r"替代|取代|代替")
QUOTED_TITLE_PATTERN = re.compile(r"《([^》]{2,160})》")
DATE_PATTERNS = (
    re.compile(r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"),
    re.compile(r"(?P<year>20\d{2})[-./](?P<month>\d{1,2})[-./](?P<day>\d{1,2})"),
)
YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
DOCUMENT_NUMBER_PATTERN = re.compile(
    r"(?:[\u4e00-\u9fffA-Za-z]{1,8})?[〔\[(（]20\d{2}[〕\])）]\d{1,5}号|"
    r"20\d{2}年第?\d{1,5}号"
)
VERSION_NOISE_PATTERN = re.compile(
    r"(?:20\d{2}(?:年度|年版|版|年)?|第[一二三四五六七八九十\d]+版|"
    r"征求意见稿?|草案|送审稿|修订版?|修正版|修正案|试行|暂行|正式版|最终版|最新版|现行版|"
    r"已废止|废止|失效|停止执行|不再执行|发布稿|印发稿|附件|副本|复件|copy)"
)
COPY_SUFFIX_PATTERN = re.compile(r"(?:\s*[-_]?\s*(?:副本|复件|copy)|\s*[（(]\d+[）)])+$", re.I)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="识别政策新旧版本并建立自动关联")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(os.environ.get("JIAOTANG_MANIFEST_PATH", Path.cwd() / "knowledge-migration/manifest.jsonl")),
    )
    parser.add_argument(
        "--content-db",
        type=Path,
        default=Path(os.environ.get("JIAOTANG_CONTENT_DATABASE", Path.cwd() / "knowledge-migration/knowledge_content.sqlite3")),
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def normalize_policy_title(title: str) -> str:
    value = unicodedata.normalize("NFKC", Path(title).stem).lower().strip()
    value = COPY_SUFFIX_PATTERN.sub("", value)
    value = DOCUMENT_NUMBER_PATTERN.sub("", value)
    value = VERSION_NOISE_PATTERN.sub("", value)
    value = re.sub(r"[\s·•,，。；;：:、/\\\-_—()（）\[\]【】《》<>]+", "", value)
    return value


def detect_policy_status(text: str) -> str:
    lowered = text.lower()
    for status in ("invalid", "draft", "trial", "revised"):
        if any(term.lower() in lowered for term in STATUS_PATTERNS[status]):
            return status
    return "active_candidate"


def extract_lifecycle_evidence(content: str) -> dict[str, object]:
    normalized = re.sub(r"[\t\r ]+", " ", content)
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[。！？；;])|\n+", normalized)]
    evidence_types: list[str] = []
    quotes: list[str] = []
    supersedes_titles: list[str] = []
    self_invalid = False

    for sentence in sentences:
        if not sentence or len(sentence) > 1200:
            continue
        quoted_titles = QUOTED_TITLE_PATTERN.findall(sentence)
        has_invalid_term = bool(INVALID_TERM_PATTERN.search(sentence))
        has_replacement_term = bool(REPLACEMENT_TERM_PATTERN.search(sentence))
        sentence_types: list[str] = []

        for self_reference in SELF_REFERENCE_PATTERN.finditer(sentence):
            following_text = sentence[self_reference.end() : self_reference.end() + 120]
            preceding_text = sentence[max(0, self_reference.start() - 8) : self_reference.start()]
            if preceding_text.endswith("自") and re.match(r"(?:施行|实施|生效)之日起", following_text):
                continue
            invalid_match = INVALID_TERM_PATTERN.search(following_text)
            if invalid_match and "《" not in following_text[: invalid_match.end()] and "原" not in following_text[: invalid_match.end()]:
                self_invalid = True
                sentence_types.append("self_invalid")
                break
        if quoted_titles and has_invalid_term:
            sentence_types.append("explicit_supersedes")
            supersedes_titles.extend(quoted_titles)
        if quoted_titles and has_replacement_term:
            sentence_types.append("explicit_replacement")
            supersedes_titles.extend(quoted_titles)

        if sentence_types:
            evidence_types.extend(sentence_types)
            if sentence not in quotes:
                quotes.append(sentence[:500])
        if len(quotes) >= 3:
            break

    return {
        "self_invalid": self_invalid,
        "evidence_types": sorted(set(evidence_types)),
        "evidence_quote": "\n".join(quotes),
        "supersedes_titles": list(dict.fromkeys(supersedes_titles)),
    }


def extract_dates(text: str) -> list[str]:
    values: set[str] = set()
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                value = datetime(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                    tzinfo=timezone.utc,
                )
                values.add(value.date().isoformat())
            except ValueError:
                continue
    return sorted(values)


def extract_years(text: str) -> list[int]:
    return sorted({int(year) for year in YEAR_PATTERN.findall(text)})


def title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    shorter, longer = sorted((left, right), key=len)
    containment = len(shorter) / len(longer) if shorter in longer else 0.0
    return max(containment, SequenceMatcher(None, left, right).ratio())


def is_policy_candidate(item: dict[str, object]) -> bool:
    name = str(item["name"])
    if name.startswith(".") or any(term in name for term in NON_POLICY_TERMS):
        return False
    return any(term in name for term in POLICY_TERMS)


def load_content(database_path: Path) -> dict[str, str]:
    connection = sqlite3.connect(database_path)
    try:
        return {
            source: content
            for source, content in connection.execute("SELECT source, content FROM documents")
        }
    finally:
        connection.close()


class DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def create_database(path: Path, rows: list[dict[str, object]]) -> None:
    with tempfile.TemporaryDirectory(prefix="jiaotang-policy-version-") as directory:
        temporary_path = Path(directory) / path.name
        connection = sqlite3.connect(temporary_path)
        try:
            connection.executescript(
                """
                CREATE TABLE policy_versions (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    version_group_id TEXT NOT NULL,
                    version_status TEXT NOT NULL,
                    policy_status TEXT NOT NULL,
                    detected_date TEXT,
                    detected_year INTEGER,
                    previous_source TEXT,
                    next_source TEXT,
                    latest_source TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    similarity REAL NOT NULL,
                    lifecycle_evidence_type TEXT,
                    lifecycle_evidence_quote TEXT,
                    lifecycle_evidence_source TEXT,
                    supersedes_titles TEXT NOT NULL,
                    superseded_by_source TEXT,
                    supersession_basis TEXT NOT NULL,
                    policy_status_source TEXT NOT NULL,
                    document_role TEXT NOT NULL,
                    sensitivity TEXT NOT NULL
                );
                CREATE INDEX policy_versions_group_idx ON policy_versions(version_group_id);
                CREATE INDEX policy_versions_latest_idx ON policy_versions(latest_source);
                CREATE VIRTUAL TABLE policy_versions_fts USING fts5(
                    title,
                    normalized_title,
                    source,
                    content='policy_versions',
                    content_rowid='id',
                    tokenize='unicode61'
                );
                """
            )
            columns = [
                "source",
                "title",
                "normalized_title",
                "version_group_id",
                "version_status",
                "policy_status",
                "detected_date",
                "detected_year",
                "previous_source",
                "next_source",
                "latest_source",
                "confidence",
                "similarity",
                "lifecycle_evidence_type",
                "lifecycle_evidence_quote",
                "lifecycle_evidence_source",
                "supersedes_titles",
                "superseded_by_source",
                "supersession_basis",
                "policy_status_source",
                "document_role",
                "sensitivity",
            ]
            connection.executemany(
                f"INSERT INTO policy_versions({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                ([row[column] for column in columns] for row in rows),
            )
            connection.execute(
                "INSERT INTO policy_versions_fts(rowid,title,normalized_title,source) "
                "SELECT id,title,normalized_title,source FROM policy_versions"
            )
            connection.commit()
        finally:
            connection.close()
        shutil.copy2(temporary_path, path)


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    output = (args.output or manifest_path.parent).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    content_by_source = load_content(args.content_db.expanduser().resolve())

    candidates: list[dict[str, object]] = []
    for item in manifest:
        if item["upload_action"] == "reference_duplicate" or not is_policy_candidate(item):
            continue
        content = content_by_source.get(str(item["relative_path"]), "")
        name = str(item["name"])
        name_dates = extract_dates(name)
        content_dates = extract_dates(content[:6000])
        dates = name_dates or content_dates
        name_years = extract_years(name)
        content_years = extract_years(content[:6000])
        years = name_years or content_years
        normalized = normalize_policy_title(str(item["name"]))
        if len(normalized) < 6:
            continue
        lifecycle = extract_lifecycle_evidence(content)
        filename_status = detect_policy_status(name)
        policy_status = "invalid" if lifecycle["self_invalid"] else filename_status
        if lifecycle["self_invalid"]:
            policy_status_source = "content_original_text"
        elif filename_status != "active_candidate":
            policy_status_source = "filename"
        else:
            policy_status_source = "none"
        candidates.append(
            {
                "source": item["relative_path"],
                "title": item["name"],
                "normalized_title": normalized,
                "policy_status": policy_status,
                "policy_status_source": policy_status_source,
                "lifecycle_evidence_type": "|".join(lifecycle["evidence_types"]),
                "lifecycle_evidence_quote": lifecycle["evidence_quote"],
                "supersedes_titles": lifecycle["supersedes_titles"],
                "detected_date": dates[-1] if dates else "",
                "detected_year": years[-1] if years else None,
                "modified_at": item["modified_at"],
                "document_role": item["document_role"],
                "sensitivity": item["sensitivity"],
                "top_category": item["top_category"],
            }
        )

    disjoint = DisjointSet(len(candidates))
    exact_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        exact_groups[(str(candidate["top_category"]), str(candidate["normalized_title"]))].append(index)
    for indexes in exact_groups.values():
        for index in indexes[1:]:
            disjoint.union(indexes[0], index)

    by_category: dict[str, list[int]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        by_category[str(candidate["top_category"])].append(index)
    fuzzy_links: dict[tuple[int, int], float] = {}
    for indexes in by_category.values():
        for position, left_index in enumerate(indexes):
            left = str(candidates[left_index]["normalized_title"])
            for right_index in indexes[position + 1 :]:
                right = str(candidates[right_index]["normalized_title"])
                similarity = title_similarity(left, right)
                if similarity >= 0.9 and min(len(left), len(right)) >= 8:
                    disjoint.union(left_index, right_index)
                    fuzzy_links[(min(left_index, right_index), max(left_index, right_index))] = similarity

    explicit_superseded_by: dict[int, int] = {}
    for newer_index, newer in enumerate(candidates):
        if newer["policy_status"] in {"draft", "invalid"}:
            continue
        for superseded_title in newer["supersedes_titles"]:
            normalized_target = normalize_policy_title(str(superseded_title))
            if len(normalized_target) < 6:
                continue
            matches = [
                older_index
                for older_index, older in enumerate(candidates)
                if older_index != newer_index
                and older["top_category"] == newer["top_category"]
                and title_similarity(normalized_target, str(older["normalized_title"])) >= 0.9
            ]
            if not matches:
                continue
            older_index = max(
                matches,
                key=lambda index: title_similarity(
                    normalized_target, str(candidates[index]["normalized_title"])
                ),
            )
            explicit_superseded_by[older_index] = newer_index
            disjoint.union(older_index, newer_index)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(candidates)):
        groups[disjoint.find(index)].append(index)

    rows: list[dict[str, object]] = []
    group_records: list[dict[str, object]] = []
    for indexes in groups.values():
        items = [candidates[index] for index in indexes]
        items.sort(
            key=lambda item: (
                str(item["detected_date"] or ""),
                int(item["detected_year"] or 0),
                str(item["modified_at"]),
                str(item["source"]),
            )
        )
        eligible = [item for item in items if item["policy_status"] not in {"invalid", "draft"}]
        explicit_latest_indexes = {
            newer_index
            for older_index, newer_index in explicit_superseded_by.items()
            if older_index in indexes and newer_index in indexes
        } - set(explicit_superseded_by)
        explicit_latest = [candidates[index] for index in explicit_latest_indexes]
        if explicit_latest:
            latest = max(explicit_latest, key=items.index)
        else:
            latest = eligible[-1] if eligible else items[-1]
        group_seed = f"{items[0]['top_category']}\n{items[0]['normalized_title']}"
        group_id = "pv_" + hashlib.sha256(group_seed.encode("utf-8")).hexdigest()[:16]
        exact = len({str(item["normalized_title"]) for item in items}) == 1
        confidence = "high" if exact else "medium"
        similarities = [
            title_similarity(str(item["normalized_title"]), str(latest["normalized_title"]))
            for item in items
        ]
        for position, item in enumerate(items):
            item_index = next(index for index in indexes if candidates[index] is item)
            superseding_index = explicit_superseded_by.get(item_index)
            superseding_item = candidates[superseding_index] if superseding_index is not None else None
            if len(items) == 1:
                version_status = "single"
            elif item["policy_status"] == "invalid":
                version_status = "invalid"
            elif item["policy_status"] == "draft":
                version_status = "draft"
            elif item is latest:
                version_status = "latest"
            elif superseding_item is not None:
                version_status = "superseded_confirmed"
            else:
                version_status = "superseded_candidate"
            if superseding_item is not None:
                evidence_type = "explicitly_superseded"
                evidence_quote = superseding_item["lifecycle_evidence_quote"]
                evidence_source = superseding_item["source"]
                supersession_basis = "explicit_original_text"
            else:
                evidence_type = item["lifecycle_evidence_type"]
                evidence_quote = item["lifecycle_evidence_quote"]
                evidence_source = item["source"] if evidence_quote else None
                if "explicit_supersedes" in str(evidence_type) or "explicit_replacement" in str(evidence_type):
                    supersession_basis = "explicit_original_text"
                elif version_status == "superseded_candidate":
                    supersession_basis = "chronology_inference"
                else:
                    supersession_basis = "not_applicable"
            rows.append(
                {
                    "source": item["source"],
                    "title": item["title"],
                    "normalized_title": item["normalized_title"],
                    "version_group_id": group_id,
                    "version_status": version_status,
                    "policy_status": item["policy_status"],
                    "detected_date": item["detected_date"] or None,
                    "detected_year": item["detected_year"],
                    "previous_source": items[position - 1]["source"] if position > 0 else None,
                    "next_source": items[position + 1]["source"] if position + 1 < len(items) else None,
                    "latest_source": latest["source"],
                    "confidence": confidence,
                    "similarity": similarities[position],
                    "lifecycle_evidence_type": evidence_type or None,
                    "lifecycle_evidence_quote": evidence_quote or None,
                    "lifecycle_evidence_source": evidence_source,
                    "supersedes_titles": json.dumps(item["supersedes_titles"], ensure_ascii=False),
                    "superseded_by_source": superseding_item["source"] if superseding_item else None,
                    "supersession_basis": supersession_basis,
                    "policy_status_source": item["policy_status_source"],
                    "document_role": item["document_role"],
                    "sensitivity": item["sensitivity"],
                }
            )
        group_records.append(
            {
                "version_group_id": group_id,
                "normalized_title": latest["normalized_title"],
                "latest_source": latest["source"],
                "confidence": confidence,
                "versions": [item["source"] for item in items],
                "explicit_supersession_links": [
                    {
                        "superseded_source": candidates[older_index]["source"],
                        "superseded_by_source": candidates[newer_index]["source"],
                        "evidence_quote": candidates[newer_index]["lifecycle_evidence_quote"],
                    }
                    for older_index, newer_index in explicit_superseded_by.items()
                    if older_index in indexes and newer_index in indexes
                ],
            }
        )

    rows.sort(key=lambda row: (str(row["version_group_id"]), str(row["detected_date"] or "")))
    fieldnames = [
        "version_group_id",
        "version_status",
        "policy_status",
        "confidence",
        "similarity",
        "lifecycle_evidence_type",
        "lifecycle_evidence_quote",
        "lifecycle_evidence_source",
        "supersedes_titles",
        "superseded_by_source",
        "supersession_basis",
        "policy_status_source",
        "detected_date",
        "detected_year",
        "title",
        "normalized_title",
        "source",
        "previous_source",
        "next_source",
        "latest_source",
        "document_role",
        "sensitivity",
    ]
    with (output / "policy_versions.csv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with (output / "policy_version_groups.jsonl").open("w", encoding="utf-8") as target:
        for group in group_records:
            target.write(json.dumps(group, ensure_ascii=False) + "\n")
    create_database(output / "policy_versions.sqlite3", rows)

    versions_by_source = {str(row["source"]): row for row in rows}
    with (output / "documents_with_versions.jsonl").open("w", encoding="utf-8") as target:
        for line in (output / "documents.jsonl").read_text(encoding="utf-8").splitlines():
            document = json.loads(line)
            version = versions_by_source.get(str(document["source"]))
            if version:
                for key in (
                    "version_group_id",
                    "version_status",
                    "policy_status",
                    "detected_date",
                    "detected_year",
                    "previous_source",
                    "next_source",
                    "latest_source",
                    "confidence",
                    "lifecycle_evidence_type",
                    "lifecycle_evidence_quote",
                    "lifecycle_evidence_source",
                    "supersedes_titles",
                    "superseded_by_source",
                    "supersession_basis",
                    "policy_status_source",
                ):
                    document[key] = version[key]
            target.write(json.dumps(document, ensure_ascii=False) + "\n")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_candidates": len(rows),
        "version_groups": len(group_records),
        "multi_version_groups": sum(1 for group in group_records if len(group["versions"]) > 1),
        "linked_documents": sum(len(group["versions"]) for group in group_records if len(group["versions"]) > 1),
        "confidence": dict(Counter(str(row["confidence"]) for row in rows)),
        "version_status": dict(Counter(str(row["version_status"]) for row in rows)),
        "policy_status": dict(Counter(str(row["policy_status"]) for row in rows)),
        "supersession_basis": dict(Counter(str(row["supersession_basis"]) for row in rows)),
        "evidence_backed_records": sum(1 for row in rows if row["lifecycle_evidence_quote"]),
    }
    (output / "policy_version_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

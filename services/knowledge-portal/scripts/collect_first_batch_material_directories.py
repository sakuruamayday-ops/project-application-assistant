#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber
import requests


DEFAULT_ROOT = Path("/Users/zsh/JiaotangData/知识库/10_政策与目录/三首项目/浙江省首批次新材料/应用示范指导目录")
PROJECT_ID = "11"
PROJECT_NAME = "浙江省首批次新材料"
EXPECTED_COUNTS = {2020: 153, 2021: 230, 2022: 276, 2023: 202, 2024: 329, 2025: 445}
SOURCES = {
    2020: {
        "url": "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3244/site/attach/0/797d9c7723e8483581b84598fd37f904.pdf",
        "document_number": "",
        "effective_date": "2020-09-05",
        "status": "superseded",
    },
    2021: {
        "url": "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web2945/site/attach/0/caa8ecb5480a4c5ca9e0541b0bcd9862.pdf",
        "document_number": "浙经信材料〔2021〕136号",
        "effective_date": "2021-09-05",
        "status": "superseded",
    },
    2022: {
        "url": "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3499/site/attach/0/c86a4a7607154743a8da9d45eb9beb47.pdf",
        "document_number": "浙经信材料〔2022〕166号",
        "effective_date": "2022-09-05",
        "status": "superseded",
    },
    2023: {
        "url": "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web1585/site/attach/0/44d49356c7d74ed5abecb81edec6ebed.pdf",
        "fallback_urls": [
            "https://jxt.zj.gov.cn/module/download/downfile.jsp?classid=0&filename=44d49356c7d74ed5abecb81edec6ebed.pdf",
        ],
        "document_number": "浙经信材料〔2023〕197号",
        "effective_date": "2023-09-05",
        "status": "superseded",
    },
    2024: {
        "url": "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3499/site/attach/0/84dc84797aee4adb92db302c8580bd48.pdf",
        "document_number": "浙经信材料〔2024〕182号",
        "effective_date": "2024-09-05",
        "status": "superseded",
    },
    2025: {
        "url": "https://zjjcmspublicnew.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/cms_files/filemanager/1571137/attach/20262/B10D90A5F1E3AFB7AB702233CB25A52B.pdf",
        "document_number": "浙经信材料〔2025〕234号",
        "effective_date": "2025-09-05",
        "status": "active",
    },
}

RECOVERED_NAME_OVERRIDES = {
    1: "正畸模型树脂",
    22: "35kV热塑性聚丙烯电缆料",
    64: "9,9-二[(4-羟乙氧基)苯基]芴（BPEF）",
    73: "高性能动力电池用阻燃泡绵",
    75: "超纯氨",
    77: "超纯四氯化硅",
    111: "引水工程用内外涂覆卷制焊钢管",
    154: "钨丝金刚石切割线",
    167: "三元正极材料（镍钴铝酸锂、镍钴锰酸锂）",
    168: "钠电池铁酸钠基三元正极材料",
    183: '高离子电导率β"-Al2O3电解质材料',
    189: "低缺陷高平坦度大尺寸半导体硅晶圆",
    196: "集成电路用抛光液",
}

DRAFT_FILES = {
    2025: {
        "filename": "浙江省重点新材料首批次应用示范指导目录（2025年版）_公示稿.pdf",
        "document_title": "浙江省重点新材料首批次应用示范指导目录（2025年版）（公示稿）",
        "validity_status": "draft_superseded",
        "superseded_by": "浙经信材料〔2025〕234号",
    }
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集并结构化浙江省首批次新材料应用示范指导目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--seed-dir", type=Path)
    return parser.parse_args()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(session: requests.Session, source: dict[str, Any], target: Path) -> bool:
    if target.is_file() and target.stat().st_size > 10_000:
        return True
    for url in [source["url"], *source.get("fallback_urls", [])]:
        try:
            response = session.get(url, timeout=120)
            response.raise_for_status()
        except requests.RequestException:
            continue
        if response.content.startswith(b"%PDF"):
            target.write_bytes(response.content)
            return True
    return False


def parse_directory(path: Path, year: int, source: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    top_category = ""
    major_category = ""
    sub_category = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for raw in table:
                    cells = [clean(cell) for cell in (raw or [])]
                    if len(cells) < 4:
                        cells.extend([""] * (4 - len(cells)))
                    marker = cells[0]
                    if marker in {"序号", "序 号"}:
                        continue
                    if not marker and rows and any(cells[1:]):
                        rows[-1]["material_name"] = clean(f"{rows[-1]['material_name']} {cells[1]}")
                        rows[-1]["performance_requirements"] = clean(
                            f"{rows[-1]['performance_requirements']} {cells[2]}"
                        )
                        rows[-1]["application_field"] = clean(
                            f"{rows[-1]['application_field']} {cells[3]}"
                        )
                        continue
                    if not marker.isdigit():
                        category = cells[1] or marker
                        if marker in {"先进基础材料", "关键战略材料", "前沿新材料"}:
                            top_category = marker
                            major_category = ""
                            sub_category = ""
                        elif re.fullmatch(r"[一二三四五六七八九十]+", marker):
                            major_category = category
                            sub_category = ""
                        elif re.fullmatch(r"[（(][一二三四五六七八九十]+[）)]", marker):
                            sub_category = category
                        continue
                    sequence = int(marker)
                    rows.append(
                        {
                            "project_id": PROJECT_ID,
                            "project_name": PROJECT_NAME,
                            "directory_year": year,
                            "sequence_no": sequence,
                            "material_name": cells[1],
                            "performance_requirements": cells[2],
                            "application_field": cells[3],
                            "top_category": top_category,
                            "major_category": major_category,
                            "sub_category": sub_category,
                            "document_title": f"浙江省重点新材料首批次应用示范指导目录（{year}年版）",
                            "document_number": source["document_number"],
                            "effective_date": source["effective_date"],
                            "validity_status": source["status"],
                            "replacement_year": year + 1 if year < max(SOURCES) else None,
                            "source_url": source["url"],
                            "source_tier": "official",
                        }
                    )
    deduplicated = {row["sequence_no"]: row for row in rows}
    ordered = [deduplicated[key] for key in sorted(deduplicated)]
    expected = EXPECTED_COUNTS[year]
    if len(ordered) != expected or [row["sequence_no"] for row in ordered] != list(range(1, expected + 1)):
        raise RuntimeError(f"{year}版目录预期{expected}项连续序号，实际{len(ordered)}项")
    return ordered


def normalized_name(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")


def parse_recovered_search_index(
    path: Path,
    year: int,
    source: dict[str, Any],
    known_material_names: list[str],
) -> list[dict[str, Any]]:
    indexed_lines: dict[int, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^L(\d+)@P\d+:\s?(.*)$", raw_line)
        if match:
            indexed_lines[int(match.group(1))] = match.group(2)
    if not indexed_lines or sorted(indexed_lines) != list(range(max(indexed_lines) + 1)):
        raise RuntimeError(f"{year}版官方搜索索引全文不连续")
    lines = [indexed_lines[index] for index in range(max(indexed_lines) + 1)]
    chunks: dict[int, list[str]] = {}
    cursor = 0
    expected = EXPECTED_COUNTS[year]
    for sequence in range(1, expected + 1):
        marker = re.compile(rf"^{sequence}(?:\s+(.+))?$")
        found = next(
            ((index, match) for index in range(cursor, len(lines)) if (match := marker.match(lines[index].strip()))),
            None,
        )
        if found is None:
            raise RuntimeError(f"{year}版官方搜索索引缺少序号{sequence}")
        index, match = found
        next_index = len(lines)
        if sequence < expected:
            next_marker = re.compile(rf"^{sequence + 1}(?:\s+.*)?$")
            next_index = next(
                (candidate for candidate in range(index + 1, len(lines)) if next_marker.match(lines[candidate].strip())),
                len(lines),
            )
        chunks[sequence] = ([match.group(1)] if match.group(1) else []) + lines[index + 1 : next_index]
        cursor = index + 1

    candidates = sorted(set(known_material_names), key=lambda value: len(normalized_name(value)), reverse=True)
    entries: list[dict[str, Any]] = []
    for sequence, chunk in chunks.items():
        material_name = RECOVERED_NAME_OVERRIDES.get(sequence, "")
        if not material_name:
            prefix = normalized_name("".join(chunk[:8]))
            material_name = next((name for name in candidates if prefix.startswith(normalized_name(name))), "")
        if not material_name:
            parts = []
            for line in chunk[:5]:
                value = line.strip()
                if not value or value.startswith("序号 材料名称"):
                    break
                if re.search(
                    r"[≥≤＞＜%=℃]|\d+(?:\.\d+)?(?:MPa|GPa|kPa|ppm|ppb|mm|cm|nm|μm|g/|kg/|W/|kV|N/|wt)",
                    value,
                    re.IGNORECASE,
                ):
                    break
                parts.append(value)
            material_name = "".join(parts)
        if not material_name or len(material_name) > 80:
            raise RuntimeError(f"{year}版序号{sequence}材料名称提取异常：{material_name}")
        entries.append(
            {
                "project_id": PROJECT_ID,
                "project_name": PROJECT_NAME,
                "directory_year": year,
                "sequence_no": sequence,
                "material_name": material_name,
                "performance_requirements": "",
                "application_field": "",
                "top_category": "",
                "major_category": "",
                "sub_category": "",
                "document_title": f"浙江省重点新材料首批次应用示范指导目录（{year}年版）",
                "document_number": source["document_number"],
                "effective_date": source["effective_date"],
                "validity_status": source["status"],
                "replacement_year": year + 1 if year < max(SOURCES) else None,
                "source_url": source["url"],
                "source_tier": "official_search_index",
                "recovery_scope": "material_name_only",
            }
        )
    return entries


def write_markdown(path: Path, entries: list[dict[str, Any]]) -> None:
    first = entries[0]
    lines = [
        f"# {first['document_title']}",
        "",
        f"- 文号：{first['document_number'] or '原文未标注文号'}",
        f"- 生效日期：{first['effective_date']}",
        f"- 状态：{first['validity_status']}",
        f"- 官方来源：{first['source_url']}",
        f"- 结构化条目：{len(entries)}项",
        f"- 关联项目：{PROJECT_NAME}",
        "",
        "| 序号 | 材料名称 | 分类 | 性能要求 | 应用领域 |",
        "|---:|---|---|---|---|",
    ]
    for row in entries:
        category = " / ".join(
            value for value in (row["top_category"], row["major_category"], row["sub_category"]) if value
        )
        values = [
            str(row["sequence_no"]),
            row["material_name"],
            category,
            row["performance_requirements"],
            row["application_field"],
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "JiaotangKnowledgeCollector/1.1", "Referer": "https://jxt.zj.gov.cn/"})
    all_entries: list[dict[str, Any]] = []
    versions: list[dict[str, Any]] = []
    archived_drafts: list[dict[str, Any]] = []
    missing: list[int] = []
    deferred_recovered: list[tuple[int, dict[str, Any], Path, Path, dict[str, Any]]] = []
    for year, source in SOURCES.items():
        year_dir = args.output / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)
        target = year_dir / f"浙江省重点新材料首批次应用示范指导目录（{year}年版）.pdf"
        seed = args.seed_dir / f"{year}.pdf" if args.seed_dir else None
        if seed and seed.is_file() and seed.stat().st_size > 10_000:
            shutil.copy2(seed, target)
        available = download(session, source, target)
        version = {
            "year": year,
            "document_title": f"浙江省重点新材料首批次应用示范指导目录（{year}年版）",
            "document_number": source["document_number"],
            "effective_date": source["effective_date"],
            "validity_status": source["status"],
            "replacement_year": year + 1 if year < max(SOURCES) else None,
            "source_url": source["url"],
            "expected_entries": EXPECTED_COUNTS[year],
            "local_file_available": available,
        }
        if available:
            entries = parse_directory(target, year, source)
            all_entries.extend(entries)
            write_markdown(year_dir / f"浙江省重点新材料首批次应用示范指导目录（{year}年版）.md", entries)
            version["parsed_entries"] = len(entries)
        else:
            recovered_text = year_dir / f"浙江省重点新材料首批次应用示范指导目录（{year}年版）_官方搜索索引全文.txt"
            if recovered_text.is_file():
                version["parsed_entries"] = 0
                version["search_index_text_available"] = True
                deferred_recovered.append((year, source, recovered_text, year_dir, version))
            else:
                missing.append(year)
                version["parsed_entries"] = 0
                (year_dir / f"浙江省重点新材料首批次应用示范指导目录（{year}年版）_来源说明.md").write_text(
                    "\n".join(
                        (
                            f"# 浙江省重点新材料首批次应用示范指导目录（{year}年版）",
                            "",
                            f"- 文号：{source['document_number']}",
                            f"- 生效日期：{source['effective_date']}",
                            f"- 官方附件：{source['url']}",
                            f"- 应有条目：{EXPECTED_COUNTS[year]}项",
                            "- 当前状态：官方旧附件下载端返回失效，已保留官方链接和版本链，等待恢复原始副本后自动补建条目。",
                            f"- 关联项目：{PROJECT_NAME}",
                        )
                    )
                    + "\n",
                    encoding="utf-8",
                )
        versions.append(version)
        draft = DRAFT_FILES.get(year)
        if draft:
            draft_path = year_dir / draft["filename"]
            if draft_path.is_file():
                with pdfplumber.open(draft_path) as pdf:
                    page_count = len(pdf.pages)
                archived_drafts.append(
                    {
                        "year": year,
                        "document_title": draft["document_title"],
                        "validity_status": draft["validity_status"],
                        "superseded_by": draft["superseded_by"],
                        "local_file": str(draft_path),
                        "page_count": page_count,
                        "sha256": file_sha256(draft_path),
                        "retrieval_policy": "archive_only",
                    }
                )
    known_material_names = [entry["material_name"] for entry in all_entries]
    for year, source, recovered_text, year_dir, version in deferred_recovered:
        entries = parse_recovered_search_index(recovered_text, year, source, known_material_names)
        all_entries.extend(entries)
        write_markdown(year_dir / f"浙江省重点新材料首批次应用示范指导目录（{year}年版）.md", entries)
        version["parsed_entries"] = len(entries)
        (year_dir / f"浙江省重点新材料首批次应用示范指导目录（{year}年版）_来源说明.md").write_text(
            "\n".join(
                (
                    f"# 浙江省重点新材料首批次应用示范指导目录（{year}年版）来源说明",
                    "",
                    f"- 官方附件：{source['url']}",
                    f"- 官方文号：{source['document_number']}",
                    f"- 已恢复：官方搜索索引完整文本及{len(entries)}项材料名称。",
                    "- 原始PDF：官方旧附件下载端当前失效，暂未恢复本地原件。",
                    "- 结构化边界：性能要求和应用领域保留在官方搜索索引全文中，材料名表不补造字段。",
                )
            )
            + "\n",
            encoding="utf-8",
        )
    all_entries.sort(key=lambda entry: (entry["directory_year"], entry["sequence_no"]))
    jsonl = args.output / "浙江省重点新材料首批次应用示范指导目录_结构化条目.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for entry in all_entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    metadata = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_id": PROJECT_ID,
        "project_name": PROJECT_NAME,
        "versions": versions,
        "archived_drafts": archived_drafts,
        "parsed_entries": len(all_entries),
        "missing_versions": missing,
        "current_version": 2025,
    }
    (args.output / "浙江省重点新材料首批次应用示范指导目录_版本关系.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()

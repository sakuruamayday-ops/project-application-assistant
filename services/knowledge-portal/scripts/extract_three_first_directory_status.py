#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import fitz


DEFAULT_PDF = Path(
    "/Users/zsh/JiaotangData/知识库/10_政策与目录/首台套/"
    "关于印发浙江省首台（套）产品推广应用指导目录（2026）.pdf"
)
DEFAULT_OUTPUT = Path(
    "/Users/zsh/JiaotangData/知识库/50_名单与对标/三首项目/_结构化数据/"
    "三首项目目录状态.jsonl"
)
SOURCE_URL = "https://jxt.zj.gov.cn/"
SOURCE_TITLE = "关于印发浙江省首台（套）产品推广应用指导目录（2026年版）的通知"
PROJECTS = {
    "首台（套）装备": ("12", "浙江省制造业首台（套）装备"),
    "首批次新材料": ("11", "浙江省首批次新材料"),
    "首版次软件": ("10", "浙江省首版次软件产品"),
}


def compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def section_name(value: object) -> str:
    normalized = compact(value)
    if "首台" in normalized and "装备" in normalized:
        return "首台（套）装备"
    if "首批次" in normalized and "材料" in normalized:
        return "首批次新材料"
    if "首版次" in normalized and "软件" in normalized:
        return "首版次软件"
    return ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="提取浙江省三首推广目录及计划退出时间")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def extract(pdf: Path) -> list[dict[str, object]]:
    current_section = ""
    rows: list[dict[str, object]] = []
    document = fitz.open(pdf)
    try:
        for page_number, page in enumerate(document, start=1):
            for table in page.find_tables().tables:
                for row in table.extract():
                    first = compact(row[0] if row else "")
                    detected = section_name(first)
                    if detected:
                        current_section = detected
                        continue
                    if first == "序号" or not re.fullmatch(r"\d+", first):
                        continue
                    if not current_section or len(row) < 6:
                        continue
                    product_name = compact(row[1])
                    enterprise_name = compact(row[2])
                    exit_time = compact(row[5])
                    if not product_name or not enterprise_name:
                        continue
                    project_id, project_name = PROJECTS[current_section]
                    rows.append(
                        {
                            "sequence": int(first),
                            "enterprise_name": enterprise_name,
                            "project_id": project_id,
                            "project_name": project_name,
                            "year": 2026,
                            "product_name": product_name,
                            "recognition_tier": compact(row[4]),
                            "product_category": compact(row[6]) if len(row) > 6 else "",
                            "province": "浙江省",
                            "city": "",
                            "county": compact(row[3]),
                            "list_status": "scheduled_directory_exit",
                            "event_date": exit_time,
                            "source_title": SOURCE_TITLE,
                            "source_url": SOURCE_URL,
                            "source_tier": "official",
                            "evidence_semantics": "promotion_directory_row",
                            "confidence": "product_level",
                            "source_page": page_number,
                            "source_file": str(pdf),
                        }
                    )
    finally:
        document.close()
    return rows


def main() -> None:
    args = parse_args()
    if not args.pdf.is_file():
        raise SystemExit(f"目录原文不存在：{args.pdf}")
    rows = extract(args.pdf)
    if not rows:
        raise SystemExit("未从目录原文提取到产品记录")
    missing_exit = [row for row in rows if not row["event_date"]]
    if missing_exit:
        raise SystemExit(f"存在{len(missing_exit)}条记录缺少退出目录时间")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = Counter(str(row["project_name"]) for row in rows)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "records": len(rows),
                "exit_time_coverage": 1.0,
                "projects": counts,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

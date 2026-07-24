#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber
import requests
from bs4 import BeautifulSoup


DEFAULT_OUTPUT = Path("/Volumes/知识库/_云端知识库/50_名单与对标/三首项目/_结构化数据")
SOURCES = {
    "2019_first_set_publicity": {
        "url": "https://www.sohu.com/a/258710962_99919023",
        "filename": "2019年度浙江省装备制造业重点领域首台套产品公示名单_公开转载.html",
    },
    "2020_first_set_final": {
        "url": "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web2734/site/attach/0/01dbba3940b04fd5b4c1f89da6032567.pdf",
        "filename": "2020年度浙江省装备制造业重点领域首台套产品名单_官方.pdf",
    },
    "2021_first_batch_reward": {
        "url": "http://qyfw.87188718.com//Upload/20220129/20220129160114087.doc",
        "filename": "2021年浙江省重点首批次新材料认定奖励名单_公开档案.doc",
    },
    "2021_first_set_final": {
        "url": "http://qyfw.87188718.com//Upload/20220129/20220129160057357.doc",
        "filename": "2021年度浙江省首台套装备名单_公开档案.doc",
    },
    "2021_first_set_standard": {
        "url": "http://qyfw.87188718.com//Upload/20220129/20220129160119183.doc",
        "filename": "2021年度浙江省首台套装备清单引导标准认定名单_公开档案.doc",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集三首项目官方与公开补充附件")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-cache", type=Path)
    return parser.parse_args()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def download(session: requests.Session, url: str, path: Path) -> None:
    response = session.get(url, timeout=120)
    response.raise_for_status()
    path.write_bytes(response.content)


def base_record(**values: Any) -> dict[str, Any]:
    row = {
        "project_id": "",
        "project_name": "",
        "year": None,
        "enterprise_name": "",
        "product_name": "",
        "recognition_tier": "",
        "product_category": "",
        "province": "浙江省",
        "city": "",
        "county": "",
        "list_status": "",
        "source_title": "",
        "source_url": "",
        "source_tier": "",
        "confidence": "product_level",
        "evidence_semantics": "annual_list_row",
    }
    row.update(values)
    return row


def parse_2019_first_set(path: Path) -> list[dict[str, Any]]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("2019首台套公开表格未找到")
    records = []
    for tr in table.find_all("tr"):
        cells = [clean(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        records.append(
            base_record(
                project_id="12",
                project_name="浙江省制造业首台（套）装备",
                year=2019,
                enterprise_name=cells[2],
                product_name=cells[1],
                recognition_tier=f"{cells[3]}首台（套）" if "首台" not in cells[3] else cells[3],
                list_status="publicity",
                source_title="2019年度浙江省装备制造业重点领域首台（套）产品公示名单",
                source_url=SOURCES["2019_first_set_publicity"]["url"],
                source_tier="public_repost",
            )
        )
    if len(records) != 107:
        raise RuntimeError(f"2019首台套预期107条，实际{len(records)}条")
    return records


def parse_2020_first_set(path: Path) -> list[dict[str, Any]]:
    records = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for cells in table:
                    if len(cells) < 6 or not clean(cells[0]).isdigit():
                        continue
                    records.append(
                        base_record(
                            project_id="12",
                            project_name="浙江省制造业首台（套）装备",
                            year=2020,
                            enterprise_name=clean(cells[2]),
                            product_name=clean(cells[1]),
                            product_category=clean(cells[3]),
                            recognition_tier=clean(cells[4]),
                            county=clean(cells[5]),
                            list_status="final_recognition",
                            source_title="关于公布2020年度浙江省装备制造业重点领域首台（套）产品名单的通知",
                            source_url=SOURCES["2020_first_set_final"]["url"],
                            source_tier="official",
                        )
                    )
    if len(records) != 162:
        raise RuntimeError(f"2020首台套预期162条，实际{len(records)}条")
    return records


def doc_text(path: Path) -> str:
    return subprocess.check_output(["textutil", "-convert", "txt", "-stdout", str(path)]).decode("utf-8", "ignore")


def parse_2021_first_batch(path: Path) -> list[dict[str, Any]]:
    lines = [clean(line) for line in doc_text(path).splitlines() if clean(line)]
    start = lines.index("1")
    records = []
    cursor = start
    while cursor + 3 < len(lines) and lines[cursor].isdigit():
        sequence = int(lines[cursor])
        product_name, enterprise_name, region = lines[cursor + 1 : cursor + 4]
        cursor += 4
        tier = ""
        if cursor < len(lines) and not lines[cursor].isdigit():
            tier = lines[cursor]
            cursor += 1
        records.append(
            base_record(
                project_id="11",
                project_name="浙江省首批次新材料",
                year=2021,
                enterprise_name=enterprise_name,
                product_name=product_name,
                recognition_tier=tier,
                county=region,
                list_status="final_recognition_reward",
                source_title="2021年浙江省重点首批次新材料认定奖励名单",
                source_url=SOURCES["2021_first_batch_reward"]["url"],
                source_tier="public_archive",
            )
        )
        if sequence != len(records):
            raise RuntimeError("2021首批次序号不连续")
    if len(records) != 13:
        raise RuntimeError(f"2021重点首批次预期13条，实际{len(records)}条")
    return records


def parse_2021_first_set(path: Path) -> list[dict[str, Any]]:
    parts = [clean(item) for item in doc_text(path).split("\x07") if clean(item)]
    start = parts.index("1")
    values = parts[start:]
    if len(values) % 6:
        raise RuntimeError("2021首台套主名单字段数不能被6整除")
    records = []
    for cursor in range(0, len(values), 6):
        sequence, product, enterprise, category, tier, region = values[cursor : cursor + 6]
        if int(sequence) != len(records) + 1:
            raise RuntimeError("2021首台套主名单序号不连续")
        records.append(
            base_record(
                project_id="12",
                project_name="浙江省制造业首台（套）装备",
                year=2021,
                enterprise_name=enterprise,
                product_name=product,
                product_category=category,
                recognition_tier=tier,
                county=region,
                list_status="final_recognition",
                source_title="2021年度浙江省首台（套）装备名单",
                source_url=SOURCES["2021_first_set_final"]["url"],
                source_tier="public_archive",
            )
        )
    if len(records) != 235:
        raise RuntimeError(f"2021首台套主名单预期235条，实际{len(records)}条")
    return records


def parse_2021_first_set_standard(path: Path) -> list[dict[str, Any]]:
    lines = [clean(line) for line in doc_text(path).splitlines() if clean(line)]
    start = lines.index("1")
    values = lines[start:]
    records = []
    cursor = 0
    while cursor + 5 < len(values):
        sequence = values[cursor]
        if not sequence.isdigit() or int(sequence) != len(records) + 1:
            break
        product, enterprise, region, tier, standard_no = values[cursor + 1 : cursor + 6]
        records.append(
            base_record(
                project_id="12",
                project_name="浙江省制造业首台（套）装备",
                year=2021,
                enterprise_name=enterprise,
                product_name=product,
                product_category=f"清单引导标准序号{standard_no}",
                recognition_tier=tier,
                county=region,
                list_status="standard_guided_recognition",
                source_title="2021年度浙江省首台（套）装备清单引导标准认定名单",
                source_url=SOURCES["2021_first_set_standard"]["url"],
                source_tier="public_archive",
            )
        )
        cursor += 6
    if len(records) != 8:
        raise RuntimeError(f"2021首台套清单引导标准预期8条，实际{len(records)}条")
    return records


def main() -> None:
    args = parse_args()
    source_cache = args.source_cache or args.output / "_原始采集" / "官方与公开补充"
    source_cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "JiaotangKnowledgeCollector/1.1"
    paths: dict[str, Path] = {}
    for key, source in SOURCES.items():
        path = source_cache / source["filename"]
        download(session, source["url"], path)
        paths[key] = path
    records = [
        *parse_2019_first_set(paths["2019_first_set_publicity"]),
        *parse_2020_first_set(paths["2020_first_set_final"]),
        *parse_2021_first_batch(paths["2021_first_batch_reward"]),
        *parse_2021_first_set(paths["2021_first_set_final"]),
        *parse_2021_first_set_standard(paths["2021_first_set_standard"]),
    ]
    output = args.output / "三首项目官方公开补充.jsonl"
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    metadata = {
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "records": len(records),
        "counts": {
            "2019_first_set_publicity": 107,
            "2020_first_set_final": 162,
            "2021_first_batch_reward": 13,
            "2021_first_set_final": 235,
            "2021_first_set_standard": 8,
        },
        "sources": SOURCES,
        "output": str(output),
    }
    (source_cache / "采集元数据.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()

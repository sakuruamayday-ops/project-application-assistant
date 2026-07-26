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

import requests
from bs4 import BeautifulSoup


DEFAULT_OUTPUT = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/三首项目/_结构化数据")
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
    "2024_first_batch_publicity": {
        "url": "http://www.zjpia.net/info.asp?id=34148",
        "filename": "2024年度浙江省首批次新材料认定结果公示_行业协会转载.html",
    },
    "2025_first_version_final": {
        "url": "https://zj87.jxt.zj.gov.cn/webapi/portal/getNewsDetail?ID=293873",
        "filename": "2025年浙江省首版次软件产品应用推广指导目录_官方.json",
    },
}

FIRST_BATCH_2021_NON_REWARD = (
    (1, "中钢新型材料股份有限公司", "核石墨", "技术水平国际领先或国际先进，打破国际垄断，实现重点领域同准替代且在知名用户应用"),
    (2, "浙江陶特容器科技股份有限公司", "合金钢高压无缝Y瓶", "技术水平国际领先或国际先进，打破国际垄断，实现重点领域同准替代且在知名用户应用"),
    (3, "浙江道明光电科技有限公司", "软包锂电池用铝塑复合膜", "技术水平国际领先或国际先进，打破国际垄断，实现重点领域同准替代且在知名用户应用"),
    (4, "浙江新纳陶瓷新材有限公司", "半导体刻蚀设备用大尺寸氧化铝陶瓷", "技术水平国际领先或国际先进，打破国际垄断，实现重点领域同准替代且在知名用户应用"),
    (5, "浙江格尔泰斯环保特材科技股份有限公司", "PTFE亲水膜", "技术水平国际领先或国际先进，打破国际垄断，实现重点领域同准替代且在知名用户应用"),
    (6, "浙江和谐光催化科技有限公司", "建筑外表面用自清洁涂料", "技术水平国际领先或国际先进，打破国际垄断，实现重点领域同准替代且在知名用户应用"),
    (7, "中科金绮新材料科技有限公司", "特种高性能PBO纤维", "技术水平国际领先或国际先进，打破国际垄断，实现重点领域同准替代且在知名用户应用"),
    (8, "振石集团华美新材料有限公司", "高阻燃高强度玻纤增强聚酯基复合材料", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (9, "兰溪泛翌精细陶瓷有限公司", "高性能碳化硼防弹陶瓷", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (10, "中浮新材料科技股份有限公司", "深海浮力材料", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (11, "浙江中科磁业股份有限公司", "高性能新型钕磁体", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (12, "浙江立泰复合材料股份有限公司", "LT02型武装直升机防护装甲", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (13, "浙江信汇新材料股份有限公司", "卤代丁基橡胶", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (14, "浙江博瑞电子科技有限公司", "高纯氯化氢", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (15, "浙江博瑞电子科技有限公司", "高纯氯气", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (16, "浙江凯圣氟化学有限公司", "电子级硫酸", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (17, "浙江凯圣氟化学有限公司", "电子级硝酸", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (18, "浙江凯圣氟化学有限公司", "电子级氨水", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (19, "浙江凯圣氟化学有限公司", "电子级BOE", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (20, "杭州千石科技有限公司", "注塑钐铁氮稀土永磁复合材料", "技术水平国内领先，打破国际垄断，实现重点领域降准替代且在知名用户应用"),
    (21, "巨石集团有限公司", "耐老化低毛羽通用型玻璃纤维直接纱386H", "其他"),
    (22, "杭州屹通新材料股份有限公司", "高精度高强度合金钢粉体", "其他"),
)


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
    import pdfplumber

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


def curated_2021_first_batch_non_reward() -> list[dict[str, Any]]:
    records = []
    for sequence, enterprise_name, product_name, recognition_tier in FIRST_BATCH_2021_NON_REWARD:
        records.append(
            base_record(
                project_id="11",
                project_name="浙江省首批次新材料",
                year=2021,
                enterprise_name=enterprise_name,
                product_name=product_name,
                recognition_tier=recognition_tier,
                list_status="publicity_non_reward",
                source_title="2021年度浙江省首批次新材料（非认定奖励类）拟认定项目清单",
                source_url="knowledge://50_名单与对标/三首项目/_结构化数据/_原始采集/用户补充/2021首批次非认定奖励类",
                source_tier="user_provided_official_screenshot",
            )
        )
        records[-1]["sequence_no"] = sequence
    return records


def write_2021_first_batch_non_reward_markdown(output: Path) -> Path:
    target = output / "_原始采集" / "用户补充" / "2021首批次非认定奖励类" / "2021年度浙江省首批次新材料（非认定奖励类）拟认定项目清单.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 2021年度浙江省首批次新材料（非认定奖励类）拟认定项目清单",
        "",
        "- 来源：用户提供的官方名单截图，共3张。",
        "- 名单性质：拟认定项目清单，非认定奖励类。",
        "- 关联项目：浙江省首批次新材料。",
        "- 结构化条目：22项。",
        "",
        "| 序号 | 生产企业 | 材料名称 | 认定类别 |",
        "|---:|---|---|---|",
    ]
    for sequence, enterprise_name, product_name, recognition_tier in FIRST_BATCH_2021_NON_REWARD:
        lines.append(f"| {sequence} | {enterprise_name} | {product_name} | {recognition_tier} |")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


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


def parse_2024_first_batch(path: Path) -> list[dict[str, Any]]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    records = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header = [clean(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"])] if rows else []
        if header[:4] != ["序号", "材料名称", "企业名称", "认定档次"]:
            continue
        for row in rows[1:]:
            cells = [clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if len(cells) < 4 or not cells[0].isdigit():
                continue
            records.append(
                base_record(
                    project_id="11",
                    project_name="浙江省首批次新材料",
                    year=2024,
                    enterprise_name=cells[2],
                    product_name=cells[1],
                    recognition_tier=cells[3],
                    list_status="publicity",
                    source_title="2024年度浙江省首批次新材料认定结果公示",
                    source_url=SOURCES["2024_first_batch_publicity"]["url"],
                    source_tier="public_repost",
                )
            )
        break
    if len(records) != 64:
        raise RuntimeError(f"2024首批次公示预期64项产品，实际{len(records)}条")
    return records


def parse_2025_first_version(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = payload.get("body") or {}
    soup = BeautifulSoup(str(body.get("CONTENT") or ""), "html.parser")
    records = []
    recognition_tier = ""
    for row in soup.select("table tr"):
        cells = [clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
        if len(cells) == 1 and "首版次软件" in cells[0]:
            recognition_tier = cells[0]
            continue
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        if len(cells) >= 4:
            product_category, product_name, enterprise_name = cells[1:4]
        else:
            product_category = ""
            product_name, enterprise_name = cells[1:3]
        records.append(
            base_record(
                project_id="10",
                project_name="浙江省首版次软件产品",
                year=2025,
                enterprise_name=enterprise_name,
                product_name=product_name,
                product_category=product_category,
                recognition_tier=recognition_tier,
                list_status="final_recognition",
                source_title=clean(body.get("TITLE")),
                source_url=SOURCES["2025_first_version_final"]["url"],
                source_tier="official",
            )
        )
    if len(records) != 84:
        raise RuntimeError(f"2025首版次正式目录预期84项产品，实际{len(records)}条")
    return records


def main() -> None:
    args = parse_args()
    curated_markdown = write_2021_first_batch_non_reward_markdown(args.output)
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
        *curated_2021_first_batch_non_reward(),
        *parse_2021_first_set(paths["2021_first_set_final"]),
        *parse_2021_first_set_standard(paths["2021_first_set_standard"]),
        *parse_2024_first_batch(paths["2024_first_batch_publicity"]),
        *parse_2025_first_version(paths["2025_first_version_final"]),
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
            "2021_first_batch_non_reward_publicity": 22,
            "2021_first_set_final": 235,
            "2021_first_set_standard": 8,
            "2024_first_batch_publicity": 64,
            "2025_first_version_final": 84,
        },
        "sources": SOURCES,
        "output": str(output),
        "curated_markdown": str(curated_markdown),
    }
    (source_cache / "采集元数据.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build Zhejiang small-giant review events from official publication rows.

Membership always comes from the official provincial or separately planned
Ningbo publication.  City and county are joined only after membership is fixed,
using the already reconciled earlier-cohort small-giant master (including former
names).  The build stops on any missing or ambiguous identity instead of
silently falling back to a semantic-search result.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "references"


REVIEW_2023_ZHEJIANG_NON_NINGBO = [
    "浙江铖昌科技股份有限公司",
    "浙江浙大鸣泉科技有限公司",
    "杭州集智机电股份有限公司",
    "浙江威星智能仪表股份有限公司",
    "杭州申昊科技股份有限公司",
    "浙江顺豪新材料有限公司",
    "浙江星华新材料集团股份有限公司",
    "杭州华普永明光电股份有限公司",
    "浙江托普云农科技股份有限公司",
    "中翰盛泰生物技术股份有限公司",
    "杭州屹通新材料股份有限公司",
    "杭州启明医疗器械股份有限公司",
    "英飞特电子（杭州）股份有限公司",
    "杭州捷尔思阻燃化工有限公司",
    "杭州中科微电子有限公司",
    "温州市润新机械制造有限公司",
    "星际控股集团有限公司",
    "浙江鼎业机械设备有限公司",
    "温州聚星科技股份有限公司",
    "乐清市嘉得电子有限公司",
    "浙江强力控股有限公司",
    "浙江正理生能科技有限公司",
    "八达机电股份有限公司",
    "工正集团有限公司",
    "宣达实业集团有限公司",
    "浙江华邦物联技术股份有限公司",
    "浙江炜冈科技股份有限公司",
    "温州益坤电气股份有限公司",
    "维融科技股份有限公司",
    "浙江嘉泰激光科技股份有限公司",
    "浙江石化阀门有限公司",
    "维都利阀门有限公司",
    "精工阀门集团有限公司",
    "欧诗漫生物股份有限公司",
    "安吉长虹制链有限公司",
    "浙江纳美新材料股份有限公司",
    "浙江盛发纺织印染有限公司",
    "浙江万享科技股份有限公司",
    "湖州电动滚筒有限公司",
    "浙江力聚热能装备股份有限公司",
    "湖州太平微特电机有限公司",
    "浙江睿高新材料股份有限公司",
    "浙江荣泰科技企业有限公司",
    "浙江海盐力源环保科技股份有限公司",
    "浙江联洋新材料股份有限公司",
    "浙江伏尔特医疗器械股份有限公司",
    "浙江上方生物科技有限公司",
    "川源（中国）机械有限公司",
    "浙江信胜科技股份有限公司",
    "绍兴中科通信设备有限公司",
    "浙江新涛智控科技股份有限公司",
    "浙江阿斯克建材科技股份有限公司",
    "浙江天行健水务有限公司",
    "浙江海创锂电科技有限公司",
    "浙江千禧龙纤特种纤维股份有限公司",
    "金华春光橡塑科技股份有限公司",
    "义乌市易开盖实业公司",
    "武义西林德机械制造有限公司",
    "浙江花园生物高科股份有限公司",
    "浙江闪铸三维科技有限公司",
    "浙江大众齿轮有限公司",
    "浙江好易点智能科技有限公司",
    "浙江日新电气有限公司",
    "浙江赛豪实业有限公司",
    "浙江肯得机电股份有限公司",
    "浙江飞越机电有限公司",
    "浙江风驰机械有限公司",
    "浙江海德曼智能装备股份有限公司",
    "浙江严牌过滤技术股份有限公司",
    "浙江优亿医疗器械股份有限公司",
    "三门三友科技股份有限公司",
    "宇恒电池股份有限公司",
    "舟山市7412工厂",
    "舟山海山机械密封材料股份有限公司",
    "舟山晨光电器有限公司",
]


def normalize_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value or "").lower()


def document_mentions(
    connection: sqlite3.Connection,
    title: str,
    *,
    take_last: int | None = None,
) -> list[str]:
    document = connection.execute(
        "SELECT id FROM documents WHERE title=? ORDER BY id LIMIT 1", (title,)
    ).fetchone()
    if document is None:
        raise ValueError(f"official review document not indexed: {title}")
    rows = connection.execute(
        "SELECT enterprise_name FROM enterprise_mentions WHERE document_id=? ORDER BY id",
        (int(document[0]),),
    ).fetchall()
    names = [str(row[0] or "").strip() for row in rows if str(row[0] or "").strip()]
    return names[-take_last:] if take_last is not None else names


def master_geography(connection: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    lookup: dict[str, set[tuple[str, str]]] = {}
    for row in connection.execute(
        "SELECT enterprise_name,former_names_json,city,county FROM national_small_giant_master"
    ):
        names = [str(row[0] or "")]
        try:
            names.extend(str(value) for value in json.loads(str(row[1] or "[]")))
        except json.JSONDecodeError:
            pass
        geography = (str(row[2] or ""), str(row[3] or ""))
        for name in names:
            key = normalize_name(name)
            if key and geography[0]:
                lookup.setdefault(key, set()).add(geography)
    ambiguous = {key: values for key, values in lookup.items() if len(values) > 1}
    if ambiguous:
        # Different county values within the same city are not membership
        # ambiguity; prefer the most recent populated master row below.
        for key, values in list(ambiguous.items()):
            if len({city for city, _ in values}) == 1:
                lookup[key] = {sorted(values, key=lambda value: bool(value[1]), reverse=True)[0]}
    return {key: next(iter(values)) for key, values in lookup.items() if len(values) == 1}


def source_specs(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "source_id": "national-small-giant-2022-first-review-zhejiang-non-ningbo-publicity",
            "document_title": "附件2：第一批专精特新“小巨人”复核通过企业公示名单_1 (1).xls",
            "event_year": 2022,
            "cohort_year": 2019,
            "batch": "第一批复核",
            "official_url": "",
            "evidence_archive_url": "",
            "names": document_mentions(
                connection,
                "附件2：第一批专精特新“小巨人”复核通过企业公示名单_1 (1).xls",
            ),
        },
        {
            "source_id": "national-small-giant-2022-first-review-ningbo-publicity",
            "document_title": "第一批专精特新“小巨人”复核通过企业公示名单—宁波市4家",
            "event_year": 2022,
            "cohort_year": 2019,
            "batch": "第一批复核",
            "official_url": "http://jxj.ningbo.gov.cn/art/2022/8/8/art_1229561613_58934870.html",
            "evidence_archive_url": "https://finance.sina.cn/2022-08-11/detail-imizmscv5788060.d.html",
            "names": [
                "宁波中意液压马达有限公司",
                "宁波菲仕技术股份有限公司",
                "宁波索诺工业自控设备有限公司",
                "宁波长城精工实业有限公司",
            ],
            "force_city": "宁波市",
        },
        {
            "source_id": "national-small-giant-2023-second-review-zhejiang-non-ningbo-publicity",
            "document_title": "第二批专精特新“小巨人”复核通过企业公示名单—浙江省非宁波段75家",
            "event_year": 2023,
            "cohort_year": 2020,
            "batch": "第二批复核",
            "official_url": "https://jxt.zj.gov.cn/art/2023/7/14/art_1582900_25599.html",
            "evidence_archive_url": "https://www.chacewang.com/newsdetail/news378215.html",
            "names": REVIEW_2023_ZHEJIANG_NON_NINGBO,
            "city_blocks": [
                ("杭州市", 15),
                ("温州市", 18),
                ("湖州市", 9),
                ("嘉兴市", 6),
                ("绍兴市", 5),
                ("金华市", 11),
                ("台州市", 8),
                ("舟山市", 3),
            ],
        },
        {
            "source_id": "national-small-giant-2023-second-review-ningbo-publicity",
            "document_title": "2.第二批专精特新“小巨人”复核通过企业公示名单.doc",
            "event_year": 2023,
            "cohort_year": 2020,
            "batch": "第二批复核",
            "official_url": "",
            "evidence_archive_url": "",
            "names": document_mentions(
                connection,
                "2.第二批专精特新“小巨人”复核通过企业公示名单.doc",
            ),
            "force_city": "宁波市",
        },
        {
            "source_id": "national-small-giant-2024-third-review-zhejiang-publicity",
            "document_title": "附件2.第三批专精特新“小巨人”复核通过企业公示名单.pdf",
            "event_year": 2024,
            "cohort_year": 2021,
            "batch": "第三批复核",
            "official_url": "https://jxt.zj.gov.cn/module/download/downfile.jsp?classid=0&filename=ac148016a52b408aadb917bf912d2690.pdf",
            "evidence_archive_url": "",
            "names": document_mentions(
                connection,
                "附件2.第三批专精特新“小巨人”复核通过企业公示名单.pdf",
            ),
        },
        {
            "source_id": "national-small-giant-2025-review-zhejiang-non-ningbo-publicity",
            "document_title": "关于浙江省第七批专精特新“小巨人”企业和2025年专精特新“小巨人”复核通过企业名单的公示—2.2025年专精特新“小巨人”复核通过企业公示名单.pdf",
            "event_year": 2025,
            "cohort_year": 2022,
            "batch": "2025年复核",
            "official_url": "https://zj87.jxt.zj.gov.cn/zlzq/web/views/article/news/detail.html?id=288758",
            "evidence_archive_url": "",
            "names": document_mentions(
                connection,
                "关于浙江省第七批专精特新“小巨人”企业和2025年专精特新“小巨人”复核通过企业名单的公示—2.2025年专精特新“小巨人”复核通过企业公示名单.pdf",
            ),
            "city_overrides": {
                "浙江德宏汽车电子电器股份有限公司": ("湖州市", "吴兴区")
            },
        },
        {
            "source_id": "national-small-giant-2025-review-ningbo-publicity",
            "document_title": "关于宁波市第七批专精特新“小巨人”企业和2025年专精特新“小巨人”复核通过企业名单的公示—公示附件名单.md",
            "event_year": 2025,
            "cohort_year": 2022,
            "batch": "2025年复核",
            "official_url": "",
            "evidence_archive_url": "https://www.keceyun.com/policy/newsdetail/362669.html",
            "names": document_mentions(
                connection,
                "关于宁波市第七批专精特新“小巨人”企业和2025年专精特新“小巨人”复核通过企业名单的公示—公示附件名单.md",
                take_last=95,
            ),
            "force_city": "宁波市",
        },
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(f"file:{args.database.expanduser().resolve()}?mode=ro", uri=True)
    geography = master_geography(connection)
    outputs: list[dict[str, Any]] = []
    for source in source_specs(connection):
        names = list(source.pop("names"))
        city_blocks = list(source.pop("city_blocks", []))
        city_overrides = dict(source.pop("city_overrides", {}))
        city_by_sequence: list[str] = []
        for city, count in city_blocks:
            city_by_sequence.extend([str(city)] * int(count))
        if city_by_sequence and len(city_by_sequence) != len(names):
            raise ValueError(
                f"city block mismatch for {source['source_id']}: "
                f"rows={len(names)} blocks={len(city_by_sequence)}"
            )
        if len(names) != len({normalize_name(name) for name in names}):
            raise ValueError(f"duplicate official review row: {source['source_id']}")
        entities: list[dict[str, Any]] = []
        missing: list[str] = []
        for sequence_no, name in enumerate(names, start=1):
            city, county = geography.get(normalize_name(name), ("", ""))
            if city_by_sequence:
                city = city_by_sequence[sequence_no - 1]
                if geography.get(normalize_name(name), ("", ""))[0] != city:
                    county = ""
            if name in city_overrides:
                city, county = city_overrides[name]
            if source.get("force_city"):
                city = str(source["force_city"])
            if not city:
                missing.append(name)
                continue
            entities.append(
                {
                    "sequence_no": sequence_no,
                    "enterprise_name": name,
                    "province": "浙江省",
                    "city": city,
                    "county": county,
                }
            )
        if missing:
            raise ValueError(
                f"unbound official review rows for {source['source_id']}: {missing}"
            )
        payload = {
            "schema_version": 1,
            **{key: value for key, value in source.items() if key != "force_city"},
            "project_name": "国家专精特新“小巨人”企业",
            "event_type": "review_publicity",
            "status": "复核通过公示",
            "coverage_basis": "official_review_publication_membership_plus_prior_cohort_identity_geography",
            "expected_count": len(names),
            "entities": entities,
        }
        output = args.output_dir / f"{source['source_id']}.json"
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        outputs.append(
            {
                "source_id": source["source_id"],
                "count": len(entities),
                "cities": dict(
                    sorted(
                        {
                            city: sum(item["city"] == city for item in entities)
                            for city in {item["city"] for item in entities}
                        }.items()
                    )
                ),
                "output": str(output),
            }
        )
    connection.close()
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

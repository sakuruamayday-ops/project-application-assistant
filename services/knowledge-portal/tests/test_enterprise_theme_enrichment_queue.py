import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_enterprise_theme_enrichment_queue.py"
SPEC = importlib.util.spec_from_file_location("enterprise_theme_queue", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_exact_names_add_topics_but_product_names_remain_correction_candidates():
    unified = [
        {
            "identity_key": "913301001111111111",
            "unified_social_credit_code": "913301001111111111",
            "current_name": "甲机器人有限公司",
            "recognition_projects": ["国家专精特新“小巨人”企业"],
            "main_product_tags": [],
            "industry_track_tags": [],
        },
        {
            "identity_key": "name:bfl2030h动柱高速铣削中心",
            "current_name": "BFL2030H 动柱高速铣削中心",
            "recognition_projects": ["浙江制造精品"],
            "main_product_tags": [],
            "industry_track_tags": [],
        },
    ]
    sources = [
        {
            "entName": "甲机器人有限公司",
            "industryName": "工业机器人制造",
        },
        {
            "entName": "宁波海天精工股份有限公司",
            "subject": "动柱高速铣削中心BFL2030H::国内首台（套）::整机装备",
            "industryName": "金属切削机床制造",
        },
    ]

    queue, stats = MODULE.build_queue(unified, sources)

    exact = next(row for row in queue if row["current_name"] == "甲机器人有限公司")
    product = next(row for row in queue if row["current_name"].startswith("BFL2030H"))
    assert exact["match_status"] == "exact_enterprise_name"
    assert exact["candidate_industry_track_tags"] == ["工业机器人制造"]
    assert product["match_status"] == "product_name_candidate"
    assert product["matched_enterprise_names"] == ["宁波海天精工股份有限公司"]
    assert stats["initial_theme_empty"] == 2
    assert stats["qice_topics_available"] == 2

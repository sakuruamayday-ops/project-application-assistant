from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "talent-projects"
SKILL = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
METHOD = (
    SKILL_ROOT / "references" / "talent-startup-location-preassessment.md"
).read_text(encoding="utf-8")
SNAPSHOT = (
    SKILL_ROOT
    / "references"
    / "hangzhou-talent-and-ai-voucher-snapshot-2026-08-06.md"
).read_text(encoding="utf-8")


def test_talent_preassessment_uses_real_profile_without_degree_floor():
    assert "学历只是可能的匹配字段之一" in SKILL
    assert "不设置统一的学历起点" in METHOD
    assert "不把博士、本科、专科或无学历证明直接等同于人才项目等级" in SKILL


def test_exception_and_voucher_routes_are_guarded():
    assert "只有官方规则明确存在时才能列为破格机会" in SKILL
    assert "不把“存在破格条款”写成“能够破格入选”" in METHOD
    assert "只有用户明确关注券类" in SKILL
    assert "未触发时，输出中省略券类比较" in SKILL
    assert "不检索、不列示、不计分" in METHOD
    assert "金额集中不等于大企业集中" in METHOD


def test_policy_route_sources_and_ten_district_snapshot_are_present():
    assert "以`policy-retrieval`为主技能" in SKILL
    assert "附录：主要政策来源" in SKILL
    assert "券类内容属于可选模块" in SNAPSHOT
    for district in (
        "上城",
        "拱墅",
        "西湖",
        "滨江",
        "萧山",
        "余杭",
        "临平",
        "钱塘",
        "富阳",
        "临安",
    ):
        assert district in SNAPSHOT


def test_stale_fixed_weight_and_phd_only_routes_are_absent():
    assert "references/phd-startup-location-preassessment.md" not in SKILL
    assert "人才项目50%" not in METHOD
    assert "券类资源15%" not in METHOD

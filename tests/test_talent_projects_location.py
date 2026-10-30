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
    for field in ("学历", "职称", "经历", "成果", "团队", "项目"):
        assert field in SKILL and field in METHOD
    assert "其他字段标未知并继续现有画像分析" in METHOD
    assert "年龄学历等未知条件保留在相关分支" in SKILL


def test_exception_and_voucher_routes_use_their_real_basis():
    assert "官方破格举荐" in SKILL
    assert "破格入口和个人最终入选状态分别呈现" in SKILL
    assert "有明确依据的破格路线" in SKILL
    assert "官方条款" in METHOD and "个人是否具备破格资格" in METHOD
    assert "按用户关注或实际训练、推理、采购需求展开" in SKILL
    assert "专项资源被触发时" in METHOD
    assert "企业规模集中与金额集中分别核对" in METHOD


def test_policy_route_sources_and_ten_district_snapshot_are_present():
    assert "policy-retrieval" in SKILL
    assert "主要政策来源" in SKILL
    assert "券类按业务需求和实际适配展开" in SNAPSHOT
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

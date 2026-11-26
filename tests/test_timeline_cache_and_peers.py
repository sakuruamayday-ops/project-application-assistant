from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "skills" / "_core"
CHECKUP_CLI = ROOT / "skills" / "gov-project-checkup" / "scripts" / "run_checkup.py"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import kb_local  # noqa: E402
import timeline_cache  # noqa: E402


def _make_mock_main_db(db_path: Path) -> None:
    con = sqlite3.connect(str(db_path))
    con.executescript(
        """
        CREATE TABLE enterprise (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            unified_social_credit_code TEXT,
            province TEXT,
            city TEXT,
            county TEXT,
            founded_date TEXT,
            registered_capital TEXT,
            industry_l1 TEXT,
            industry_l2 TEXT,
            industry_l3 TEXT,
            company_intro TEXT
        );
        CREATE TABLE recognition (
            id INTEGER PRIMARY KEY,
            enterprise_id INTEGER,
            project_name TEXT,
            recognition_year INTEGER,
            batch TEXT,
            result TEXT,
            recognition_status TEXT,
            product_name TEXT,
            primary_source_title TEXT,
            published_date TEXT
        );
        """
    )
    con.executemany(
        "INSERT INTO enterprise VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "浙江申新新材料包装有限公司", "9133010974949062XQ", "浙江省", "杭州市", "萧山区", "2003-07-01", "9817.65万人民币", "制造业", "橡胶和塑料制品业", "塑料包装箱", ""),
            (2, "杭州光驰通信技术有限公司", "913301097544408546", "浙江省", "杭州市", "萧山区", "2003-11-18", "1000万人民币", "制造业", "电气机械和器材制造业", "光通信设备", ""),
            (3, "杭州复核老企有限公司", "91330109000000003A", "浙江省", "杭州市", "萧山区", "2000-01-01", "5000万人民币", "制造业", "通用设备制造业", "机械", ""),
            (4, "杭州已退出企业有限公司", "91330109000000004B", "浙江省", "杭州市", "萧山区", "2010-01-01", "2000万人民币", "制造业", "通用设备制造业", "机械", ""),
        ],
    )
    con.executemany(
        "INSERT INTO recognition VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            # 2026 重点省专 (年初公示 -> 默认 apply_year=2025)
            (1, 1, "浙江省重点省专", 2026, "第二批", "拟支持", "recognized", "", "2026重点省专公示", "2026-02-24"),
            (2, 2, "浙江省重点省专", 2026, "第二批", "拟支持", "recognized", "", "2026重点省专公示", "2026-02-24"),
            # 伴随项目：申新 2024 已有首台套（事前），2026 才拿制造精品（事后）
            (3, 1, "浙江省制造业首台（套）装备", 2024, "2024", "正式认定", "recognized", "设备A", "首台套", "2024-12-20"),
            (4, 1, "浙江制造精品", 2026, "2026", "拟认定", "recognized", "产品A", "制造精品", "2026-10-10"),
            # 2025 复核企业（用于测试 exclude_review 与跨届告警）
            (5, 3, "浙江省重点省专", 2025, "复核", "拟复核通过", "recognized", "", "2025复核", "2025-06-01"),
            # 已退出记录（必须被 recognition_status='recognized' 过滤）
            (6, 4, "浙江省重点省专", 2026, "第二批", "计划退出目录", "excluded", "", "退出名单", "2026-03-01"),
        ],
    )
    con.commit()
    con.close()


def test_timeline_cache_upsert_and_point_in_time_backtest(tmp_path: Path) -> None:
    cache_db = tmp_path / "timeline_cache.db"
    qcc_patents = {
        "企业名称": "浙江申新新材料包装有限公司",
        "专利信息": [
            {"申请号": "CN202610143172.7", "发明名称": "事后发明1", "申请日期": "2026-02-02", "公开（公告）日期": "2026-10-30", "专利类型": "发明授权", "法律状态": "授权"},
            {"申请号": "CN202510920827.2", "发明名称": "事后发明2", "申请日期": "2025-07-04", "公开（公告）日期": "2026-06-19", "专利类型": "发明授权", "法律状态": "授权"},
            {"申请号": "CN202310414797.9", "发明名称": "事前发明1", "申请日期": "2023-04-18", "公开（公告）日期": "2025-11-14", "专利类型": "发明授权", "法律状态": "授权"},
            {"申请号": "CN202011071891.1", "发明名称": "事前发明2", "申请日期": "2020-10-09", "公开（公告）日期": "2025-04-04", "专利类型": "发明授权", "法律状态": "授权"},
            {"申请号": "CN202011071894.5", "发明名称": "受让发明3", "申请日期": "2020-10-09", "公开（公告）日期": "2024-06-21", "专利类型": "发明授权", "法律状态": "授权", "权利取得方式": "受让取得"},
            {"申请号": "CN201911000594.5", "发明名称": "事前发明4", "申请日期": "2019-10-21", "公开（公告）日期": "2022-11-08", "专利类型": "发明授权", "法律状态": "授权"},
        ],
    }
    r1 = timeline_cache.ingest_patents("9133010974949062XQ", qcc_patents, fetched_at="2026-11-25T10:00:00+08:00", cache_path=cache_db)
    # Re-ingest same payload -> idempotent upsert, no duplicate count
    r2 = timeline_cache.ingest_patents("9133010974949062XQ", qcc_patents, fetched_at="2026-11-25T10:05:00+08:00", cache_path=cache_db)
    assert r1["ok"] and r2["ok"] and r2["upserted"] == 6

    q_apply = timeline_cache.query_at_date("9133010974949062XQ", "2025-12-28", cache_path=cache_db)
    assert q_apply["cache_hit"] is True
    assert q_apply["patent_point_in_time_reliable"] is True
    assert q_apply["valid_granted_inv_at_t"] == 4
    assert q_apply["valid_own_inv_at_t"] == 3  # excludes 1 transferred patent
    assert q_apply["current_granted_inv"] == 6
    assert q_apply["post_hoc_granted_inv_delta"] == 2

    qcc_honors = {
        "企业名称": "浙江申新新材料包装有限公司",
        "荣誉信息": [
            {"名称": "高新技术企业研究开发中心", "级别": "省级", "认证年份": "2024", "发布日期": "2025-01-07", "发布单位": "省经信厅"},
            {"名称": "浙江制造精品", "级别": "省级", "认证年份": "2026", "发布日期": "2026-10-10", "发布单位": "省经信厅"},
        ],
    }
    hr = timeline_cache.ingest_honors("9133010974949062XQ", qcc_honors, fetched_at="2026-11-25T10:05:00+08:00", cache_path=cache_db)
    assert hr["ok"] and hr["upserted"] == 2
    q_h = timeline_cache.query_at_date("9133010974949062XQ", "2025-12-28", cache_path=cache_db)
    assert any("高新技术企业研究开发中心" in x for x in q_h["pre_honors_at_t"])
    assert any("浙江制造精品" in x for x in q_h["post_honors_after_t"])


def test_query_peers_point_in_time_benchmark_and_backward_compat(tmp_path: Path) -> None:
    main_db = tmp_path / "jiaotang.db"
    cache_db = tmp_path / "timeline_cache.db"
    _make_mock_main_db(main_db)

    # 1. Backward compatible call with NO cache file present
    legacy = kb_local.query_peers("重点省专", "萧山", "", 20, db_path=main_db)
    names = [p["enterprise_name"] for p in legacy["peers"]]
    assert "杭州已退出企业有限公司" not in names  # excluded status filtered out
    assert len(names) == 3

    # 2. Cross-cohort warning when benchmark=True without year/exclude_review
    mixed = kb_local.query_peers("重点省专", "萧山", "", 20, db_path=main_db, benchmark=True, cache_path=cache_db)
    assert mixed["benchmark_summary"]["cohort_count"] == 2
    assert len(mixed["benchmark_summary"]["warnings"]) == 1

    # 3. Populate sidecar cache for 1 of 2 enterprises, then run filtered benchmark
    timeline_cache.ingest_patents(
        "9133010974949062XQ",
        [
            {"申请号": "CN202310414797.9", "公开（公告）日期": "2025-11-14", "专利类型": "发明授权", "法律状态": "授权"},
            {"申请号": "CN202610143172.7", "公开（公告）日期": "2026-10-30", "专利类型": "发明授权", "法律状态": "授权"},
        ],
        fetched_at="2026-11-25T10:00:00+08:00",
        cache_path=cache_db,
    )
    res = kb_local.query_peers(
        "重点省专",
        "萧山",
        "",
        20,
        db_path=main_db,
        year=2026,
        exclude_review=True,
        apply_date="2025-12-28",
        benchmark=True,
        cache_path=cache_db,
    )
    assert res["deduped_count"] == 2
    by_name = {p["enterprise_name"]: p for p in res["peers"]}
    shenxin = by_name["浙江申新新材料包装有限公司"]
    assert shenxin["apply_date"] == "2025-12-28"
    assert shenxin["age_at_apply"] == 22.4
    assert "浙江省制造业首台（套）装备(2024)" in shenxin["pre_existing_projects"]
    assert "浙江制造精品(2026)" in shenxin["post_hoc_projects"]
    assert shenxin["timeline_cache"]["valid_granted_inv_at_t"] == 1
    assert shenxin["timeline_cache"]["post_hoc_granted_inv_delta"] == 1

    cohort = res["benchmark_summary"]["cohorts"][0]
    assert cohort["pre_existing_project_rates_pct"]["浙江省制造业首台（套）装备"] == 50.0
    assert cohort["post_hoc_project_rates_pct"]["浙江制造精品"] == 50.0
    assert cohort["timeline_cache_patents"]["cached_count"] == 1
    assert cohort["timeline_cache_patents"]["post_hoc_inflation_pct"] == 100.0
    assert len(cohort["pending_cache_sample"]) == 1
    assert cohort["pending_cache_sample"][0]["uscc"] == "913301097544408546"


def test_run_checkup_cli_cache_ingest_and_query(tmp_path: Path) -> None:
    cache_db = tmp_path / "cli_cache.db"
    payload = {
        "企业名称": "嘉兴市科讯电子有限公司",
        "专利信息": [
            {"申请号": "CN202211740304.2", "公开（公告）日期": "2024-03-15", "专利类型": "发明授权", "法律状态": "授权"},
            {"申请号": "CN202411945362.8", "公开（公告）日期": "2025-03-18", "专利类型": "发明授权", "法律状态": "授权"},
        ],
    }
    p_ing = subprocess.run(
        [
            sys.executable, str(CHECKUP_CLI), "cache-ingest",
            "--type", "patent", "--uscc", "91330411715401967P",
            "--input", "-", "--cache-db", str(cache_db),
        ],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=True,
    )
    ing_out = json.loads(p_ing.stdout)
    assert ing_out["ok"] is True and ing_out["upserted"] == 2

    p_qry = subprocess.run(
        [
            sys.executable, str(CHECKUP_CLI), "cache-query",
            "--uscc", "91330411715401967P", "--as-of", "2024-11-07",
            "--cache-db", str(cache_db),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    qry_out = json.loads(p_qry.stdout)
    assert qry_out["valid_granted_inv_at_t"] == 1
    assert qry_out["current_granted_inv"] == 2

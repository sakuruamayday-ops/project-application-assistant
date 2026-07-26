#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "references" / "ipc-snapshots" / "dual-center-ipc-index.json"


def normalize_ipc(value):
    match = re.search(r"\b([A-H]\d{2}[A-Z])", value.upper())
    return match.group(1) if match else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--applicant-location", required=True)
    p.add_argument("--ipc", action="append", required=True)
    p.add_argument("--technology-theme", default="")
    p.add_argument("--zhejiang-record", choices=["yes", "no", "unknown"], default="yes")
    p.add_argument("--hangzhou-record", choices=["yes", "no", "unknown"], default="yes")
    p.add_argument("--zhejiang-status", choices=["normal", "suspended", "unknown"], default="unknown")
    p.add_argument("--hangzhou-status", choices=["normal", "suspended", "unknown"], default="unknown")
    a = p.parse_args()

    data = json.loads(INDEX.read_text(encoding="utf-8"))["centers"]
    codes = [normalize_ipc(x) for x in a.ipc]
    invalid = [raw for raw, code in zip(a.ipc, codes) if not code]
    codes = [code for code in codes if code]
    location = a.applicant_location
    in_hangzhou = "杭州" in location
    in_zhejiang = in_hangzhou or "浙江" in location
    theme = a.technology_theme

    rows = {}
    for name, record, region_ok, record_state, status in [
        ("浙江省知识产权保护中心", data["浙江省知识产权保护中心"], in_zhejiang, a.zhejiang_record, a.zhejiang_status),
        ("杭州市知识产权保护中心", data["杭州市知识产权保护中心"], in_hangzhou, a.hangzhou_record, a.hangzhou_status),
    ]:
        hits = [code for code in codes if code in record["ipc_subclasses"]]
        rows[name] = {
            "region_eligible": region_ok,
            "record_status": record_state,
            "service_status": status,
            "ipc_hits": hits,
            "ipc_misses": [code for code in codes if code not in hits],
            "all_ipc_hit": bool(codes) and len(hits) == len(codes),
            "industries": record["industries"],
        }

    eligible = []
    for name, row in rows.items():
        if (
            row["region_eligible"]
            and row["all_ipc_hit"]
            and row["record_status"] != "no"
            and row["service_status"] != "suspended"
        ):
            eligible.append(name)

    reasons = []
    if not eligible:
        result = "NO_ELIGIBLE_CENTER"
        recommendation = None
    elif len(eligible) == 1:
        recommendation = eligible[0]
        result = "RECOMMEND_HANGZHOU" if "杭州" in recommendation else "RECOMMEND_ZHEJIANG"
        reasons.append("仅该中心同时通过地域、IPC、备案可行性与服务状态门槛")
    else:
        hz_keywords = ("数字经济", "软件", "算法", "人工智能", "装备", "机器人", "半导体", "通信", "数据")
        zj_keywords = ("生物", "医药", "食品", "绿色", "低碳", "新能源", "环保", "新一代信息技术")
        hz_score = sum(k in theme for k in hz_keywords) + (a.hangzhou_record == "yes")
        zj_score = sum(k in theme for k in zj_keywords) + (a.zhejiang_record == "yes")
        if hz_score > zj_score:
            result, recommendation = "RECOMMEND_HANGZHOU", "杭州市知识产权保护中心"
            reasons.append("两个中心均命中，技术主题或现有备案更直接匹配杭州中心")
        elif zj_score > hz_score:
            result, recommendation = "RECOMMEND_ZHEJIANG", "浙江省知识产权保护中心"
            reasons.append("两个中心均命中，技术主题或现有备案更直接匹配浙江中心")
        else:
            result, recommendation = "CONDITIONAL_TIE", None
            reasons.append("两个中心均命中，现有证据不足以可靠区分")

    print(
        json.dumps(
            {
                "result": result,
                "recommended_primary_target_center": recommendation,
                "reasons": reasons,
                "candidate_assessment": rows,
                "invalid_ipc_inputs": invalid,
                "defaults_applied": {
                    "zhejiang_record": a.zhejiang_record,
                    "hangzhou_record": a.hangzhou_record,
                    "record_basis": "用户常设指令：未提供相反信息时，两个中心均按已备案处理",
                },
                "warning": "推荐不等于受理；默认备案状态属于工作假设，正式提交前仍须按基准日复核目标中心备案、IPC和管理办法。",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

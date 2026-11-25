#!/usr/bin/env python3
"""对照浙江和杭州预审中心的备案、产业和 IPC 要求。"""

import argparse
import json
import re
from pathlib import Path

from preexam_evidence import add_evidence_arguments, applicant_evidence

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "references" / "ipc-snapshots" / "dual-center-ipc-index.json"
ZHEJIANG = "浙江省知识产权保护中心"
HANGZHOU = "杭州市知识产权保护中心"
THEME_WORDS = {
    ZHEJIANG: (
        "生物", "医药", "食品", "绿色", "低碳", "新能源", "环保", "新一代信息技术",
        "新材料", "高分子", "复合材料", "阻隔", "节能", "医疗器械", "化工", "储能",
    ),
    HANGZHOU: (
        "数字经济", "软件", "算法", "人工智能", "装备", "机器人", "半导体", "通信", "数据",
        "网络安全", "加密", "网关", "物联网", "集成电路", "智能制造", "高端装备", "精密", "传动",
    ),
}
SERVICE_LABEL = {"normal": "正常", "suspended": "暂停", "unknown": "缺状态回执"}


def normalize_ipc(value):
    match = re.search(r"\b([A-H]\d{2}[A-Z])", value.upper())
    return match.group(1) if match else None


def compare_center(name, reference, location, region_ok, codes, theme, words, record, record_evidence, service):
    present = set(reference["ipc_subclasses"])
    hits = [code for code in codes if code in present]
    misses = [code for code in codes if code not in present]
    eligible = region_ok and bool(codes) and not misses and record != "no" and service != "suspended"
    record_state = record_evidence["status"]
    gaps = []
    actions = []
    if not region_ok:
        gaps.append("申请主体属地不符")
        actions.append("核对第一申请主体登记住所")
    if not codes or misses:
        gaps.append(f"目录缺 {'、'.join(misses)}" if misses else "缺有效 IPC")
        actions.append("核对独立权利要求的拟申请 IPC 与目录")
    if record != "yes":
        gaps.append("备案" + record_state if record == "unknown" else record_state)
        actions.append("取得中心备案回执")
    if service != "normal":
        gaps.append(f"服务{SERVICE_LABEL[service]}")
        actions.append("取得中心最新服务状态")
    if not words:
        gaps.append("缺可对应产业范围的主题线索")
        actions.append("按独立权利要求核对技术主题")

    evidence = [
        f"目录版本 {reference['release_date']}",
        reference["artifact"],
        reference["source_page"],
    ]
    if record_evidence["reference"]:
        evidence.append(record_evidence["reference"])
    if reference.get("official_corroboration_page"):
        evidence.append(reference["official_corroboration_page"])
    region = "杭州市" if name == HANGZHOU else "浙江省"
    return {
        "item": name,
        "requirement": f"主体属地为{region}，拟申请 IPC 在目录内，备案允许且服务未暂停。产业范围为{'、'.join(reference['industries'])}。",
        "actual": (
            f"按已填资料{'匹配' if eligible else '未匹配'}。属地 {location}（{'符合' if region_ok else '不符'}）。"
            f"主题 {theme or '缺输入'}，命中线索 {'、'.join(words) or '无'}。"
            f"IPC 命中 {'、'.join(hits) or '无'}。{record_state}，服务{SERVICE_LABEL[service]}。"
        ),
        "gap": "、".join(gaps) or "无",
        "evidence": " | ".join(evidence),
        "action": "。".join(actions) + "。" if actions else "留存备案回执、独立权利要求和目录条目。",
        "priority": "高" if not eligible else "中" if gaps else "低",
    }, eligible


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--applicant-location", required=True)
    parser.add_argument("--ipc", action="append", required=True)
    parser.add_argument("--technology-theme", default="")
    parser.add_argument("--company", default="")
    add_evidence_arguments(parser)
    parser.add_argument("--zhejiang-status", choices=["normal", "suspended", "unknown"], default="unknown")
    parser.add_argument("--hangzhou-status", choices=["normal", "suspended", "unknown"], default="unknown")
    args = parser.parse_args()
    try:
        applicant = applicant_evidence(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    centers = json.loads(INDEX.read_text(encoding="utf-8"))["centers"]
    normalized = [normalize_ipc(value) for value in args.ipc]
    invalid = [raw for raw, code in zip(args.ipc, normalized) if not code]
    codes = list(dict.fromkeys(code for code in normalized if code))
    location = args.applicant_location
    in_hangzhou = "杭州" in location
    in_zhejiang = in_hangzhou or "浙江" in location
    theme = args.technology_theme

    items = []
    matches = []
    by_theme = []
    by_record = []
    for center, name, region_ok, service in (
        ("zhejiang", ZHEJIANG, in_zhejiang, args.zhejiang_status),
        ("hangzhou", HANGZHOU, in_hangzhou, args.hangzhou_status),
    ):
        words = [word for word in THEME_WORDS[name] if word in theme]
        record = applicant[f"{center}_record_status"]
        comparison, eligible = compare_center(name, centers[name], location, region_ok, codes, theme, words,
                                              record, applicant["record_evidence"][center], service)
        items.append(comparison)
        if eligible:
            matches.append(name)
            if words:
                by_theme.append(name)
            if record == "yes":
                by_record.append(name)

    primary = None
    if not matches:
        summary = "两家预审中心均未通过已填条件对照。"
    elif len(matches) == 1:
        primary = matches[0]
        summary = f"按已填条件匹配 {primary}。"
    elif len(by_theme) == 1:
        primary = by_theme[0]
        summary = f"两家均通过已填条件对照。主题线索更直接对应 {primary}，优先核对该中心。"
    elif len(by_record) == 1:
        primary = by_record[0]
        summary = f"两家均通过已填条件对照。按已有备案状态优先核对 {primary}。"
    else:
        summary = "两家均通过已填条件对照。核对技术主题对应的产业条目和备案回执后选择。"

    if invalid:
        items.append({
            "item": "拟申请 IPC 输入",
            "requirement": "使用可识别的 IPC 小类代码",
            "actual": "、".join(invalid),
            "gap": f"{len(invalid)} 项缺有效代码",
            "evidence": "输入的 IPC 列表",
            "action": "核对独立权利要求并更正代码，再复核候选中心。",
            "priority": "高",
        })
        summary += "有输入代码需更正，当前结论依据可识别的 IPC。"

    if primary:
        decision = "RECOMMEND_HANGZHOU" if primary == HANGZHOU else "RECOMMEND_ZHEJIANG"
    else:
        decision = "CONDITIONAL_TIE" if matches else "NO_ELIGIBLE_CENTER"
    print(json.dumps({
        "applicant": applicant,
        "items": items,
        "summary": summary,
        "result": decision,
        "recommended_primary_target_center": primary,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_DB = Path("/Users/zsh/JiaotangData/索引/current/knowledge_content.sqlite3")
DEFAULT_MASTER_REPORT = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/_全国小巨人批次主表/全国小巨人批次主表核验报告.json")
DEFAULT_OUTPUT = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/_覆盖矩阵/专精特新小巨人三首遗漏审计.md")
DEFAULT_ZHEJIANG_EVENTS = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/企业身份时间轴/浙江省/浙江省企业认定事件.jsonl")
DEFAULT_THREE_FIRST_SUMMARY = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/三首项目/_结构化数据/三首项目跨年对标图谱汇总.json")
DEFAULT_SMALL_GIANT_FRAGMENTS = Path("/Users/zsh/JiaotangData/知识库/50_名单与对标/优质中小企业梯度培育/_全国小巨人批次主表/官方地方分片/official_fragments.json")
FORMAL_EVENT_STATUSES = {"official_final_list", "official_final_list_mirror"}
PUBLIC_EVENT_STATUSES = {"official_publicity", "official_publicity_archive"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计省专、国家小巨人和三首项目名单覆盖缺口")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--master-report", type=Path, default=DEFAULT_MASTER_REPORT)
    parser.add_argument("--zhejiang-events", type=Path, default=DEFAULT_ZHEJIANG_EVENTS)
    parser.add_argument("--three-first-summary", type=Path, default=DEFAULT_THREE_FIRST_SUMMARY)
    parser.add_argument("--small-giant-fragments", type=Path, default=DEFAULT_SMALL_GIANT_FRAGMENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_zhejiang_specialized_events(path: Path) -> dict[int, dict[str, object]]:
    rows: dict[int, dict[str, object]] = defaultdict(
        lambda: {
            "formal_ids": set(),
            "public_ids": set(),
            "reconstructed_ids": set(),
            "formal_titles": set(),
            "formal_paths": set(),
        }
    )
    if not path.is_file():
        return {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("project_name") != "浙江省专精特新中小企业":
            continue
        year = int(event.get("event_year") or 0)
        if not 2022 <= year <= 2025:
            continue
        identity = str(event.get("identity_key") or event.get("normalized_name") or "")
        evidence_status = str(event.get("evidence_status") or "")
        if evidence_status in FORMAL_EVENT_STATUSES:
            rows[year]["formal_ids"].add(identity)
            rows[year]["formal_titles"].add(str(event.get("source_title") or ""))
            rows[year]["formal_paths"].update(str(path) for path in event.get("source_paths") or [] if path)
        elif evidence_status in PUBLIC_EVENT_STATUSES:
            rows[year]["public_ids"].add(identity)
        elif evidence_status == "official_count_current_library_qice_reconstruction":
            rows[year]["reconstructed_ids"].add(identity)
    return rows


def main() -> None:
    args = parse_args()
    master = json.loads(args.master_report.read_text(encoding="utf-8"))
    zhejiang_events = load_zhejiang_specialized_events(args.zhejiang_events)
    three_first_summary = (
        json.loads(args.three_first_summary.read_text(encoding="utf-8"))
        if args.three_first_summary.is_file()
        else {}
    )
    fragment_payload = (
        json.loads(args.small_giant_fragments.read_text(encoding="utf-8"))
        if args.small_giant_fragments.is_file()
        else {}
    )
    fragment_by_batch: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in fragment_payload.get("batch_region_summary", []):
        batch = str(item.get("batch") or "")
        fragment_by_batch[batch]["matched_name_count"] += int(item.get("matched_name_count") or 0)
        fragment_by_batch[batch]["official_only_count"] += int(item.get("official_only_count") or 0)
        fragment_by_batch[batch]["candidate_only_count"] += int(item.get("candidate_only_count") or 0)
        if int(item.get("official_fragment_enterprise_count") or 0) > 0:
            fragment_by_batch[batch]["covered_regions"] += 1
        if str(item.get("closure_status") or "").startswith("closed_"):
            fragment_by_batch[batch]["closed_regions"] += 1
        if str(item.get("closure_status") or "") == "missing_official_fragment":
            fragment_by_batch[batch]["missing_regions"] += 1
    connection = sqlite3.connect(args.database)
    matrix_counts = {
        scope: dict(connection.execute(
            "SELECT status,COUNT(*) FROM list_coverage_matrix WHERE project_scope=? GROUP BY status",
            (scope,),
        ).fetchall())
        for scope in ("provincial_specialized_sme", "national_small_giant")
    }
    provincial_gaps: dict[str, list[int]] = defaultdict(list)
    for region, year in connection.execute(
        """
        SELECT region,year FROM list_coverage_matrix
        WHERE project_scope='provincial_specialized_sme' AND status='missing' AND year<=2025
        ORDER BY region,year
        """
    ):
        provincial_gaps[str(region)].append(int(year))
    three_first = connection.execute(
        """
        SELECT project_name,year,
               SUM(CASE WHEN evidence_semantics='annual_list_row' THEN 1 ELSE 0 END),
               SUM(CASE WHEN evidence_semantics='annual_list_row' AND product_name<>'' THEN 1 ELSE 0 END),
               SUM(CASE WHEN evidence_semantics='annual_list_row' AND source_url<>'' THEN 1 ELSE 0 END),
               SUM(CASE WHEN evidence_semantics='platform_history_claim' THEN 1 ELSE 0 END),
               GROUP_CONCAT(DISTINCT CASE WHEN evidence_semantics='annual_list_row' THEN source_tier END)
        FROM three_first_project_awards
        GROUP BY project_name,year ORDER BY project_name,year
        """
    ).fetchall()
    connection.close()
    lines = [
        "# 专精特新、小巨人和三首名单覆盖遗漏审计",
        "",
        f"- 生成时间：{datetime.now().astimezone().strftime('%Y年%m月%d日%H:%M:%S')}",
        "- 口径：国家小巨人仅统计第一至第七批认定；2026年第八批尚未形成最终认定名单，不计作历史遗漏。",
        "- 规则：认定、复核、重点支持、地方小巨人和园区名单分别处理。",
        "",
        "## 一、全国小巨人批次主表",
        "",
        "| 年度 | 批次 | 官方总量 | 当前候选 | 总量差 | 分片名称交集 | 分片覆盖地区 | 名称集合闭环地区 | 缺分片地区 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in master["batches"]:
        fragment = fragment_by_batch.get(str(item["batch"]), {})
        lines.append(
            f"| {item['year']} | {item['batch']} | {item['expected_official_count']} | "
            f"{item['candidate_count']} | {item['count_delta']} | {fragment.get('matched_name_count', 0)} | "
            f"{fragment.get('covered_regions', 0)} | {fragment.get('closed_regions', 0)} | "
            f"{fragment.get('missing_regions', 0)} | "
            f"{item['completeness_state']} |"
        )
    lines.extend([
        "",
        "- 第四至第七批中央完整附件尚未全部恢复；当前总量差只能说明候选池与官方公布总量不一致，不能直接解释为准确缺少多少家。",
        "- 地方分片按企业名称集合对账；数量相等但名称不同仍记为未闭环。详细差异见同轮《官方分片企业名称差异.csv》。",
    ])
    lines.extend([
        "",
        "## 二、浙江省专精特新历史覆盖",
        "",
        "- 这里优先读取浙江企业认定事件的正式名单证据，避免通用全文矩阵未解析派生文件时误报缺口。",
        "- 正式认定、复核通过、公示过程和企策重建分别统计；低等级重建不升级为正式名单。",
        "",
        "| 年度 | 正式名单主体 | 公示主体 | 企策重建主体 | 审计结论 |",
        "|---:|---:|---:|---:|---|",
    ])
    for year in range(2022, 2026):
        item = zhejiang_events.get(year, {})
        formal_count = len(item.get("formal_ids", set()))
        public_count = len(item.get("public_ids", set()))
        reconstructed_count = len(item.get("reconstructed_ids", set()))
        if formal_count:
            conclusion = "已命中正式名单结构化事件"
        elif public_count:
            conclusion = "仅命中公示层，当前正式名单层未命中"
        elif reconstructed_count:
            conclusion = "仅有重建线索，待正式来源"
        else:
            conclusion = "当前结构化事件层未命中"
        lines.append(
            f"| {year} | {formal_count} | {public_count} | {reconstructed_count} | {conclusion} |"
        )
    lines.extend([
        "",
        f"- 通用32地区矩阵状态保留为诊断信息：{json.dumps(matrix_counts['provincial_specialized_sme'], ensure_ascii=False)}。",
        "- 2022年首批185家仍属于企策重建范围；第二批正式名单已结构化。2024年当前只命中公示层，不能写成正式认定闭环。",
        "- 2025年第一、第二批正式认定及复核通过事件均已结构化，不再标记为附件未提取。",
    ])
    lines.extend([
        "",
        "## 三、三首产品级明细",
        "",
        "- 年度名单行与平台历史发现分开统计；平台历史页中的年份不等同于当年正式认定。",
        "- official 为政府官方附件，public_archive 为公开档案中的正式附件，public_repost 为公开转载公示表，licensed_platform 为企策顾问授权数据。",
        "",
        "| 项目 | 年度 | 年度名单行 | 有产品名称 | 有来源链接 | 平台历史线索 | 年度名单来源 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ])
    lines.extend(
        f"| {project} | {year or '待核验'} | {annual_count or 0} | {product_count or 0} | "
        f"{source_count or 0} | {history_count or 0} | {source_tiers or '仅历史线索'} |"
        for project, year, annual_count, product_count, source_count, history_count, source_tiers in three_first
    )
    lines.extend([
        "",
        "## 四、三首双层闭环状态",
        "",
        "- 年度正式产品层：只使用同年度名单产品，不用其他年度产品回填。",
        "- 企业身份主题层：允许使用同企业、同项目其他年度已核产品判断产品方向，但保留原年份和证据来源。",
        f"- 全历史企业身份：已闭合 {three_first_summary.get('identity_topic_direction_closed', '待生成')}/"
        f"{three_first_summary.get('identity_profiles', '待生成')}，待补 {three_first_summary.get('identity_topic_direction_pending', '待生成')}。",
        f"- 2025年平台历史范围：已闭合 {three_first_summary.get('history_2025_identity_topic_closed', '待生成')}/"
        f"{three_first_summary.get('history_2025_scope_records', '待生成')}，待补 {three_first_summary.get('history_2025_identity_topic_pending', '待生成')}。",
        f"- 平台历史范围未对应年度正式产品：{three_first_summary.get('scope_unresolved_records', '待生成')}条；这些是范围线索，不等于缺失产品名。",
        "",
        "## 五、下一轮优先级",
        "",
        "1. 三首只补企业身份主题仍无产品信号的主体；年度范围未对应项继续保留，不批量伪回填。",
        "2. 浙江省专精特新优先恢复2024年正式认定来源及2022年首批185家正式名单来源。",
        "3. 全国小巨人第四至第七批按地区逐一核对官方分片与候选企业名称集合，不能只看总量差。",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "generic_matrix_missing_combinations": sum(len(years) for years in provincial_gaps.values()),
        "three_first_rows": len(three_first),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

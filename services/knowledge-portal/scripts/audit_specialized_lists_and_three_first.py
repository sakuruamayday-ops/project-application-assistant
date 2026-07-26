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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计省专、国家小巨人和三首项目名单覆盖缺口")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--master-report", type=Path, default=DEFAULT_MASTER_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    master = json.loads(args.master_report.read_text(encoding="utf-8"))
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
        "| 年度 | 批次 | 官方数量 | 当前候选 | 差额 | 地方官方分片已匹配 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in master["batches"]:
        lines.append(
            f"| {item['year']} | {item['batch']} | {item['expected_official_count']} | "
            f"{item['candidate_count']} | {item['count_delta']} | {item['official_local_match_count']} | "
            f"{item['completeness_state']} |"
        )
    lines.extend([
        "",
        "## 二、省级专精特新历史缺口",
        "",
        f"- 矩阵状态：{json.dumps(matrix_counts['provincial_specialized_sme'], ensure_ascii=False)}",
        f"- 2022至2025年历史缺口：{sum(len(years) for years in provincial_gaps.values())} 个地区年度组合。",
        "- 2026年度按当年认定进度持续采集，不与历史缺口混算。",
        "",
        "| 地区 | 待补年度 |",
        "|---|---|",
    ])
    lines.extend(f"| {region} | {','.join(map(str, years))} |" for region, years in provincial_gaps.items())
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
        "## 四、三首当前明确缺口",
        "",
        "1. 首台套2016至2018年目前只有企策历史企业与年度线索，尚缺可逐企业核验的完整产品级附件。",
        "2. 2021年首批次已补13条重点新材料认定奖励名单；非认定奖励类公开信息显示应有22个项目，当前企策历史页仅发现18家企业线索，尚缺完整产品级附件且至少4条待恢复，不能与奖励名单混算。",
        "3. 2019年首台套为公开转载的107条公示表，尚待恢复政府官方原始附件；当前可用于线索核验，不替代最终认定原文。",
        "",
        "## 五、下一轮优先级",
        "",
        "1. 恢复首台套2016至2019年政府官方附件并核对公示与认定差额。",
        "2. 恢复2021年非奖励口径首批次新材料完整附件，确认与13条重点奖励名单的包含关系。",
        "3. 对企策顾问2022至2025年产品级字段抽样核验产品名称、档次、地区和原始链接。",
        "4. 省专按覆盖矩阵继续补历史缺口；国家小巨人按批次主表仅处理新增异常。",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "provincial_historical_gaps": sum(len(years) for years in provincial_gaps.values()), "three_first_rows": len(three_first)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

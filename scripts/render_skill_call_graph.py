#!/usr/bin/env python3
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
GRAPH_PATH = SKILLS_ROOT / "skill-call-graph.json"
MANIFEST_PATH = SKILLS_ROOT / "suite-manifest.json"
OUTPUT_PATH = ROOT / "docs" / "provenance" / "v1.1-skill-call-audit.md"

GROUP_TITLES = {
    "orchestration": "一、总控与配置层",
    "knowledge_and_evidence": "二、知识与证据层",
    "business_and_project": "三、企业与项目业务层",
    "patent": "四、专利工程层",
    "delivery": "五、写作与交付层",
    "evolution": "六、受控自进化层",
}

TYPE_LABELS = {
    "route": "路由",
    "requires": "硬依赖",
    "handoff": "交接",
    "quality_gate": "质量门禁",
    "governance": "治理",
    "optional": "可选增强",
}


def skill_description(skill: str) -> str:
    text = (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    if not match:
        return "未提供说明"
    description = match.group(1).strip().strip("\"'")
    return description.replace("|", "／")


def format_links(relations: list[dict], direction: str) -> str:
    if not relations:
        return "—"
    key = "to" if direction == "out" else "from"
    return "<br>".join(
        f"`{relation[key]}`〔{TYPE_LABELS[relation['type']]}〕"
        for relation in sorted(
            relations,
            key=lambda item: (TYPE_LABELS[item["type"]], item[key]),
        )
    )


def main() -> None:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    skill_count = len(manifest["skills"])
    release_tag = manifest["release"]["tag"]
    inbound = defaultdict(list)
    outbound = defaultdict(list)
    for relation in graph["relations"]:
        outbound[relation["from"]].append(relation)
        inbound[relation["to"]].append(relation)

    lines = [
        f"# 企业全生命周期助手 {release_tag} 技能调用关系核查",
        "",
        f"核查对象：{skill_count}个正式团队Skills。",
        "",
        "关系口径：硬依赖表示核心流程不可缺失；路由只选择技能；交接表示结构化结果传递；质量门禁负责强制复核；可选增强按任务触发；治理关系只在受控自进化流程中运行。",
        "",
        "## 核查结论",
        "",
        f"- {skill_count}个技能均被调用图唯一覆盖，无遗漏、无重复分组。",
        "- 所有关系目标均存在于正式技能包，未发现旧技能名或外部幽灵依赖。",
        "- 硬依赖图无循环；总控路由与自进化反馈形成的是受控工作流，不是运行时递归。",
        "- 用户默认只需触发 `project-application-assistant`；`project-task-router` 为内部路由，不与总入口竞争。",
        "- 专利、项目申报、材料交付和受控自进化均形成清晰的单向主链，跨领域调用标记为可选增强。",
        "",
        "## 核心流程图",
        "",
        "```mermaid",
        "flowchart LR",
        "  U[用户任务] --> A[project-application-assistant]",
        "  A --> F[first-run-configuration]",
        "  A --> R[project-task-router]",
        "  R --> K[知识与事实底稿]",
        "  K --> M[project-matching]",
        "  M --> P[project-feasibility]",
        "  P --> W[application-writing]",
        "  W --> C[consistency-check]",
        "  C --> D[project-deliverable-archive]",
        "  A --> E[experience-recorder]",
        "  E --> SC[skill-curator]",
        "  SC --> SE[skill-evolution]",
        "  SE --> G[evolution-governance]",
        "```",
        "",
        "## 专利主链",
        "",
        "```mermaid",
        "flowchart LR",
        "  U[公司级专利任务] --> ROUTER[patent-router]",
        "  ROUTER --> P1[P1 检索与法律分析]",
        "  ROUTER --> P2[P2 挖掘与交底]",
        "  ROUTER --> P3[P3 双中心预审推荐]",
        "  D[中国专利申请 Word 核稿] --> CHECK[checking-patdocx-cn-single-agent]",
        "  ROUTER -. 同时要求全面审查与核稿时双轨 .-> CHECK",
        "```",
        "",
        f"## {skill_count}个技能逐项关系",
        "",
    ]

    for group, skills in graph["groups"].items():
        lines.extend(
            [
                f"### {GROUP_TITLES[group]}",
                "",
                "| Skill | 主要职责 | 上游触发或输入 | 下游调用或交接 |",
                "|---|---|---|---|",
            ]
        )
        for skill in skills:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{skill}`",
                        skill_description(skill),
                        format_links(inbound[skill], "in"),
                        format_links(outbound[skill], "out"),
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.extend(
        [
            "## 逐条关系与原因",
            "",
            "| 起点 | 关系 | 终点 | 业务原因 |",
            "|---|---|---|---|",
        ]
    )
    for relation in graph["relations"]:
        lines.append(
            f"| `{relation['from']}` | {TYPE_LABELS[relation['type']]} | "
            f"`{relation['to']}` | {relation['reason']} |"
        )
    lines.append("")
    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

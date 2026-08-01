from __future__ import annotations

import json
from pathlib import Path

from app.project_decision import (
    project_query_variants,
    project_selection_prompt,
)
from scripts.build_knowledge_content_index import infer_policy_replacement


ROOT = Path(__file__).resolve().parents[3]
PROJECT_REFERENCES = ROOT / "skills" / "project-matching" / "references"


def load_rules():
    return json.loads(
        (PROJECT_REFERENCES / "high-frequency-project-retrieval-rules.json").read_text(
            encoding="utf-8"
        )
    )["rules"]


def load_aliases():
    return json.loads(
        (PROJECT_REFERENCES / "query-aliases.json").read_text(encoding="utf-8")
    )


def load_projects():
    return [
        json.loads(line)
        for line in (
            PROJECT_REFERENCES / "canonical-project-index.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def variants(query: str):
    return project_query_variants(
        query,
        rules=load_rules(),
        project_records=load_projects(),
        configured_aliases=load_aliases(),
    )


def test_future_factory_routes_by_jurisdiction():
    assert variants("杭州市未来工厂怎么申报") == ["杭州市AI工厂"]
    assert variants("浙江省未来工厂怎么申报") == ["浙江省未来工厂"]
    assert project_selection_prompt("未来工厂怎么申报", load_rules()) == (
        "请选择杭州市AI工厂，还是浙江省未来工厂；两个项目属于不同层级。"
    )


def test_old_hangzhou_programs_are_lifecycle_gated():
    old_patent = infer_policy_replacement(
        "杭州市专利试点企业和示范企业认定管理办法.docx",
        "10_政策与目录/历史政策/知识产权项目/杭市管〔2020〕38号.docx",
        "",
        "10_政策与通知",
    )
    assert old_patent["validity_status"] == "superseded"
    assert "知识产权强企" in old_patent["replacement_title"]

    old_future_factory = infer_policy_replacement(
        "2025年杭州市“未来工厂”评定工作的通知.pdf",
        "10_政策与目录/历史政策/杭州市未来工厂/通知.pdf",
        "",
        "10_政策与通知",
    )
    assert old_future_factory["validity_status"] == "historical_reference"
    assert old_future_factory["replacement_title"] == "杭州市AI工厂"

    provincial_future_factory = infer_policy_replacement(
        "2025年浙江省未来工厂申报书.wps",
        "20_申报指南与规则/浙江省未来工厂/申报书.wps",
        "",
        "20_项目规则与指南",
    )
    assert provincial_future_factory["validity_status"] == "active_candidate"

    historical_false_draft = infer_policy_replacement(
        "杭州市知识产权运营服务体系建设专项资金管理办法.docx",
        "10_政策与目录/历史政策/知识产权项目/旧办法.docx",
        "内部附有草案形成过程，但该文件当前位于历史政策层。",
        "10_政策与通知",
    )
    assert historical_false_draft["validity_status"] == "historical_reference"

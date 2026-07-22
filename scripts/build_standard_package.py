#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path


REQUIRED = [
    "skills/manufacturing-tax-risk-analysis/SKILL.md",
    "skills/manufacturing-tax-risk-analysis/scripts/calculate_metrics.py",
    "skills/manufacturing-tax-risk-analysis/references/risk-gates.md",
    "skills/jiaotang-legal-regulations/SKILL.md",
    "skills/jiaotang-legal-regulations/scripts/search_legal_base.py",
    "skills/first-run-configuration/SKILL.md",
    "skills/first-run-configuration/scripts/configure.py",
    "skills/first-run-configuration/scripts/manage_preferences.py",
    "skills/first-run-configuration/scripts/migrate_skill_preferences.py",
    "skills/first-run-configuration/scripts/upgrade_inheritance.py",
    "skills/first-run-configuration/references/first-startup-protocol.md",
    "skills/first-run-configuration/references/preference-inheritance.md",
    "skills/graphify/SKILL.md",
    "skills/skill-curator/SKILL.md",
    "skills/skill-curator/scripts/build_impact_graph.py",
    "skills/skill-curator/scripts/aggregate_corrections.py",
    "skills/skill-curator/references/impact-graph-schema.md",
    "skills/skill-evolution/SKILL.md",
    "skills/evolution-governance/SKILL.md",
    "skills/experience-recorder/SKILL.md",
    "skills/experience-recorder/scripts/record_correction.py",
    "skills/enterprise-panorama-analysis/SKILL.md",
    "skills/enterprise-panorama-analysis/scripts/validate_report_pdf.py",
    "skills/project-deliverable-archive/SKILL.md",
    "skills/project-matching/references/canonical-project-index.jsonl",
    "skills/project-matching/references/high-frequency-project-rules.jsonl",
    "skills/project-matching/references/high-frequency-project-retrieval-rules.json",
    "skills/project-matching/references/high-frequency-project-gold-standard.jsonl",
    "skills/project-application-assistant/scripts/user_region_profile.py",
    "skills/project-application-assistant/references/region-loading-rules.md",
    "skills/third-party-data-indexing/SKILL.md",
    "skills/third-party-data-indexing/scripts/index_engine.py",
    "skills/third-party-data-indexing/scripts/daily_update.py",
    "skills/third-party-data-indexing/scripts/quality_monitor.py",
    "skills/patent-data-foundation/scripts/patent_connector.py",
    "skills/patent-direction-planner/scripts/update_preexamination_catalogs.py",
    "skills/patent-direction-planner/references/preexamination-sources.json",
    "skills/industry-chain-foundation-matcher/references/industry-chain-index.jsonl",
    "skills/industry-chain-foundation-matcher/references/industry-foundation-index.jsonl",
    "skills/industry-chain-foundation-matcher/references/source-documents/产业链架构(2).pdf",
    "skills/industry-chain-foundation-matcher/references/source-documents/工业六基领域目录(2).pdf",
    "docs/user-guide/api-mcp-configuration.md",
    "docs/user-guide/企业全生命周期助手用户使用手册.md",
]

HOST_SKILL_INSTALL_PROMPT = "帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills"
EVOLUTION_SKILLS = (
    "skill-curator",
    "skill-evolution",
    "evolution-governance",
    "experience-recorder",
)
FORBIDDEN_ARCHIVE_PATH_PARTS = {"agents", "__pycache__", ".DS_Store"}
FORBIDDEN_TEXT_SNIPPETS = (
    "/Users/",
    "/Volumes/",
    ".agents/skills",
    "jiaotang-rag-query",
    "patent-lawyer-agent",
    "qcc-quick-scan",
)
RELEASE_GATE_SNIPPETS = {
    "skills/first-run-configuration/SKILL.md": (
        "自动启用受控自进化",
        HOST_SKILL_INSTALL_PROMPT,
        "first-startup-protocol.md",
        "preferences.json",
        "upgrade_inheritance.py",
    ),
    "skills/project-application-assistant/SKILL.md": (
        "必须调用 `experience-recorder`",
        "眼下最没有把握的事情是什么",
        "最大的遗漏是什么",
    ),
    "skills/experience-recorder/SKILL.md": ("强制四问", "不得只把问题抛给用户"),
}


PACKAGE_DOCS = [
    "docs/user-guide/api-mcp-configuration.md",
    "docs/user-guide/企业全生命周期助手用户使用手册.md",
    "docs/config/aiqice.md",
    "docs/config/document-tools.md",
    "docs/config/government-browser.md",
    "docs/config/local-knowledge.md",
    "docs/config/mcp.md",
    "docs/config/models.md",
    "docs/config/paddle-ocr.md",
    "docs/config/qcc.md",
]


def included(path):
    return (
        not any(part in FORBIDDEN_ARCHIVE_PATH_PARTS or part.startswith("._") for part in path.parts)
        and path.suffix not in {".pyc", ".pyo"}
    )


def validate_release_source(root: Path) -> None:
    failures = []
    for skill_name in EVOLUTION_SKILLS:
        if not (root / "skills" / skill_name / "SKILL.md").is_file():
            failures.append(f"缺少自进化Skill：{skill_name}")
    for relative_path, snippets in RELEASE_GATE_SNIPPETS.items():
        path = root / relative_path
        if not path.is_file():
            failures.append(f"缺少发布门禁文件：{relative_path}")
            continue
        content = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in content:
                failures.append(f"{relative_path} 缺少门禁内容：{snippet}")
    retrieval_rules_path = root / "skills/project-matching/references/high-frequency-project-retrieval-rules.json"
    gold_path = root / "skills/project-matching/references/high-frequency-project-gold-standard.jsonl"
    if retrieval_rules_path.is_file() and gold_path.is_file():
        retrieval_rules = json.loads(retrieval_rules_path.read_text(encoding="utf-8"))["rules"]
        aliases = {str(alias) for rule in retrieval_rules for alias in rule.get("aliases", [])}
        gold_cases = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines() if line]
        case_keys = {(str(case["alias"]), str(case["kind"])) for case in gold_cases}
        for alias in aliases:
            for kind in ("positive", "cross-project", "stale"):
                if (alias, kind) not in case_keys:
                    failures.append(f"高频简称缺少{kind}金标准：{alias}")
        if len(gold_cases) != len(aliases) * 3:
            failures.append("高频简称金标准数量与三类门禁不一致")
    if failures:
        raise SystemExit("发布门禁失败：\n- " + "\n- ".join(failures))


def validate_release_archive(output: Path) -> None:
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        required_flags = {
            "automatic_evolution_activation": True,
            "four_question_review": True,
            "host_skill_install_prompt": HOST_SKILL_INSTALL_PROMPT,
            "personal_preference_overlay": True,
            "cross_device_preference_sync": True,
            "three_way_upgrade_inheritance": True,
            "direct_skill_edit_detection": True,
            "legacy_skill_preference_migration": True,
        }
        for skill_name in EVOLUTION_SKILLS:
            if f"skills/{skill_name}/SKILL.md" not in names:
                raise SystemExit(f"发布门禁失败：ZIP缺少自进化Skill {skill_name}")
        for skill_name in ("manufacturing-tax-risk-analysis", "jiaotang-legal-regulations"):
            if f"skills/{skill_name}/SKILL.md" not in names:
                raise SystemExit(f"发布门禁失败：ZIP缺少正式团队Skill {skill_name}")
        if "skills/first-run-configuration/references/first-startup-protocol.md" not in names:
            raise SystemExit("发布门禁失败：ZIP缺少首次启动协议")
        includes = manifest.get("includes", {})
        for name, expected in required_flags.items():
            if includes.get(name) != expected:
                raise SystemExit(f"发布门禁失败：manifest {name} 不符合要求")
        official_hashes = manifest.get("official_skill_hashes", {})
        if len(official_hashes) != manifest.get("skill_count"):
            raise SystemExit("发布门禁失败：官方Skill哈希数量不完整")
        for skill_name, expected_hash in official_hashes.items():
            archive_path = f"skills/{skill_name}/SKILL.md"
            if archive_path not in names:
                raise SystemExit(f"发布门禁失败：哈希对应Skill不存在：{skill_name}")
            actual_hash = hashlib.sha256(archive.read(archive_path)).hexdigest()
            if actual_hash != expected_hash:
                raise SystemExit(f"发布门禁失败：Skill哈希不一致：{skill_name}")
        invalid_paths = [
            name
            for name in names
            if any(part in FORBIDDEN_ARCHIVE_PATH_PARTS or part.startswith("._") for part in Path(name).parts)
        ]
        if invalid_paths:
            raise SystemExit(f"发布门禁失败：ZIP包含平台元数据或缓存：{invalid_paths[:5]}")
        text_suffixes = {".md", ".py", ".json", ".jsonl", ".yaml", ".yml", ".sh", ".txt"}
        forbidden_hits = []
        for name in sorted(names):
            if Path(name).suffix.lower() not in text_suffixes:
                continue
            content = archive.read(name).decode("utf-8", errors="ignore")
            for snippet in FORBIDDEN_TEXT_SNIPPETS:
                if snippet in content:
                    forbidden_hits.append(f"{name}: {snippet}")
        if forbidden_hits:
            raise SystemExit("发布门禁失败：ZIP包含本机路径或旧依赖：\n- " + "\n- ".join(forbidden_hits[:20]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--version", default="2.0.0")
    parser.add_argument("--status", default="release-candidate")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", args.version):
        raise SystemExit("版本号必须使用 MAJOR.MINOR 或 MAJOR.MINOR.PATCH")
    output = args.output or args.root / "dist" / f"企业全生命周期助手-{args.version}.zip"
    missing = [path for path in REQUIRED if not (args.root / path).is_file()]
    if missing:
        raise SystemExit(f"缺少必需资源: {missing}")
    validate_release_source(args.root)
    files = sorted(path for path in (args.root / "skills").rglob("*") if path.is_file() and included(path.relative_to(args.root)))
    documentation = [args.root / path for path in PACKAGE_DOCS]
    official_skill_hashes = {
        path.parent.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
        if path.name == "SKILL.md"
    }
    manifest = {
        "name": "企业全生命周期助手",
        "version": args.version,
        "status": args.status,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "skill_count": sum(1 for path in files if path.name == "SKILL.md"),
        "preference_schema_version": 1,
        "official_skill_hashes": official_skill_hashes,
        "includes": {
            "default_project_map": True,
            "high_frequency_rules": True,
            "region_memory": True,
            "sqlite_dynamic_index": True,
            "daily_collection_workflow": True,
            "collection_quality_monitor": True,
            "patent_data_connector": True,
            "preexamination_catalog_updater": True,
            "industry_chain_catalog": True,
            "industry_foundation_catalog": True,
            "industry_source_pdfs": True,
            "enterprise_panorama_report": True,
            "automatic_workspace_archive": True,
            "api_mcp_user_guide": True,
            "unified_first_run_configuration": True,
            "knowledge_graph": True,
            "controlled_skill_evolution": True,
            "skill_change_impact_graph": True,
            "thresholded_correction_batches": True,
            "automatic_evolution_activation": True,
            "four_question_review": True,
            "host_skill_install_prompt": HOST_SKILL_INSTALL_PROMPT,
            "agent_metadata": False,
            "manufacturing_tax_risk_analysis": True,
            "legal_regulations_dynamic_routing": True,
            "personal_preference_overlay": True,
            "cross_device_preference_sync": True,
            "three_way_upgrade_inheritance": True,
            "direct_skill_edit_detection": True,
            "legacy_skill_preference_migration": True,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(args.root).as_posix())
        for path in documentation:
            archive.write(path, path.relative_to(args.root).as_posix())
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    validate_release_archive(output)
    print(json.dumps({"output": str(output), "files": len(files), **manifest}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

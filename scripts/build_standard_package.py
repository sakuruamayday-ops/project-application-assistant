#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PORTABLE_REPORT_REQUIRED = [
    "skills/manufacturing-tax-risk-analysis/assets/deep-gold-advisor-template.html",
    "skills/manufacturing-tax-risk-analysis/assets/gold-advisor.css",
    "skills/manufacturing-tax-risk-analysis/references/report-data.example.json",
    "skills/manufacturing-tax-risk-analysis/references/report-input-schema.md",
    "skills/manufacturing-tax-risk-analysis/references/report-spec.md",
    "skills/manufacturing-tax-risk-analysis/references/risk-gates.md",
    "skills/manufacturing-tax-risk-analysis/scripts/brand_gold_pdf.py",
    "skills/manufacturing-tax-risk-analysis/scripts/calculate_metrics.py",
    "skills/manufacturing-tax-risk-analysis/scripts/generate_report_html.py",
    "skills/manufacturing-tax-risk-analysis/scripts/render_pdf_stdout.js",
    "skills/manufacturing-tax-risk-analysis/scripts/verify_e2e.py",
    "skills/manufacturing-tax-risk-analysis/package.json",
    "skills/_runtime/jiaotang-branding/runtime-manifest.json",
    "skills/_runtime/jiaotang-branding/requirements.txt",
    "skills/_runtime/jiaotang-branding/references/brand_config.json",
    "skills/_runtime/jiaotang-branding/scripts/brand_config.py",
    "skills/_runtime/jiaotang-branding/scripts/delivery_gate.py",
    "skills/_runtime/jiaotang-branding/scripts/pdf_two_pass.py",
    "skills/_runtime/jiaotang-branding/assets/brand-mark.png",
    "skills/_runtime/jiaotang-branding/assets/brand-gold-07.png",
    "skills/_runtime/jiaotang-branding/assets/brand-gold-10.png",
    "skills/_runtime/jiaotang-branding/assets/brand-gold-12.png",
    "skills/_runtime/jiaotang-branding/assets/brand-gold-16.png",
    "skills/_runtime/jiaotang-branding/assets/brand-red-07.png",
    "skills/_runtime/jiaotang-branding/assets/brand-red-10.png",
    "skills/_runtime/jiaotang-branding/assets/brand-red-12.png",
    "skills/_runtime/jiaotang-branding/assets/brand-red-16.png",
    "skills/_runtime/jiaotang-branding/assets/brand-white-10.png",
    "skills/_runtime/jiaotang-branding/assets/brand-white-16.png",
]

REQUIRED = [
    "skills/manufacturing-tax-risk-analysis/SKILL.md",
    *PORTABLE_REPORT_REQUIRED,
    "containers/portable-report-test.Dockerfile",
    "scripts/run_clean_container_gate.py",
    "skills/jiaotang-legal-regulations/SKILL.md",
    "skills/jiaotang-legal-regulations/scripts/search_legal_base.py",
    "skills/first-run-configuration/SKILL.md",
    "skills/first-run-configuration/scripts/configure.py",
    "skills/first-run-configuration/scripts/manage_preferences.py",
    "skills/first-run-configuration/scripts/migrate_skill_preferences.py",
    "skills/first-run-configuration/scripts/upgrade_inheritance.py",
    "skills/first-run-configuration/references/first-startup-protocol.md",
    "skills/first-run-configuration/references/preference-inheritance.md",
    "skills/first-run-configuration/references/capability-delegation-protocol.md",
    "skills/financial-verification/references/financial-facts-contract.md",
    "skills/financial-verification/scripts/validate_financial_facts.py",
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
    "skills/enterprise-panorama-analysis/references/relationship-graph-spec.md",
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
    "skills/jiaotang-patent-router/SKILL.md",
    "skills/jiaotang-patent-router/scripts/build_ipc_evidence_chain.py",
    "skills/jiaotang-patent-router/scripts/build_claim_prior_art_matrix.py",
    "skills/jiaotang-patent-router/scripts/claim_structure.py",
    "skills/jiaotang-patent-router/references/ipc-snapshots/manifest.json",
    "skills/checking-patdocx-cn-single-agent/SKILL.md",
    "skills/checking-patdocx-cn-single-agent/scripts/patent_extractor.py",
    "skills/checking-patdocx-cn-single-agent/scripts/review_adder.py",
    "skills/checking-patdocx-cn-single-agent/scripts/verify.py",
    "skills/industry-chain-foundation-matcher/references/industry-chain-index.jsonl",
    "skills/industry-chain-foundation-matcher/references/industry-foundation-index.jsonl",
    "skills/industry-chain-foundation-matcher/references/source-documents/产业链架构(2).pdf",
    "skills/industry-chain-foundation-matcher/references/source-documents/工业六基领域目录(2).pdf",
    "skills/standard-drafting/SKILL.md",
    "skills/standard-drafting/references/gbt-1-1-drafting-rules.md",
    "skills/standard-drafting/references/standard-type-structures.md",
    "skills/standard-drafting/assets/standard-draft-template.md",
    "skills/standard-drafting/assets/compilation-note-template.md",
    "skills/standard-drafting/scripts/audit_standard_draft.py",
    "docs/user-guide/api-mcp-configuration.md",
    "docs/user-guide/企业全生命周期助手用户使用手册.docx",
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
    "qcc-quick-scan",
)
LEGACY_BRAND_DUPLICATES = {
    "skills/enterprise-panorama-analysis/references/brand_config.json",
    "skills/enterprise-panorama-analysis/scripts/brand_config.py",
    "skills/enterprise-panorama-analysis/scripts/pdf_two_pass.py",
}
RELEASE_GATE_SNIPPETS = {
    "skills/first-run-configuration/SKILL.md": (
        "自动启用受控自进化",
        HOST_SKILL_INSTALL_PROMPT,
        "first-startup-protocol.md",
        "preferences.json",
        "upgrade_inheritance.py",
        "capability-delegation-protocol.md",
        "天眼查",
    ),
    "skills/local-knowledge-retrieval/SKILL.md": ("企业身份时间轴", "天眼查"),
    "skills/enterprise-profile/SKILL.md": ("天眼查", "企查查", "官方来源"),
    "skills/manufacturing-tax-risk-analysis/SKILL.md": ("enterprise-financial-facts/v1",),
    "skills/project-feasibility/SKILL.md": ("enterprise-financial-facts.v1.json",),
    "skills/project-application-assistant/SKILL.md": (
        "必须调用 `experience-recorder`",
        "眼下最没有把握的事情是什么",
        "最大的遗漏是什么",
    ),
    "skills/experience-recorder/SKILL.md": ("强制四问", "不得只把问题抛给用户"),
    "skills/standard-drafting/SKILL.md": (
        "GB/T 1.1",
        "要求—试验方法—判定规则对应矩阵",
        "audit_standard_draft.py",
    ),
}


PACKAGE_DOCS = [
    "docs/user-guide/api-mcp-configuration.md",
    "docs/config/aiqice.md",
    "docs/config/document-tools.md",
    "docs/config/government-browser.md",
    "docs/config/local-knowledge.md",
    "docs/config/mcp.md",
    "docs/config/models.md",
    "docs/config/paddle-ocr.md",
    "docs/config/qcc.md",
]


def load_release_companion_builder(root: Path):
    path = root / "scripts/release_companions.py"
    specification = importlib.util.spec_from_file_location(
        "standard_package_release_companions", path
    )
    if specification is None or specification.loader is None:
        raise SystemExit("无法加载发布伴随物生成器")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def included(path):
    return (
        not any(part in FORBIDDEN_ARCHIVE_PATH_PARTS or part.startswith("._") for part in path.parts)
        and path.suffix not in {".pyc", ".pyo"}
        and path.as_posix() not in LEGACY_BRAND_DUPLICATES
        and not (
            path.parts[:3] == ("skills", "enterprise-panorama-analysis", "assets")
            and path.name.startswith("brand-")
            and path.suffix.lower() == ".png"
        )
    )


def validate_release_source(root: Path) -> None:
    failures = []
    for relative_path in PORTABLE_REPORT_REQUIRED:
        if not (root / relative_path).is_file():
            failures.append(f"缺少便携报告运行文件：{relative_path}")
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
            "manufacturing_tax_17_page_generator": True,
            "unified_branding_runtime": True,
            "portable_path_gate": True,
            "tax_report_e2e_gate": True,
        }
        for skill_name in EVOLUTION_SKILLS:
            if f"skills/{skill_name}/SKILL.md" not in names:
                raise SystemExit(f"发布门禁失败：ZIP缺少自进化Skill {skill_name}")
        for skill_name in (
            "manufacturing-tax-risk-analysis",
            "jiaotang-legal-regulations",
            "standard-drafting",
        ):
            if f"skills/{skill_name}/SKILL.md" not in names:
                raise SystemExit(f"发布门禁失败：ZIP缺少正式团队Skill {skill_name}")
        if "skills/first-run-configuration/references/first-startup-protocol.md" not in names:
            raise SystemExit("发布门禁失败：ZIP缺少首次启动协议")
        missing_report_files = [
            path for path in PORTABLE_REPORT_REQUIRED if path not in names
        ]
        if missing_report_files:
            raise SystemExit(
                f"发布门禁失败：ZIP缺少便携报告运行文件：{missing_report_files}"
            )
        legacy_duplicates = sorted(LEGACY_BRAND_DUPLICATES & names)
        legacy_duplicates.extend(
            name
            for name in names
            if name.startswith("skills/enterprise-panorama-analysis/assets/brand-")
        )
        if legacy_duplicates:
            raise SystemExit(
                f"发布门禁失败：ZIP仍包含分散品牌运行时副本：{legacy_duplicates}"
            )
        includes = manifest.get("includes", {})
        for name, expected in required_flags.items():
            if includes.get(name) != expected:
                raise SystemExit(f"发布门禁失败：manifest {name} 不符合要求")
        stable = manifest.get("status") == "stable"
        if includes.get("clean_container_gate") is not stable:
            raise SystemExit("发布门禁失败：clean_container_gate与发布状态不一致")
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
        text_suffixes = {
            ".md",
            ".py",
            ".js",
            ".json",
            ".jsonl",
            ".yaml",
            ".yml",
            ".sh",
            ".txt",
            ".html",
            ".css",
        }
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

        runtime_hashes = manifest.get("portable_runtime_hashes", {})
        if set(runtime_hashes) != set(PORTABLE_REPORT_REQUIRED):
            raise SystemExit("发布门禁失败：便携报告运行时哈希清单不完整")
        for name, expected_hash in runtime_hashes.items():
            actual_hash = hashlib.sha256(archive.read(name)).hexdigest()
            if actual_hash != expected_hash:
                raise SystemExit(f"发布门禁失败：便携运行文件哈希不一致：{name}")


def run_stable_container_gate(root: Path, package: Path) -> Path:
    audit_path = package.with_suffix(".container-audit.json")
    command = [
        sys.executable,
        str(root / "scripts" / "run_clean_container_gate.py"),
        "--package",
        str(package),
        "--audit-json",
        str(audit_path),
    ]
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True)
    if completed.returncode:
        detail = completed.stdout.strip() or completed.stderr.strip()
        raise SystemExit(f"stable发布容器门禁失败：{detail}")
    return audit_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--version",
        help="兼容性断言；实际版本始终读取skills/suite-manifest.json",
    )
    parser.add_argument("--status", default="release-candidate")
    args = parser.parse_args()
    suite_manifest = json.loads(
        (args.root / "skills/suite-manifest.json").read_text(encoding="utf-8")
    )
    release = suite_manifest["release"]
    version = release["version"]
    if args.version and args.version != version:
        raise SystemExit(
            "命令行版本与suite-manifest.json不一致："
            f"{args.version} / {version}"
        )
    if args.status not in {"release-candidate", "stable"}:
        raise SystemExit("status只允许release-candidate或stable")
    output = (
        args.output
        or args.root / "dist" / f"企业全生命周期助手-{release['tag']}.zip"
    )
    staging_output = output.with_name(f".{output.name}.staging")
    missing = [path for path in REQUIRED if not (args.root / path).is_file()]
    if missing:
        raise SystemExit(f"缺少必需资源: {missing}")
    validate_release_source(args.root)
    files = sorted(path for path in (args.root / "skills").rglob("*") if path.is_file() and included(path.relative_to(args.root)))
    companion_workspace = tempfile.TemporaryDirectory(
        prefix="standard-package-release-companions-"
    )
    companion_builder = load_release_companion_builder(args.root)
    companion_result = companion_builder.generate(
        args.root,
        Path(companion_workspace.name),
        apply_brand=True,
        render=True,
    )
    documentation = [
        (args.root / path, path)
        for path in PACKAGE_DOCS
    ]
    documentation.extend(
        [
            (
                Path(companion_result["manual"]),
                f"docs/user-guide/{Path(companion_result['manual']).name}",
            ),
            (
                Path(companion_result["companion"]),
                f"docs/releases/{Path(companion_result['companion']).name}",
            ),
        ]
    )
    official_skill_hashes = {
        path.parent.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
        if path.name == "SKILL.md"
    }
    declared_skills = suite_manifest["skills"]
    if sorted(official_skill_hashes) != declared_skills:
        raise SystemExit("技能目录与suite-manifest.json中的skills不一致")
    portable_runtime_hashes = {
        relative_path: hashlib.sha256((args.root / relative_path).read_bytes()).hexdigest()
        for relative_path in PORTABLE_REPORT_REQUIRED
    }
    manifest = {
        "name": "企业全生命周期助手",
        "version": version,
        "release_tag": release["tag"],
        "status": args.status,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "skill_count": len(declared_skills),
        "preference_schema_version": 1,
        "official_skill_hashes": official_skill_hashes,
        "portable_runtime_hashes": portable_runtime_hashes,
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
            "word_user_manual": True,
            "release_companion_audit": True,
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
            "manufacturing_tax_17_page_generator": True,
            "unified_branding_runtime": True,
            "portable_path_gate": True,
            "tax_report_e2e_gate": True,
            "clean_container_gate": args.status == "stable",
            "legal_regulations_dynamic_routing": True,
            "personal_preference_overlay": True,
            "cross_device_preference_sync": True,
            "three_way_upgrade_inheritance": True,
            "direct_skill_edit_detection": True,
            "legacy_skill_preference_migration": True,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(staging_output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(args.root).as_posix())
        for path, archive_name in documentation:
            archive.write(path, archive_name)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    validate_release_archive(staging_output)
    container_audit = None
    if args.status == "stable":
        staging_audit = run_stable_container_gate(args.root, staging_output)
        final_audit = output.with_suffix(".container-audit.json")
        staging_audit.replace(final_audit)
        container_audit = str(final_audit)
    staging_output.replace(output)
    print(
        json.dumps(
            {
                "output": str(output),
                "files": len(files),
                "container_audit": container_audit,
                **manifest,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

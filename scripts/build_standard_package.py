#!/usr/bin/env python3
"""Build and verify the V3 10-skill signed universal suite archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from scripts.public_namespace_gate import require_public_namespace
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from public_namespace_gate import require_public_namespace

from project_assistant.skill_integrity import (  # noqa: E402
    trusted_publisher_fingerprint,
    verify_skill_directory,
)

V3_CORE_SKILLS = (
    "application-reviewer",
    "enterprise-due-diligence",
    "general-grant-writer",
    "gov-project-checkup",
    "hightech-application-writer",
    "manufacturing-tax-risk",
    "patent-docx-reviewer",
    "patent-strategy-assistant",
    "sme-giant-writer",
    "standard-drafting",
)

CORE_ENGINE_REQUIRED = [
    "skills/_core/kb_local.py",
    "skills/_core/timeline_cache.py",
    "skills/_core/fact_ledger.py",
    "skills/_core/doc_io.py",
    "skills/_core/quality_gate.py",
    "skills/_core/v3-delivery-constitution.md",
]

PORTABLE_REPORT_REQUIRED = [
    "skills/manufacturing-tax-risk/assets/deep-gold-advisor-template.html",
    "skills/manufacturing-tax-risk/assets/gold-advisor.css",
    "skills/manufacturing-tax-risk/references/metrics-input.example.json",
    "skills/manufacturing-tax-risk/references/report-data.example.json",
    "skills/manufacturing-tax-risk/references/report-input-schema.md",
    "skills/manufacturing-tax-risk/references/report-spec.md",
    "skills/manufacturing-tax-risk/references/risk-gates.md",
    "skills/manufacturing-tax-risk/scripts/brand_gold_pdf.py",
    "skills/manufacturing-tax-risk/scripts/calculate_metrics.py",
    "skills/manufacturing-tax-risk/scripts/generate_report_html.py",
    "skills/manufacturing-tax-risk/scripts/render_pdf_stdout.js",
    "skills/manufacturing-tax-risk/scripts/verify_e2e.py",
    "skills/manufacturing-tax-risk/package.json",
]

REQUIRED = [
    "skills/suite-manifest.json",
    *CORE_ENGINE_REQUIRED,
    *PORTABLE_REPORT_REQUIRED,
    *[f"skills/{skill}/SKILL.md" for skill in V3_CORE_SKILLS],
    "skills/gov-project-checkup/scripts/run_checkup.py",
    "skills/gov-project-checkup/references/high-frequency-project-rules.jsonl",
    "skills/application-reviewer/scripts/review_application.py",
    "skills/hightech-application-writer/scripts/audit_application_docx.py",
    "skills/hightech-application-writer/scripts/expand_rd_ps_tables.py",
    "skills/hightech-application-writer/scripts/fill_rd_core_innovation.py",
    "skills/sme-giant-writer/scripts/validate_sme_assessment.py",
    "skills/general-grant-writer/scripts/validate_grant_deliverable.py",
    "skills/patent-docx-reviewer/scripts/patent_extractor.py",
    "skills/patent-docx-reviewer/scripts/review_adder.py",
    "skills/patent-strategy-assistant/scripts/build_ipc_evidence_chain.py",
    "skills/standard-drafting/scripts/audit_standard_draft.py",
    "skills/enterprise-due-diligence/scripts/build_standard_html.py",
    "skills/enterprise-due-diligence/scripts/check_company_law.py",
    "docs/user-guide/api-mcp-configuration.md",
]

FORBIDDEN_ARCHIVE_PATH_PARTS = {"agents", "__pycache__", ".DS_Store", "tests"}
FORBIDDEN_TEXT_SNIPPETS = (
    "/Users/",
    "/Volumes/",
    ".agents/skills",
    "jiaotang-rag-query",
    "qcc-quick-scan",
)

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


def included(path: Path) -> bool:
    return (
        not any(part in FORBIDDEN_ARCHIVE_PATH_PARTS or part.startswith("._") for part in path.parts)
        and path.suffix not in {".pyc", ".pyo"}
        and path.as_posix() != "skills/local-skill-reconciliation.json"
        and path.parts[:3] != ("skills", "_runtime", "jiaotang-kb")
    )


def validate_release_source(root: Path, *, verify_signatures: bool = True) -> dict[str, object]:
    failures: list[str] = []
    for relative_path in REQUIRED:
        if not (root / relative_path).is_file():
            failures.append(f"缺少必需发布文件：{relative_path}")
    suite_path = root / "skills/suite-manifest.json"
    if not suite_path.is_file():
        raise SystemExit("发布门禁失败：缺少 skills/suite-manifest.json")
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    declared = sorted(str(s) for s in suite.get("skills", []))
    if declared != sorted(V3_CORE_SKILLS):
        failures.append(f"suite-manifest.json 技能列表与 V3 10 核心技能不一致：{declared}")

    fingerprint = ""
    if verify_signatures and not failures:
        try:
            fingerprint = trusted_publisher_fingerprint(root / "skills")
            with tempfile.TemporaryDirectory(prefix="v3-release-verify-") as ev_dir:
                ev_path = Path(ev_dir)
                for skill_name in declared:
                    verify_skill_directory(
                        root / "skills" / skill_name,
                        evidence_dir=ev_path,
                        label=f"source-{skill_name}",
                        require_signature=True,
                        expected_public_fingerprint=fingerprint,
                    )
        except Exception as exc:
            failures.append(f"V3 技能 Ed25519 验签失败：{exc}")
    if failures:
        raise SystemExit("发布门禁失败：\n- " + "\n- ".join(failures))
    return {"publisher_fingerprint": fingerprint, "skill_count": len(declared)}


def validate_release_archive(output: Path) -> None:
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        for skill_name in V3_CORE_SKILLS:
            if f"skills/{skill_name}/SKILL.md" not in names:
                raise SystemExit(f"发布门禁失败：ZIP缺少 V3 核心技能 {skill_name}")
            if f"skills/{skill_name}/release-manifest.json" not in names:
                raise SystemExit(f"发布门禁失败：ZIP缺少技能签名清单 {skill_name}")
        for path in (*CORE_ENGINE_REQUIRED, *PORTABLE_REPORT_REQUIRED):
            if path not in names:
                raise SystemExit(f"发布门禁失败：ZIP缺少核心运行文件：{path}")
        official_hashes = manifest.get("official_skill_hashes", {})
        if len(official_hashes) != manifest.get("skill_count"):
            raise SystemExit("发布门禁失败：官方Skill哈希数量不完整")
        for skill_name, expected_hash in official_hashes.items():
            archive_path = f"skills/{skill_name}/SKILL.md"
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
        text_suffixes = {".md", ".py", ".js", ".json", ".jsonl", ".yaml", ".yml", ".sh", ".txt", ".html", ".css"}
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


def main() -> None:
    parser = argparse.ArgumentParser(description="构建并验签 V3 10 大核心技能通用发布包")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--version", help="兼容性断言；实际版本始终读取 skills/suite-manifest.json")
    parser.add_argument("--status", default="release-candidate")
    args = parser.parse_args()

    suite_manifest = json.loads((args.root / "skills/suite-manifest.json").read_text(encoding="utf-8"))
    release = suite_manifest["release"]
    version = release["version"]
    if args.version and args.version != version:
        raise SystemExit(f"命令行版本与suite-manifest.json不一致：{args.version} / {version}")
    if args.status not in {"release-candidate", "stable"}:
        raise SystemExit("status只允许release-candidate或stable")

    output = args.output or args.root / "dist" / f"project-application-assistant-skills-{release['tag']}.zip"
    staging_output = output.with_name(f".{output.name}.staging")
    source_meta = validate_release_source(args.root, verify_signatures=True)

    files = sorted(
        path for path in (args.root / "skills").rglob("*")
        if path.is_file() and included(path.relative_to(args.root))
    )
    documentation = [(args.root / path, path) for path in PACKAGE_DOCS if (args.root / path).is_file()]
    official_skill_hashes = {
        path.parent.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
        if path.name == "SKILL.md" and path.parent.parent.name == "skills"
    }
    declared_skills = sorted(suite_manifest["skills"])
    if sorted(official_skill_hashes) != declared_skills:
        raise SystemExit("技能目录与suite-manifest.json中的skills不一致")
    portable_runtime_hashes = {
        relative_path: hashlib.sha256((args.root / relative_path).read_bytes()).hexdigest()
        for relative_path in PORTABLE_REPORT_REQUIRED
    }
    manifest = {
        "name": "政府项目与知识产权全生命周期助手",
        "version": version,
        "release_tag": release["tag"],
        "status": args.status,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "skill_count": len(declared_skills),
        "publisher_fingerprint": source_meta["publisher_fingerprint"],
        "official_skill_hashes": official_skill_hashes,
        "portable_runtime_hashes": portable_runtime_hashes,
        "includes": {
            "v3_core_10_skills": True,
            "unified_core_engine": True,
            "embedded_ed25519_signatures": False,
            "manufacturing_tax_17_page_generator": True,
            "unified_branding_runtime": False,
            "portable_path_gate": True,
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
    require_public_namespace(archives=[staging_output], asset_names=[output.name])
    staging_output.replace(output)
    print(json.dumps({"output": str(output), "files": len(files), **manifest}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

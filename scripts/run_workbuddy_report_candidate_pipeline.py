#!/usr/bin/env python3
"""Run the 12-project private-report and dual-WorkBuddy candidate pipeline.

This is an unsigned candidate workflow.  It generates 24 complete real-client
drafts, renders every page, builds macOS and Windows WorkBuddy RC ZIPs, then
replays template selection from both final ZIPs.  It never builds ZCode.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


PROJECT_IDS = (
    "high-tech-enterprise",
    "specialized-sme",
    "little-giant",
    "first-equipment",
    "first-material",
    "first-software",
    "enterprise-rd-center",
    "manufacturing-excellence",
    "single-champion",
    "green-factory",
    "digitalization",
    "science-plan",
)
REPORT_TYPES = ("preassessment", "feasibility")
PLATFORMS = ("macos", "windows")
FORBIDDEN_TARGETS = ("zcode", "z-code", "z_code")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_json(command: list[str], *, cwd: Path, timeout: int = 1200) -> dict[str, Any]:
    process = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "命令未返回JSON:\n"
            + " ".join(command)
            + "\nstdout:\n"
            + process.stdout[-4000:]
            + "\nstderr:\n"
            + process.stderr[-4000:]
        ) from exc
    if process.returncode != 0 or payload.get("status") not in {"pass", "ok"}:
        raise RuntimeError(
            "命令执行失败:\n"
            + " ".join(command)
            + "\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
    return payload


def safe_extract_zip(archive: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    root = destination.resolve()
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            normalized = member.filename.replace("\\", "/")
            parts = [part for part in normalized.split("/") if part not in {"", "."}]
            canonical = "/".join(parts)
            mode = (member.external_attr >> 16) & 0o170000
            if (
                normalized.startswith("/")
                or re.match(r"^[A-Za-z]:", normalized)
                or ".." in parts
                or "\x00" in normalized
                or mode == 0o120000
                or (canonical in seen and not member.is_dir())
            ):
                raise RuntimeError(f"ZIP包含不安全条目:{member.filename}")
            seen.add(canonical)
            target = (destination / Path(*parts)).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"ZIP路径越界:{member.filename}")
        bundle.extractall(destination)


def git_clean(repo_root: Path) -> str:
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise RuntimeError("候选流水线必须从已提交的清洁工作树运行:\n" + status)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def load_fixture_manifest(path: Path, *, release_tag: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "gongchuang-private-real-client-report-fixtures/v1":
        raise ValueError("真实客户夹具清单schema不匹配")
    if str(payload.get("release_tag") or "") != release_tag:
        raise ValueError("真实客户夹具清单与候选版本不一致")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != len(PROJECT_IDS):
        raise ValueError("必须恰好提供12类真实客户夹具")
    ids = [str(case.get("project_id") or "") for case in cases]
    if tuple(ids) != PROJECT_IDS:
        raise ValueError("客户夹具必须按12类受控项目顺序且不得缺类")
    return cases


def source_skills_root_from_archive(extracted_root: Path) -> tuple[Path, Path]:
    registries = list(extracted_root.rglob("skills/project-feasibility/references/report-template-registry.json"))
    if len(registries) != 1:
        raise RuntimeError(f"最终ZIP内模板索引数量异常:{len(registries)}")
    registry = registries[0]
    return registry.parents[2], registry


def render_report(
    *,
    docx: Path,
    render_dir: Path,
    render_python: Path,
    renderer: Path,
    repo_root: Path,
    office_bin: Path | None,
) -> tuple[Path, list[Path], int]:
    render_dir.mkdir(parents=True, exist_ok=False)
    preferred_office = office_bin or render_python.parent.parent.parent / "bin/override"
    process = subprocess.run(
        [
            str(render_python),
            str(renderer),
            str(docx),
            "--output_dir",
            str(render_dir),
            "--emit_pdf",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
        env={
            **os.environ,
            "TMPDIR": "/private/tmp",
            "PATH": (
                f"{preferred_office}:{render_python.parent.parent.parent / 'bin/override'}:"
                f"{os.environ.get('PATH', '')}"
            ),
        },
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"DOCX渲染失败:{docx.name}\n{process.stdout[-4000:]}\n{process.stderr[-4000:]}"
        )
    pdf = render_dir / f"{docx.stem}.pdf"
    pages = sorted(render_dir.glob("page-*.png"))
    if not pdf.is_file() or not pages:
        raise RuntimeError(f"DOCX渲染产物不完整:{docx.name}")
    import fitz

    document = fitz.open(pdf)
    try:
        page_count = document.page_count
        if page_count != len(pages):
            raise RuntimeError(f"PDF与PNG页数不一致:{docx.name}")
        for index, page in enumerate(document):
            text = page.get_text("text").strip()
            if len(text) < 10:
                raise RuntimeError(f"检出空白或无文本页:{docx.name}:第{index + 1}页")
    finally:
        document.close()
    return pdf, pages, page_count


def build_contact_sheet(
    *,
    reports: list[dict[str, Any]],
    output: Path,
    platform_label: str,
) -> dict[str, Any]:
    from PIL import Image, ImageDraw, ImageFont

    selected: list[tuple[str, Path]] = []
    for item in reports:
        pages = [Path(path) for path in item["page_pngs"]]
        page = pages[len(pages) // 2 if item["report_type"] == "feasibility" else 0]
        selected.append((f"{item['project_id']} | {item['report_type']}", page))
    thumb_w, thumb_h = 340, 470
    label_h = 34
    cols = 4
    rows = (len(selected) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), "#F2F2F2")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, (label, path) in enumerate(selected):
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb_w - 12, thumb_h - 12))
        x = (index % cols) * thumb_w + (thumb_w - image.width) // 2
        y = (index // cols) * (thumb_h + label_h) + 6
        canvas.paste(image, (x, y))
        draw.text(
            ((index % cols) * thumb_w + 8, (index // cols) * (thumb_h + label_h) + thumb_h + 6),
            label,
            fill="#222222",
            font=font,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return {
        "status": "pending-visual-review",
        "platform": platform_label,
        "path": str(output),
        "sha256": sha256_file(output),
        "sample_count": len(selected),
    }


def materialize_and_fill(
    *,
    selector_module: Any,
    filler_module: Any,
    registry: Path,
    case: dict[str, Any],
    report_type: str,
    output_dir: Path,
    release_tag: str,
    public_root: Path,
    suffix: str,
) -> dict[str, Any]:
    selection = selector_module.resolve_template(
        case["project_id"],
        report_type,
        registry_path=registry,
    )
    selection_receipt = selector_module.materialize(
        selection,
        output_dir,
        enterprise=str(case["enterprise"]),
        output_name=(
            f"{case['enterprise']}_{selection['project_label']}_{selection['report_label']}_{suffix}.docx"
        ),
    )
    master = Path(selection_receipt["output_path"])
    draft = master.with_name(master.stem + "_完整成稿.docx")
    completed = filler_module.complete_report(
        template_path=master,
        output_path=draft,
        fixture=case,
        report_type=report_type,
        release_tag=release_tag,
        public_root=public_root,
    )
    return {
        "selection": selection_receipt,
        "completion": completed,
        "docx": draft,
    }


def sanitize_receipt(value: Any, cases: list[dict[str, Any]]) -> Any:
    text = json.dumps(value, ensure_ascii=False)
    secrets: set[str] = set()
    for case in cases:
        secrets.add(str(case.get("enterprise") or ""))
        for material in case.get("materials", []):
            secrets.add(str(material.get("path") or ""))
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "[PRIVATE]")
    return json.loads(text)


def scan_archive_privacy(archive: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    enterprise_names = [str(case["enterprise"]) for case in cases]
    path_strings = [
        str(material["path"])
        for case in cases
        for material in case.get("materials", [])
    ]
    needles = [item.encode("utf-8") for item in enterprise_names + path_strings if item]
    findings: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if any(name and name in member.filename for name in enterprise_names):
                findings.append(member.filename)
                continue
            if member.is_dir():
                continue
            data = bundle.read(member)
            if any(needle in data for needle in needles):
                findings.append(member.filename)
    if findings:
        raise RuntimeError("候选包混入真实客户信息:" + ",".join(findings))
    return {"status": "pass", "archive": str(archive), "finding_count": 0}


def run_pipeline(options: argparse.Namespace) -> dict[str, Any]:
    repo_root = options.repo_root.expanduser().resolve()
    skills_root = repo_root / "skills"
    fixture_manifest = options.fixtures.expanduser().resolve()
    output_root = options.output_dir.expanduser().resolve()
    release_manager = options.release_manager_root.expanduser().resolve()
    renderer = options.renderer.expanduser().resolve()
    render_python = options.render_python.expanduser().resolve()
    office_bin = options.office_bin.expanduser().resolve() if options.office_bin else None
    if office_bin is not None and not (office_bin / "soffice").is_file():
        raise FileNotFoundError(f"指定Office渲染器不存在:{office_bin / 'soffice'}")
    if output_root.exists():
        raise FileExistsError(f"候选流水线输出已存在，拒绝覆盖:{output_root}")
    if any(marker in str(output_root).casefold() for marker in FORBIDDEN_TARGETS):
        raise ValueError("本候选流水线禁止产生ZCode产物")
    git_head = git_clean(repo_root)
    suite_manifest = json.loads((skills_root / "suite-manifest.json").read_text(encoding="utf-8"))
    if suite_manifest["release"]["tag"] != options.release_tag:
        raise ValueError("清单版本与候选版本不一致")
    released_adapters = suite_manifest["release"]["one_step_installation_protocol"]["released_adapters"]
    if released_adapters != ["workbuddy-macos", "workbuddy-windows"]:
        raise ValueError("候选流水线仅允许macOS和Windows WorkBuddy两个适配器")
    cases = load_fixture_manifest(fixture_manifest, release_tag=options.release_tag)
    release_manager_scripts = release_manager / "scripts"
    if str(release_manager_scripts) not in sys.path:
        sys.path.insert(0, str(release_manager_scripts))
    release_collection = load_module(
        "workbuddy_candidate_release_collection",
        release_manager_scripts / "package_skill_collection.py",
    )
    release_gates = release_collection.run_release_gates(
        repo_root,
        skills_root,
        suite_manifest,
    )
    if release_gates.get("status") != "pass":
        raise RuntimeError(
            "源码候选门禁失败:"
            + "\uff1b".join(str(item) for item in release_gates.get("failed", []))
        )
    selector = load_module(
        "project_report_selector_source",
        skills_root / "project-feasibility/scripts/select_report_template.py",
    )
    filler = load_module(
        "project_report_filler",
        skills_root / "project-feasibility/scripts/fill_report_template.py",
    )
    source_registry = skills_root / "project-feasibility/references/report-template-registry.json"
    output_root.mkdir(parents=True)
    primary_root = output_root / "01_12类真实客户完整成稿"
    render_root = output_root / "02_逐页渲染与视觉抽检"
    package_root = output_root / "03_WorkBuddy未签名候选包"
    post_zip_root = output_root / "04_最终ZIP模板调用回归"
    receipts_root = output_root / "05_候选流水线回执"
    for path in (primary_root, render_root, package_root, post_zip_root, receipts_root):
        path.mkdir(parents=True, exist_ok=True)
    primary_reports: list[dict[str, Any]] = []
    for case in cases:
        project_dir = primary_root / case["project_id"]
        project_dir.mkdir()
        for report_type in REPORT_TYPES:
            built = materialize_and_fill(
                selector_module=selector,
                filler_module=filler,
                registry=source_registry,
                case=case,
                report_type=report_type,
                output_dir=project_dir,
                release_tag=options.release_tag,
                public_root=repo_root,
                suffix="源码模板",
            )
            docx = built["docx"]
            report_render_dir = render_root / case["project_id"] / report_type
            pdf, pages, page_count = render_report(
                docx=docx,
                render_dir=report_render_dir,
                render_python=render_python,
                renderer=renderer,
                repo_root=repo_root,
                office_bin=office_bin,
            )
            delivery_pdf = project_dir / f"{docx.stem}.pdf"
            shutil.copy2(pdf, delivery_pdf)
            profile_id = str(built["selection"]["profile_id"])
            profile_validator = load_module(
                f"profile_validator_{case['project_id']}_{report_type}",
                skills_root / "project-feasibility/scripts/validate_report_profile_delivery.py",
            )
            profile = profile_validator.validate_profile(
                plugin_root=repo_root,
                profile_id=profile_id,
                artifacts=[docx, delivery_pdf],
                template_selection_receipt=Path(built["selection"]["receipt_path"]),
                completion_receipt=Path(built["completion"]["receipt_path"]),
            )
            if profile["status"] != "pass":
                raise RuntimeError(
                    f"报告画像门禁失败:{case['project_id']}/{report_type}:"
                    + "；".join(profile["errors"])
                )
            primary_reports.append(
                {
                    "project_id": case["project_id"],
                    "report_type": report_type,
                    "enterprise": case["enterprise"],
                    "docx": str(docx),
                    "docx_sha256": sha256_file(docx),
                    "pdf": str(delivery_pdf),
                    "pdf_sha256": sha256_file(delivery_pdf),
                    "page_count": page_count,
                    "page_pngs": [str(path) for path in pages],
                    "selection_receipt": built["selection"]["receipt_path"],
                    "completion_receipt": built["completion"]["receipt_path"],
                    "profile_validation": profile,
                }
            )
    contact_sheet = build_contact_sheet(
        reports=primary_reports,
        output=render_root / "12类双报告视觉抽检联系表.png",
        platform_label="source-completed-reports",
    )
    package_results: dict[str, Any] = {}
    archives: dict[str, Path] = {}
    for platform in PLATFORMS:
        payload = run_json(
            [
                sys.executable,
                str(release_manager / "scripts/package_workbuddy_suite.py"),
                "--skills-root",
                str(skills_root),
                "--output-dir",
                str(package_root),
                "--release-tag",
                options.release_tag,
                "--platform",
                platform,
                "--candidate-mode",
            ],
            cwd=repo_root,
            timeout=1800,
        )
        if payload.get("candidate_mode") is not True or payload.get("formal_release_eligible") is not False:
            raise RuntimeError(f"{platform} WorkBuddy未以未签名候选模式产出")
        archive = Path(payload["archive"]).resolve()
        archives[platform] = archive
        package_results[platform] = payload
    post_zip_reports: list[dict[str, Any]] = []
    privacy_results: list[dict[str, Any]] = []
    for platform, archive in archives.items():
        privacy_results.append(scan_archive_privacy(archive, cases))
        extracted = post_zip_root / f"{platform}_extracted"
        safe_extract_zip(archive, extracted)
        installed_skills, installed_registry = source_skills_root_from_archive(extracted)
        installed_selector = load_module(
            f"project_report_selector_{platform}",
            installed_skills / "project-feasibility/scripts/select_report_template.py",
        )
        installed_filler = load_module(
            f"project_report_filler_{platform}",
            installed_skills / "project-feasibility/scripts/fill_report_template.py",
        )
        platform_report_dir = post_zip_root / f"{platform}_completed"
        platform_report_dir.mkdir()
        for case in cases:
            project_dir = platform_report_dir / case["project_id"]
            project_dir.mkdir()
            for report_type in REPORT_TYPES:
                built = materialize_and_fill(
                    selector_module=installed_selector,
                    filler_module=installed_filler,
                    registry=installed_registry,
                    case=case,
                    report_type=report_type,
                    output_dir=project_dir,
                    release_tag=options.release_tag,
                    public_root=repo_root,
                    suffix=f"{platform}_最终ZIP模板",
                )
                source_match = next(
                    item
                    for item in primary_reports
                    if item["project_id"] == case["project_id"] and item["report_type"] == report_type
                )
                if built["selection"]["template_sha256"] != json.loads(
                    Path(source_match["selection_receipt"]).read_text(encoding="utf-8")
                )["template_sha256"]:
                    raise RuntimeError(f"最终ZIP模板哈希漂移:{platform}/{case['project_id']}/{report_type}")
                post_zip_reports.append(
                    {
                        "platform": platform,
                        "project_id": case["project_id"],
                        "report_type": report_type,
                        "docx": str(built["docx"]),
                        "docx_sha256": sha256_file(built["docx"]),
                        "template_sha256": built["selection"]["template_sha256"],
                        "completion_status": built["completion"]["status"],
                    }
                )
    if len(post_zip_reports) != len(PLATFORMS) * len(PROJECT_IDS) * len(REPORT_TYPES):
        raise RuntimeError("最终ZIP模板调用次数不是48次")
    package_artifacts = {
        platform: {"path": str(archive), "sha256": sha256_file(archive)}
        for platform, archive in archives.items()
    }
    post_package_gates = release_collection.run_post_package_gates(
        repo_root,
        suite_manifest,
        package_artifacts,
        receipts_root / "post-package-gate-work",
    )
    if post_package_gates.get("status") != "pass":
        raise RuntimeError(
            "最终ZIP候选门禁失败:"
            + "\uff1b".join(str(item) for item in post_package_gates.get("failed", []))
        )
    public_receipt = sanitize_receipt(
        {
            "schema": "gongchuang-workbuddy-report-candidate-pipeline/v1",
            "status": "pending",
            "automated_gate_status": "pass",
            "candidate_state": "pending-visual-review",
            "candidate_ready_for_host_testing": False,
            "release_tag": options.release_tag,
            "candidate_only": True,
            "formal_release_eligible": False,
            "zcode": {
                "status": "not-built-not-tested",
                "reason": "用户明确排除ZCode候选包，待独立测试后再立项",
            },
            "source_commit": git_head,
            "project_count": len(cases),
            "report_type_count": len(REPORT_TYPES),
            "primary_completed_docx_count": len(primary_reports),
            "primary_completed_pdf_count": len(primary_reports),
            "primary_rendered_page_count": sum(item["page_count"] for item in primary_reports),
            "final_zip_count": len(archives),
            "final_zip_template_call_count": len(post_zip_reports),
            "platforms": list(PLATFORMS),
            "packages": package_results,
            "privacy_scans": privacy_results,
            "release_gates": release_gates,
            "post_package_gates": post_package_gates,
            "contact_sheet": contact_sheet,
            "visual_review": {
                "status": "pending-visual-review",
                "all_pages_rendered": True,
                "sample_strategy": "前期评估抽首页，可行性分析抽中间条件页，覆盖12类24份成稿",
                "finalizer": "scripts/record_workbuddy_report_visual_review.py",
            },
            "real_host_acceptance": {
                "macos": "pending-real-host-receipt",
                "windows": "pending-real-host-receipt",
            },
        },
        cases,
    )
    receipt_path = receipts_root / f"candidate-pipeline-{options.release_tag}.json"
    write_json(receipt_path, public_receipt)
    private_inventory = {
        "schema": "gongchuang-private-real-client-report-output/v1",
        "release_tag": options.release_tag,
        "fixture_manifest": str(fixture_manifest),
        "reports": primary_reports,
        "post_zip_reports": post_zip_reports,
    }
    private_receipt_path = receipts_root / f"private-output-inventory-{options.release_tag}.json"
    write_json(private_receipt_path, private_inventory)
    return {
        **public_receipt,
        "receipt_path": str(receipt_path),
        "private_inventory_path": str(private_receipt_path),
        "output_dir": str(output_root),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, required=True)
    result.add_argument("--fixtures", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--release-tag", required=True)
    result.add_argument("--release-manager-root", type=Path, required=True)
    result.add_argument("--renderer", type=Path, required=True)
    result.add_argument("--render-python", type=Path, required=True)
    result.add_argument("--office-bin", type=Path)
    return result


def main() -> int:
    options = parser().parse_args()
    try:
        result = run_pipeline(options)
    except Exception as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

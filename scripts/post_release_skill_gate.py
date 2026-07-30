#!/usr/bin/env python3
"""从正式签名通用包原子升级本机Skills，并输出三方一致性审计。"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from project_assistant.installer import install_skills  # noqa: E402
from project_assistant.skill_integrity import (  # noqa: E402
    audit_skill_layers,
    trusted_publisher_fingerprint,
    verify_suite_bundle,
)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def safe_extract_zip(archive: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"审计解压目录已存在，拒绝覆盖：{destination}")
    destination.mkdir(parents=True)
    resolved_destination = destination.resolve()
    seen: set[str] = set()
    with zipfile.ZipFile(archive, "r") as bundle:
        for member in bundle.infolist():
            normalized = member.filename.replace("\\", "/")
            parts = [
                part for part in normalized.split("/") if part not in {"", "."}
            ]
            canonical = "/".join(parts)
            mode = (member.external_attr >> 16) & 0o170000
            if (
                normalized.startswith("/")
                or re.match(r"^[A-Za-z]:", normalized)
                or ".." in parts
                or "\x00" in normalized
                or mode == stat.S_IFLNK
            ):
                raise RuntimeError(f"正式包包含不安全条目：{member.filename}")
            if canonical in seen and not member.is_dir():
                raise RuntimeError(f"正式包包含重复条目：{member.filename}")
            seen.add(canonical)
            target = (destination / Path(*parts)).resolve()
            if (
                target != resolved_destination
                and resolved_destination not in target.parents
            ):
                raise RuntimeError(f"正式包路径越界：{member.filename}")
        bundle.extractall(destination)


def locate_bundle_root(extracted_root: Path) -> Path:
    candidates = sorted(
        path.parent
        for path in extracted_root.rglob("suite-release-manifest.json")
        if (path.parent / "skills" / "suite-manifest.json").is_file()
    )
    if len(candidates) != 1:
        raise RuntimeError(
            "通用正式包必须且只能包含一个签名Skill套件，"
            f"当前识别到{len(candidates)}个"
        )
    return candidates[0]


def normalize_development_root(path: Path) -> Path:
    path = path.expanduser().resolve()
    if (path / "suite-manifest.json").is_file():
        return path
    if (path / "skills" / "suite-manifest.json").is_file():
        return path / "skills"
    raise FileNotFoundError(f"开发源缺少skills/suite-manifest.json：{path}")


def run_gate(
    *,
    development_root: Path,
    release_archive: Path,
    install_root: Path,
    config_dir: Path,
    audit_dir: Path,
    report_path: Path | None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    run_id = timestamp()
    started_at = datetime.now(timezone.utc).isoformat()
    development_root = normalize_development_root(development_root)
    release_archive = release_archive.expanduser().resolve()
    install_root = install_root.expanduser().resolve()
    config_dir = config_dir.expanduser().resolve()
    audit_dir = audit_dir.expanduser().resolve()
    evidence_dir = audit_dir / "evidence" / run_id
    extracted_root = evidence_dir / "release-extracted"
    report_path = (
        report_path.expanduser().resolve()
        if report_path
        else audit_dir / f"{run_id}.json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": started_at,
        "status": "fail",
        "development_root": str(development_root),
        "release_archive": str(release_archive),
        "install_root": str(install_root),
        "config_dir": str(config_dir),
        "evidence_dir": str(evidence_dir),
        "report_path": str(report_path),
        "command": list(command or []),
        "stages": {},
    }
    try:
        if not release_archive.is_file():
            raise FileNotFoundError(f"通用正式包不存在：{release_archive}")
        safe_extract_zip(release_archive, extracted_root)
        bundle_root = locate_bundle_root(extracted_root)
        release_root = bundle_root / "skills"
        report["bundle_root"] = str(bundle_root)
        trusted_fingerprint = trusted_publisher_fingerprint(
            development_root
        )

        suite_verification = verify_suite_bundle(
            bundle_root,
            evidence_dir=evidence_dir / "suite-signature",
            expected_public_fingerprint=trusted_fingerprint,
        )
        report["stages"]["suite_verification"] = suite_verification

        pre_deploy = audit_skill_layers(
            development_root=development_root,
            release_root=release_root,
            install_root=None,
            evidence_dir=evidence_dir / "pre-deploy-signatures",
        )
        report["stages"]["pre_deploy_three_way"] = pre_deploy
        if pre_deploy["status"] != "pass":
            raise RuntimeError(
                "开发源与正式包不一致，禁止部署："
                + "、".join(pre_deploy["failures"][:20])
            )

        install_report: dict[str, Any] = {}
        installed = install_skills(
            release_root,
            install_root,
            "copy",
            True,
            config_dir,
            str(suite_verification.get("release_version") or "unknown"),
            command=command,
            report_out=install_report,
            require_signatures=True,
        )
        report["stages"]["atomic_install"] = {
            **install_report,
            "installed_count": len(installed),
        }
        expected_count = int(suite_verification.get("skill_count") or 0)
        if len(installed) != expected_count:
            raise RuntimeError(
                f"原子升级数量不完整：应安装{expected_count}项，实际{len(installed)}项"
            )

        post_deploy = audit_skill_layers(
            development_root=development_root,
            release_root=release_root,
            install_root=install_root,
            evidence_dir=evidence_dir / "post-deploy-signatures",
        )
        report["stages"]["post_deploy_three_way"] = post_deploy
        if post_deploy["status"] != "pass":
            raise RuntimeError(
                "部署后三方一致性审计失败："
                + "、".join(post_deploy["failures"][:20])
            )
        if (
            post_deploy["verified_skill_signatures"] != expected_count
            or post_deploy["verified_install_signatures"] != expected_count
        ):
            raise RuntimeError("部署后全量验签数量不完整")

        report["status"] = "pass"
        report["summary"] = {
            "release_tag": suite_verification.get("release_tag"),
            "release_version": suite_verification.get("release_version"),
            "suite_signature": "verified",
            "skill_count": expected_count,
            "release_skill_signatures_verified": post_deploy[
                "verified_skill_signatures"
            ],
            "installed_skill_signatures_verified": post_deploy[
                "verified_install_signatures"
            ],
            "development_release_install_match": True,
            "atomic_install": "committed",
            "signed_install_read_only": True,
        }
    except Exception as exc:
        report["error"] = str(exc)
        raise RuntimeError(
            f"{exc}；审计报告：{report_path}"
        ) from exc
    finally:
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_json(report_path, report)
    return report


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="正式发布后的本机原子升级、全量验签和三方哈希门禁"
    )
    command.add_argument("--development-root", type=Path, required=True)
    command.add_argument("--release-archive", type=Path, required=True)
    command.add_argument(
        "--install-root",
        type=Path,
        default=Path.home() / ".codex" / "skills",
    )
    command.add_argument(
        "--config-dir",
        type=Path,
        default=Path.home() / ".config" / "project-assistant",
    )
    command.add_argument(
        "--audit-dir",
        type=Path,
        default=Path.home()
        / ".config"
        / "project-assistant"
        / "deployment-audits",
    )
    command.add_argument("--report", type=Path)
    return command


def main() -> int:
    arguments = parser().parse_args()
    try:
        result = run_gate(
            development_root=arguments.development_root,
            release_archive=arguments.release_archive,
            install_root=arguments.install_root,
            config_dir=arguments.config_dir,
            audit_dir=arguments.audit_dir,
            report_path=arguments.report,
            command=[sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "summary": result.get("summary"),
                    "report": result["report_path"],
                    "evidence_dir": result["evidence_dir"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print(
            json.dumps(
                {"status": "fail", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

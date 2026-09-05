#!/usr/bin/env python3
"""Build the signed generic suite for the current host-neutral release.

The collection manifest is authoritative: the first-party client consumes the
same signed suite and no platform-specific plugin is emitted. This builder
preserves the release-gate, signing, provenance, archive and post-package
validation contracts for the one permitted artifact.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_MANAGER_ROOT = Path.home() / ".codex" / "skills" / "skill-release-manager"
DEFAULT_SIGNING_KEY = Path.home() / ".codex" / "skill-signing" / "jiaotang-skill-release-ed25519"
DEFAULT_PUBLIC_KEY = DEFAULT_SIGNING_KEY.with_suffix(".pub")


def load_module(path: Path, name: str):
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载发布管理器模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按套件清单构建并验证唯一的通用签名 Skills 包"
    )
    parser.add_argument("--skills-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-tag")
    parser.add_argument("--signing-key", type=Path, default=DEFAULT_SIGNING_KEY)
    parser.add_argument("--public-key", type=Path, default=DEFAULT_PUBLIC_KEY)
    parser.add_argument(
        "--release-manager-root", type=Path, default=DEFAULT_MANAGER_ROOT
    )
    return parser.parse_args()


def invoke_json(command: list[str], *, cwd: Path) -> dict:
    process = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "通用包构建器未返回有效 JSON：" + (process.stdout or process.stderr)[-4000:]
        ) from exc
    if process.returncode or payload.get("status") != "pass":
        raise RuntimeError(str(payload.get("errors") or payload))
    return payload


def existing_gate_attestation_paths(gate_report: Path) -> list[Path]:
    """Return immutable gate evidence paths that already occupy this release name."""
    candidates = [
        gate_report,
        gate_report.with_name(gate_report.name + ".sig"),
        gate_report.with_name(gate_report.name + ".signature.json"),
        gate_report.with_name(gate_report.stem + "-publisher-ed25519.pub"),
    ]
    return [path for path in candidates if path.exists()]


def main() -> int:
    options = parse_args()
    skills_root = options.skills_root.expanduser().resolve()
    source_root = skills_root.parent
    output_dir = options.output_dir.expanduser().resolve()
    manager_root = options.release_manager_root.expanduser().resolve()
    collection = load_module(
        manager_root / "scripts" / "package_skill_collection.py",
        "gongchuang_release_collection",
    )
    suite = load_module(
        manager_root / "scripts" / "suite_validation.py",
        "gongchuang_release_suite_validation_for_generic",
    )
    package = load_module(
        manager_root / "scripts" / "package_skill_release.py",
        "gongchuang_release_package_for_generic",
    )
    public_key = options.public_key.expanduser().resolve()
    signing_key = options.signing_key.expanduser().resolve()
    package.validate_official_public_key(public_key)
    source_validation = suite.validate_suite(skills_root)
    if source_validation["status"] != "pass":
        print(json.dumps(source_validation, ensure_ascii=False, indent=2))
        return 2
    manifest = suite.load_suite_manifest(skills_root)
    distribution = manifest.get("release", {}).get("distribution_protocol", {})
    if not (
        distribution.get("generic_skill_package") == "signed-universal-zip"
        and distribution.get("platform_specific_package") is False
    ):
        print(json.dumps({"status": "fail", "errors": ["当前套件未声明仅通用包发布"]}, ensure_ascii=False, indent=2))
        return 2
    release_tag, _ = suite.release_identity(manifest, options.release_tag)
    output_dir.mkdir(parents=True, exist_ok=True)
    gate_report = output_dir / f"release-gates-{release_tag}.json"
    occupied = existing_gate_attestation_paths(gate_report)
    if occupied:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "release_tag": release_tag,
                    "errors": [
                        "发布证据名称已被占用；请使用新的空输出目录，现有证据不会被覆盖"
                    ],
                    "existing_evidence": [path.name for path in occupied],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    pre_gates = collection.run_release_gates(source_root, skills_root, manifest)
    if pre_gates["status"] != "pass":
        pre_gates["final_artifacts"] = {}
        pre_gates["post_package_gates"] = {"status": "not-run", "failed": ["pre-package-release-gates"], "results": []}
        pre_gates["final_artifacts_complete"] = False
        collection.finalize_gate_attestation(
            gate_report, pre_gates, private_key=signing_key, public_key=public_key
        )
        print(json.dumps(pre_gates, ensure_ascii=False, indent=2))
        return 2
    try:
        generic = invoke_json(
            [
                sys.executable,
                str(manager_root / "scripts" / "package_skill_suite.py"),
                "--skills-root", str(skills_root),
                "--output-dir", str(output_dir),
                "--release-tag", release_tag,
                "--signing-key", str(signing_key),
                "--public-key", str(public_key),
            ],
            cwd=source_root,
        )
        artifacts = {
            "generic": {
                "path": str(Path(generic["artifact"]).resolve()),
                "sha256": str(generic["sha256"]),
            }
        }
        post_workspace = collection.recoverable_staging_directory(
            "generic-post-package-release-gates-"
        )
        post_gates = collection.run_post_package_gates(
            source_root, manifest, artifacts, post_workspace
        )
        report = {
            **pre_gates,
            "final_artifacts": artifacts,
            "post_package_gates": post_gates,
            "platform_specific_package": {"status": "not-applicable", "reason": "suite-manifest declares a host-neutral generic release"},
            "final_artifacts_complete": post_gates["status"] == "pass",
        }
        report = collection.publicize_gate_paths(report, source_root)
        attestation = collection.finalize_gate_attestation(
            gate_report, report, private_key=signing_key, public_key=public_key
        )
        print(
            json.dumps(
                {
                    "status": "pass" if report["final_artifacts_complete"] else "partial",
                    "release_tag": release_tag,
                    "artifact": artifacts["generic"],
                    "release_gate_report": str(gate_report),
                    "release_gate_attestation": attestation,
                    "post_package_gates": post_gates,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if report["final_artifacts_complete"] else 2
    except Exception as exc:
        failed = {
            **pre_gates,
            "final_artifacts": {},
            "post_package_gates": {"status": "fail", "failed": ["generic-suite-build"], "results": [{"name": "generic-suite-build", "status": "fail", "stderr": str(exc)}]},
            "final_artifacts_complete": False,
        }
        collection.finalize_gate_attestation(
            gate_report, failed, private_key=signing_key, public_key=public_key
        )
        print(json.dumps(failed, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

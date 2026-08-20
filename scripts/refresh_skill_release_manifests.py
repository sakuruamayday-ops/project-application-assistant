#!/usr/bin/env python3
"""Refresh the embedded manifests for a signed generic skill-suite release.

The suite is distributed as one signed generic archive.  Each contained skill
still has an embedded manifest and Ed25519 signature, so an edited SKILL.md
cannot be silently accepted by the archive's own installation check.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


DEFAULT_MANAGER_ROOT = Path.home() / ".codex" / "skills" / "skill-release-manager"
DEFAULT_POLICY_DIR = Path.home() / ".codex" / "skill-release-policies" / "workbuddy-current"
DEFAULT_SIGNING_KEY = Path.home() / ".codex" / "skill-signing" / "jiaotang-skill-release-ed25519"
DEFAULT_PUBLIC_KEY = DEFAULT_SIGNING_KEY.with_suffix(".pub")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载发布管理器模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="刷新通用 Skills 套件中每项技能的清单与 Ed25519 签名"
    )
    parser.add_argument("--skills-root", type=Path, required=True)
    parser.add_argument("--policy-dir", type=Path, default=DEFAULT_POLICY_DIR)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--signing-key", type=Path, default=DEFAULT_SIGNING_KEY)
    parser.add_argument("--public-key", type=Path, default=DEFAULT_PUBLIC_KEY)
    parser.add_argument(
        "--release-manager-root", type=Path, default=DEFAULT_MANAGER_ROOT
    )
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    skills_root = options.skills_root.expanduser().resolve()
    policy_dir = options.policy_dir.expanduser().resolve()
    manager_root = options.release_manager_root.expanduser().resolve()
    package = load_module(
        manager_root / "scripts" / "package_skill_release.py",
        "gongchuang_release_package_skill",
    )
    suite = load_module(
        manager_root / "scripts" / "suite_validation.py",
        "gongchuang_release_suite_validation",
    )
    package.validate_official_public_key(options.public_key.expanduser().resolve())
    validation = suite.validate_suite(skills_root)
    if validation["status"] != "pass":
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 2
    release_tag, _ = suite.release_identity(
        suite.load_suite_manifest(skills_root), options.release_tag
    )
    results: list[dict] = []
    for skill in suite.skill_directories(skills_root):
        policy = policy_dir / f"{skill.name}.json"
        try:
            required, terms, mutable_paths, runtime_requirements = package.load_policy(policy)
            missing = [item for item in required if not (skill / item).exists()]
            if missing:
                raise ValueError("缺少必需路径：" + "、".join(missing))
            findings: list[str] = []
            for path in package.files(skill, mutable_paths=mutable_paths):
                findings.extend(
                    package.scan(path, path.relative_to(skill).as_posix(), terms)
                )
            if findings:
                raise ValueError("脱敏扫描失败：\n" + "\n".join(findings))
            package.write_manifest(
                skill,
                skill.name,
                release_tag,
                required,
                mutable_paths,
                runtime_requirements,
            )
            package.write_embedded_signature(
                skill,
                options.signing_key.expanduser().resolve(),
                options.public_key.expanduser().resolve(),
            )
            checked = package.install_check(skill)
            results.append(
                {
                    "skill": skill.name,
                    "status": "pass",
                    "checked_files": checked["checked_files"],
                }
            )
        except Exception as exc:
            results.append({"skill": skill.name, "status": "fail", "error": str(exc)})
    failed = [result["skill"] for result in results if result["status"] != "pass"]
    print(
        json.dumps(
            {
                "status": "pass" if not failed else "fail",
                "release_tag": release_tag,
                "skill_count": len(results),
                "failed": failed,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())

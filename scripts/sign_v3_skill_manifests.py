#!/usr/bin/env python3
"""Generate and Ed25519-sign embedded release-manifest.json for all 10 V3 skills."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from project_assistant.skill_integrity import (  # noqa: E402
    SIGNATURE_FILES,
    public_key_fingerprint,
    sha256_file,
    trusted_publisher_fingerprint,
    verify_skill_directory,
)

DEFAULT_SIGNING_KEY = Path.home() / ".codex" / "skill-signing" / "jiaotang-skill-release-ed25519"
DEFAULT_PUBLIC_KEY = DEFAULT_SIGNING_KEY.with_suffix(".pub")
IGNORED_PARTS = {"__pycache__", ".git"}
IGNORED_NAMES = {".DS_Store"}


def _skill_files(skill_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(skill_dir)
        if (
            any(part in IGNORED_PARTS or part.startswith("._") for part in rel.parts)
            or rel.name in IGNORED_NAMES
            or rel.suffix in {".pyc", ".pyo"}
            or rel.as_posix() in SIGNATURE_FILES
        ):
            continue
        if path.is_symlink():
            raise RuntimeError(f"签名范围内禁止符号链接：{path}")
        files[rel.as_posix()] = sha256_file(path)
    return files


def sign_v3_suite(
    *,
    skills_root: Path,
    signing_key: Path,
    public_key: Path,
) -> dict[str, object]:
    suite = json.loads((skills_root / "suite-manifest.json").read_text(encoding="utf-8"))
    release_tag = str(suite["release"]["tag"])
    skills = [str(s) for s in suite["skills"]]
    fingerprint = public_key_fingerprint(public_key)
    results: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="v3-sign-verify-") as evidence:
        evidence_dir = Path(evidence)
        for skill_name in skills:
            skill_dir = skills_root / skill_name
            if not (skill_dir / "SKILL.md").is_file():
                raise RuntimeError(f"缺少 V3 技能 SKILL.md：{skill_dir}")
            file_hashes = _skill_files(skill_dir)
            manifest = {
                "schema_version": 2,
                "skill_name": skill_name,
                "release_tag": release_tag,
                "required_paths": ["SKILL.md"],
                "mutable_paths": ["local-overrides"],
                "files": file_hashes,
                "integrity_excludes": sorted(SIGNATURE_FILES),
            }
            manifest_path = skill_dir / "release-manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            sig_path = skill_dir / "release-manifest.json.sig"
            if sig_path.exists():
                sig_path.unlink()
            proc = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "sign",
                    "-f",
                    str(signing_key),
                    "-n",
                    "codex-skill-manifest",
                    str(manifest_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"签发 {skill_name} 失败：{proc.stderr or proc.stdout}")
            shutil.copy2(public_key, skill_dir / "publisher-ed25519.pub")
            (skill_dir / "release-signature.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "algorithm": "OpenSSH-Ed25519",
                        "signature_namespace": "codex-skill-manifest",
                        "signed_file": "release-manifest.json",
                        "signature": "release-manifest.json.sig",
                        "public_key": "publisher-ed25519.pub",
                        "public_key_fingerprint": fingerprint,
                        "trust_model": "pinned-official-publisher",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            verified = verify_skill_directory(
                skill_dir,
                evidence_dir=evidence_dir,
                label=f"v3-{skill_name}",
                require_signature=True,
                expected_public_fingerprint=fingerprint,
            )
            results.append({"skill": skill_name, "checked_files": verified["checked_files"], "status": verified["status"]})

        anchor = trusted_publisher_fingerprint(skills_root)
    return {
        "status": "pass",
        "release_tag": release_tag,
        "publisher_fingerprint": anchor,
        "skill_count": len(results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="为 V3 10 大核心技能生成并验证 Ed25519 签名清单")
    parser.add_argument("--skills-root", type=Path, default=ROOT / "skills")
    parser.add_argument("--signing-key", type=Path, default=DEFAULT_SIGNING_KEY)
    parser.add_argument("--public-key", type=Path, default=DEFAULT_PUBLIC_KEY)
    args = parser.parse_args()
    summary = sign_v3_suite(
        skills_root=args.skills_root.resolve(),
        signing_key=args.signing_key.expanduser().resolve(),
        public_key=args.public_key.expanduser().resolve(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

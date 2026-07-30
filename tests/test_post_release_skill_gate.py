from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "post_release_skill_gate.py"
)
SPEC = importlib.util.spec_from_file_location("post_release_skill_gate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore_write_permissions(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts)):
        if path.exists() and not path.is_symlink():
            os.chmod(path, path.stat().st_mode | 0o700)
    os.chmod(root, root.stat().st_mode | 0o700)


@pytest.mark.skipif(
    shutil.which("ssh-keygen") is None,
    reason="需要ssh-keygen",
)
def test_post_release_gate_installs_and_audits_three_layers(tmp_path) -> None:
    skill_name = "sample-signed-skill"
    development_root = tmp_path / "development-skills"
    development_root.mkdir()
    signing_key = tmp_path / "suite-signing-key"
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(signing_key),
        ],
        check=True,
    )
    fingerprint = subprocess.run(
        [
            "ssh-keygen",
            "-lf",
            str(signing_key.with_suffix(".pub")),
            "-E",
            "sha256",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[1]
    development_skill = development_root / skill_name
    development_skill.mkdir()
    (development_skill / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_name}\n"
        "description: signed test skill\n"
        "---\n",
        encoding="utf-8",
    )
    skill_manifest_path = development_skill / "release-manifest.json"
    skill_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "skill_name": skill_name,
                "release_tag": "V9.9.9",
                "required_paths": ["SKILL.md"],
                "mutable_paths": ["local-overrides"],
                "files": {
                    "SKILL.md": sha256(development_skill / "SKILL.md")
                },
                "integrity_excludes": [
                    "publisher-ed25519.pub",
                    "release-manifest.json",
                    "release-manifest.json.sig",
                    "release-signature.json",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(signing_key),
            "-n",
            "codex-skill-manifest",
            str(skill_manifest_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    shutil.copy2(
        signing_key.with_suffix(".pub"),
        development_skill / "publisher-ed25519.pub",
    )
    (development_skill / "release-signature.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "algorithm": "OpenSSH-Ed25519",
                "signature_namespace": "codex-skill-manifest",
                "signed_file": "release-manifest.json",
                "signature": "release-manifest.json.sig",
                "public_key": "publisher-ed25519.pub",
                "public_key_fingerprint": fingerprint,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    suite_manifest = {
        "schema_version": 1,
        "product_name": "Test Suite",
        "product_slug": "test-suite",
        "install_mode": "bundle-only",
        "release": {"tag": "V9.9.9", "version": "9.9.9"},
        "skills": [skill_name],
        "shared_paths": [],
    }
    (development_root / "suite-manifest.json").write_text(
        json.dumps(suite_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    bundle_root = tmp_path / "bundle" / "test-suite"
    release_root = bundle_root / "skills"
    shutil.copytree(development_root, release_root)
    files = {
        path.relative_to(bundle_root).as_posix(): sha256(path)
        for path in sorted(bundle_root.rglob("*"))
        if path.is_file()
    }
    embedded_manifest = {
        "schema_version": 1,
        "artifact_type": "skill-suite",
        "product_name": "Test Suite",
        "product_slug": "test-suite",
        "release_tag": "V9.9.9",
        "release_version": "9.9.9",
        "install_mode": "bundle-only",
        "skill_count": 1,
        "skills": [skill_name],
        "files": files,
    }
    embedded_manifest_path = bundle_root / "suite-release-manifest.json"
    embedded_manifest_path.write_text(
        json.dumps(embedded_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(signing_key),
            "-n",
            "codex-skill-suite-manifest",
            str(embedded_manifest_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    embedded_manifest_path.with_suffix(".json.sig").replace(
        bundle_root / "suite-release-manifest.sig"
    )
    shutil.copy2(signing_key.with_suffix(".pub"), bundle_root / "publisher-ed25519.pub")
    (bundle_root / "publisher-key.json").write_text(
        json.dumps(
            {"algorithm": "Ed25519", "fingerprint_sha256": fingerprint},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    archive = tmp_path / "test-suite.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(bundle_root.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(bundle_root.parent).as_posix())

    install_root = tmp_path / "installed-skills"
    config_dir = tmp_path / "config"
    audit_dir = tmp_path / "audits"
    report_path = audit_dir / "single-audit.json"
    try:
        result = MODULE.run_gate(
            development_root=development_root,
            release_archive=archive,
            install_root=install_root,
            config_dir=config_dir,
            audit_dir=audit_dir,
            report_path=report_path,
            command=["test-post-release-gate"],
        )
        assert result["status"] == "pass"
        assert result["summary"]["suite_signature"] == "verified"
        assert result["summary"]["release_skill_signatures_verified"] == 1
        assert result["summary"]["installed_skill_signatures_verified"] == 1
        assert result["summary"]["development_release_install_match"] is True
        assert report_path.is_file()
        assert (
            install_root / skill_name / "SKILL.md"
        ).read_bytes() == (release_root / skill_name / "SKILL.md").read_bytes()
        assert (install_root / skill_name).stat().st_mode & 0o222 == 0
        assert (install_root / "suite-manifest.json").stat().st_mode & 0o222 == 0
        execution_lines = (
            config_dir / "install-executions.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        assert json.loads(execution_lines[-1])["command"] == [
            "test-post-release-gate"
        ]

        (development_skill / "SKILL.md").write_text(
            "tampered-development-source",
            encoding="utf-8",
        )
        blocked_install = tmp_path / "blocked-install"
        blocked_report = audit_dir / "blocked-audit.json"
        with pytest.raises(RuntimeError, match="开发源与正式包不一致"):
            MODULE.run_gate(
                development_root=development_root,
                release_archive=archive,
                install_root=blocked_install,
                config_dir=tmp_path / "blocked-config",
                audit_dir=audit_dir,
                report_path=blocked_report,
                command=["test-blocked-gate"],
            )
        assert not blocked_install.exists()
        assert json.loads(
            blocked_report.read_text(encoding="utf-8")
        )["status"] == "fail"
    finally:
        restore_write_permissions(install_root)

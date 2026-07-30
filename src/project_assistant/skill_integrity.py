from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any


IGNORED_NAMES = {".DS_Store"}
SIGNATURE_FILES = {
    "publisher-ed25519.pub",
    "release-manifest.json",
    "release-manifest.json.sig",
    "release-signature.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON根节点必须是对象：{path}")
    return payload


def public_key_fingerprint(public_key: Path) -> str:
    executable = shutil.which("ssh-keygen")
    if executable is None:
        raise RuntimeError("宿主环境缺少ssh-keygen，无法执行Ed25519验签")
    process = subprocess.run(
        [executable, "-lf", str(public_key), "-E", "sha256"],
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).strip()
        raise RuntimeError(f"无法读取发布公钥指纹：{detail}")
    fields = process.stdout.split()
    if len(fields) < 2:
        raise RuntimeError("ssh-keygen未返回可识别的公钥指纹")
    return fields[1]


def verify_detached_signature(
    *,
    payload: Path,
    signature: Path,
    public_key: Path,
    namespace: str,
    evidence_dir: Path,
    label: str,
    expected_fingerprint: str | None = None,
) -> dict[str, str]:
    missing = [
        path.name
        for path in (payload, signature, public_key)
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError(f"{label}缺少验签文件：" + "、".join(missing))
    fingerprint = public_key_fingerprint(public_key)
    if expected_fingerprint and fingerprint != expected_fingerprint:
        raise RuntimeError(
            f"{label}公钥指纹与签名元数据不一致："
            f"{fingerprint} / {expected_fingerprint}"
        )
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "release"
    signer_dir = evidence_dir / "allowed-signers"
    signer_dir.mkdir(parents=True, exist_ok=True)
    allowed_signers = signer_dir / f"{safe_label}.txt"
    allowed_signers.write_text(
        "publisher " + public_key.read_text(encoding="utf-8").strip() + "\n",
        encoding="utf-8",
    )
    executable = shutil.which("ssh-keygen")
    if executable is None:
        raise RuntimeError("宿主环境缺少ssh-keygen，无法执行Ed25519验签")
    process = subprocess.run(
        [
            executable,
            "-Y",
            "verify",
            "-f",
            str(allowed_signers),
            "-I",
            "publisher",
            "-n",
            namespace,
            "-s",
            str(signature),
        ],
        input=payload.read_bytes(),
        check=False,
        capture_output=True,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).decode(
            "utf-8", errors="replace"
        ).strip()
        raise RuntimeError(f"{label}Ed25519签名验证失败：{detail}")
    return {
        "status": "verified",
        "namespace": namespace,
        "public_key_fingerprint": fingerprint,
    }


def _is_ignored(path: Path) -> bool:
    return (
        path.name in IGNORED_NAMES
        or "__pycache__" in path.parts
        or path.suffix in {".pyc", ".pyo"}
        or path.name.startswith("._")
    )


def _is_mutable(relative: str, mutable_paths: list[str]) -> bool:
    return any(
        relative == prefix or relative.startswith(prefix.rstrip("/") + "/")
        for prefix in mutable_paths
    )


def tree_hashes(
    root: Path,
    *,
    mutable_paths: list[str] | None = None,
) -> dict[str, str]:
    mutable_paths = mutable_paths or []
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if _is_ignored(path):
            continue
        relative = path.relative_to(root).as_posix()
        if _is_mutable(relative, mutable_paths):
            continue
        if path.is_symlink():
            raise RuntimeError(f"签名安装范围内禁止符号链接：{path}")
        if path.is_file():
            hashes[relative] = sha256_file(path)
    return hashes


def verify_skill_directory(
    skill_dir: Path,
    *,
    evidence_dir: Path,
    label: str,
    require_signature: bool = True,
    expected_public_fingerprint: str | None = None,
) -> dict[str, Any]:
    manifest_path = skill_dir / "release-manifest.json"
    if not manifest_path.is_file():
        if require_signature:
            raise RuntimeError(f"{label}缺少release-manifest.json")
        return {
            "status": "unsigned",
            "skill": skill_dir.name,
            "checked_files": 0,
        }
    manifest = load_json(manifest_path)
    skill_name = str(manifest.get("skill_name") or "")
    if skill_name != skill_dir.name:
        raise RuntimeError(
            f"{label}技能目录名与发布清单不一致：{skill_dir.name} / {skill_name}"
        )
    declared = manifest.get("files")
    if not isinstance(declared, dict) or not declared:
        raise RuntimeError(f"{label}发布清单没有文件哈希")
    errors: list[str] = []
    for relative, expected in declared.items():
        path = skill_dir / str(relative)
        if not path.is_file():
            errors.append(f"缺少文件：{relative}")
        elif sha256_file(path) != expected:
            errors.append(f"文件哈希不一致：{relative}")
    for relative in manifest.get("required_paths", []):
        if not (skill_dir / str(relative)).exists():
            errors.append(f"缺少必需路径：{relative}")
    if errors:
        raise RuntimeError(f"{label}完整性校验失败：" + "；".join(errors))

    signature_result: dict[str, str] | None = None
    signature_paths = {
        name: skill_dir / name for name in SIGNATURE_FILES
    }
    present = {name for name, path in signature_paths.items() if path.is_file()}
    if present and present != SIGNATURE_FILES:
        missing = sorted(SIGNATURE_FILES - present)
        raise RuntimeError(f"{label}签名材料不完整：" + "、".join(missing))
    if require_signature or present:
        metadata = load_json(signature_paths["release-signature.json"])
        signature_result = verify_detached_signature(
            payload=manifest_path,
            signature=signature_paths["release-manifest.json.sig"],
            public_key=signature_paths["publisher-ed25519.pub"],
            namespace=str(
                metadata.get("signature_namespace")
                or "codex-skill-manifest"
            ),
            evidence_dir=evidence_dir,
            label=label,
            expected_fingerprint=(
                expected_public_fingerprint
                or str(metadata.get("public_key_fingerprint") or "")
                or None
            ),
        )
        metadata_fingerprint = str(
            metadata.get("public_key_fingerprint") or ""
        )
        if (
            metadata_fingerprint
            and signature_result["public_key_fingerprint"]
            != metadata_fingerprint
        ):
            raise RuntimeError(f"{label}签名元数据的公钥指纹不一致")
    mutable_paths = [
        str(value) for value in manifest.get("mutable_paths", [])
    ]
    return {
        "status": "pass",
        "skill": skill_name,
        "release_tag": manifest.get("release_tag"),
        "checked_files": len(declared),
        "mutable_paths": mutable_paths,
        "signature": signature_result,
        "tree_hashes": tree_hashes(skill_dir, mutable_paths=mutable_paths),
        "declared_hashes": {
            str(relative): str(expected)
            for relative, expected in declared.items()
        },
    }


def freeze_signed_skill(skill_dir: Path) -> dict[str, int]:
    manifest_path = skill_dir / "release-manifest.json"
    if not manifest_path.is_file():
        return {"files": 0, "directories": 0, "mutable_directories": 0}
    manifest = load_json(manifest_path)
    mutable_paths = [
        str(value) for value in manifest.get("mutable_paths", [])
    ]
    for relative in mutable_paths:
        mutable = skill_dir / relative
        mutable.mkdir(parents=True, exist_ok=True)
    file_count = 0
    directory_count = 0
    mutable_count = 0
    paths = sorted(
        skill_dir.rglob("*"),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in paths:
        relative = path.relative_to(skill_dir).as_posix()
        is_mutable = _is_mutable(relative, mutable_paths)
        if path.is_symlink():
            raise RuntimeError(f"签名安装范围内禁止符号链接：{path}")
        current_mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            if is_mutable:
                mutable_count += 1
                continue
            path.chmod(current_mode & ~(
                stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
            ))
            directory_count += 1
        elif path.is_file() and not is_mutable:
            path.chmod(current_mode & ~(
                stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
            ))
            file_count += 1
    root_mode = stat.S_IMODE(skill_dir.stat().st_mode)
    skill_dir.chmod(
        root_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    )
    directory_count += 1
    return {
        "files": file_count,
        "directories": directory_count,
        "mutable_directories": mutable_count,
    }


def freeze_managed_path(path: Path) -> dict[str, int]:
    targets = (
        sorted(
            path.rglob("*"),
            key=lambda item: len(item.parts),
            reverse=True,
        )
        if path.is_dir()
        else []
    )
    targets.append(path)
    file_count = 0
    directory_count = 0
    for target in targets:
        if target.is_symlink():
            raise RuntimeError(f"签名安装范围内禁止符号链接：{target}")
        current_mode = stat.S_IMODE(target.stat().st_mode)
        target.chmod(
            current_mode
            & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        )
        if target.is_dir():
            directory_count += 1
        elif target.is_file():
            file_count += 1
    return {"files": file_count, "directories": directory_count}


def verify_suite_bundle(
    bundle_root: Path,
    *,
    evidence_dir: Path,
    expected_public_fingerprint: str | None = None,
) -> dict[str, Any]:
    manifest_path = bundle_root / "suite-release-manifest.json"
    manifest = load_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("套件发布清单没有文件哈希")
    errors: list[str] = []
    for relative, expected in files.items():
        path = bundle_root / str(relative)
        if not path.is_file():
            errors.append(f"缺少文件：{relative}")
        elif sha256_file(path) != expected:
            errors.append(f"文件哈希不一致：{relative}")
    if errors:
        raise RuntimeError("套件完整性校验失败：" + "；".join(errors[:20]))
    excluded = {
        "suite-release-manifest.json",
        "suite-release-manifest.sig",
        "publisher-ed25519.pub",
        "publisher-key.json",
    }
    actual_files = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
        and path.relative_to(bundle_root).as_posix() not in excluded
        and not _is_ignored(path)
    }
    declared_files = {str(relative) for relative in files}
    if actual_files != declared_files:
        missing = sorted(declared_files - actual_files)
        extra = sorted(actual_files - declared_files)
        raise RuntimeError(
            "套件签名清单与实际文件集合不一致："
            f"缺少{missing[:10]}；多出{extra[:10]}"
        )
    key_metadata = load_json(bundle_root / "publisher-key.json")
    signature = verify_detached_signature(
        payload=manifest_path,
        signature=bundle_root / "suite-release-manifest.sig",
        public_key=bundle_root / "publisher-ed25519.pub",
        namespace="codex-skill-suite-manifest",
        evidence_dir=evidence_dir,
        label="skill-suite",
        expected_fingerprint=(
            expected_public_fingerprint
            or str(key_metadata.get("fingerprint_sha256") or "")
            or None
        ),
    )
    declared_fingerprint = str(
        key_metadata.get("fingerprint_sha256") or ""
    )
    if (
        declared_fingerprint
        and signature["public_key_fingerprint"] != declared_fingerprint
    ):
        raise RuntimeError("套件公钥元数据指纹不一致")
    return {
        "status": "pass",
        "release_tag": manifest.get("release_tag"),
        "release_version": manifest.get("release_version"),
        "skill_count": manifest.get("skill_count"),
        "checked_files": len(files),
        "signature": signature,
        "manifest": manifest,
    }


def trusted_publisher_fingerprint(development_root: Path) -> str:
    manifest = load_json(development_root / "suite-manifest.json")
    fingerprints: set[str] = set()
    for skill_name in manifest.get("skills", []):
        skill_dir = development_root / str(skill_name)
        public_key = skill_dir / "publisher-ed25519.pub"
        signature_metadata = skill_dir / "release-signature.json"
        if not public_key.is_file() or not signature_metadata.is_file():
            raise RuntimeError(
                f"开发源缺少发布信任锚：{skill_name}"
            )
        fingerprint = public_key_fingerprint(public_key)
        declared = str(
            load_json(signature_metadata).get("public_key_fingerprint") or ""
        )
        if not declared or declared != fingerprint:
            raise RuntimeError(
                f"开发源发布公钥指纹不一致：{skill_name}"
            )
        fingerprints.add(fingerprint)
    if len(fingerprints) != 1:
        raise RuntimeError(
            "开发源必须且只能声明一个统一发布公钥指纹"
        )
    return fingerprints.pop()


def audit_skill_layers(
    *,
    development_root: Path,
    release_root: Path,
    install_root: Path | None,
    evidence_dir: Path,
) -> dict[str, Any]:
    suite_manifest = load_json(release_root / "suite-manifest.json")
    expected_skills = [str(value) for value in suite_manifest.get("skills", [])]
    if not expected_skills:
        raise RuntimeError("正式包suite-manifest.json没有声明Skills")
    development_manifest = load_json(
        development_root / "suite-manifest.json"
    )
    if development_manifest.get("skills") != suite_manifest.get("skills"):
        raise RuntimeError("开发源与正式包声明的Skills集合不一致")
    if development_manifest.get("release") != suite_manifest.get("release"):
        raise RuntimeError("开发源与正式包的发布身份不一致")
    trusted_fingerprint = trusted_publisher_fingerprint(development_root)

    skill_results: list[dict[str, Any]] = []
    failures: list[str] = []
    for skill_name in expected_skills:
        development_skill = development_root / skill_name
        release_skill = release_root / skill_name
        installed_skill = install_root / skill_name if install_root else None
        try:
            release_verification = verify_skill_directory(
                release_skill,
                evidence_dir=evidence_dir,
                label=f"release-{skill_name}",
                require_signature=True,
                expected_public_fingerprint=trusted_fingerprint,
            )
            development_mismatches: list[str] = []
            for relative, expected in release_verification[
                "declared_hashes"
            ].items():
                path = development_skill / relative
                if not path.is_file():
                    development_mismatches.append(f"缺少：{relative}")
                elif sha256_file(path) != expected:
                    development_mismatches.append(f"哈希不一致：{relative}")
            installed_verification = None
            install_mismatches: list[str] = []
            if installed_skill is not None:
                installed_verification = verify_skill_directory(
                    installed_skill,
                    evidence_dir=evidence_dir,
                    label=f"installed-{skill_name}",
                    require_signature=True,
                    expected_public_fingerprint=trusted_fingerprint,
                )
                release_tree = release_verification["tree_hashes"]
                install_tree = installed_verification["tree_hashes"]
                install_mismatches = sorted(
                    {
                        *(
                            f"缺少：{relative}"
                            for relative in release_tree.keys() - install_tree.keys()
                        ),
                        *(
                            f"多出：{relative}"
                            for relative in install_tree.keys() - release_tree.keys()
                        ),
                        *(
                            f"哈希不一致：{relative}"
                            for relative in release_tree.keys() & install_tree.keys()
                            if release_tree[relative] != install_tree[relative]
                        ),
                    }
                )
            status = (
                "pass"
                if not development_mismatches and not install_mismatches
                else "fail"
            )
            if status != "pass":
                failures.append(skill_name)
            skill_results.append(
                {
                    "skill": skill_name,
                    "status": status,
                    "development_vs_release": development_mismatches,
                    "release_signature": release_verification["signature"],
                    "installed_vs_release": install_mismatches,
                    "installed_signature": (
                        installed_verification["signature"]
                        if installed_verification
                        else None
                    ),
                    "checked_files": release_verification["checked_files"],
                }
            )
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            failures.append(skill_name)
            skill_results.append(
                {
                    "skill": skill_name,
                    "status": "fail",
                    "error": str(exc),
                }
            )

    shared_results: list[dict[str, Any]] = []
    shared_paths = [
        "suite-manifest.json",
        *[str(value) for value in suite_manifest.get("shared_paths", [])],
    ]
    for relative in shared_paths:
        release_path = release_root / relative
        development_path = development_root / relative
        installed_path = install_root / relative if install_root else None
        try:
            if release_path.is_dir():
                release_hashes = tree_hashes(release_path)
                development_hashes = tree_hashes(development_path)
                installed_hashes = (
                    tree_hashes(installed_path)
                    if installed_path is not None
                    else None
                )
                development_match = development_hashes == release_hashes
                installed_match = (
                    installed_hashes == release_hashes
                    if installed_hashes is not None
                    else None
                )
            else:
                release_digest = sha256_file(release_path)
                development_match = (
                    development_path.is_file()
                    and sha256_file(development_path) == release_digest
                )
                installed_match = (
                    installed_path.is_file()
                    and sha256_file(installed_path) == release_digest
                    if installed_path is not None
                    else None
                )
            status = (
                "pass"
                if development_match and installed_match is not False
                else "fail"
            )
            if status != "pass":
                failures.append(relative)
            shared_results.append(
                {
                    "path": relative,
                    "status": status,
                    "development_matches_release": development_match,
                    "installed_matches_release": installed_match,
                }
            )
        except (OSError, RuntimeError) as exc:
            failures.append(relative)
            shared_results.append(
                {"path": relative, "status": "fail", "error": str(exc)}
            )
    return {
        "status": "pass" if not failures else "fail",
        "skill_count": len(expected_skills),
        "trusted_publisher_fingerprint": trusted_fingerprint,
        "verified_skill_signatures": sum(
            1
            for item in skill_results
            if (item.get("release_signature") or {}).get("status")
            == "verified"
        ),
        "verified_install_signatures": sum(
            1
            for item in skill_results
            if (item.get("installed_signature") or {}).get("status")
            == "verified"
        ),
        "failures": failures,
        "skills": skill_results,
        "shared_paths": shared_results,
    }

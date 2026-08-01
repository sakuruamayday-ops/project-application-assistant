#!/usr/bin/env python3
"""Fail-closed release command without self-hosted Runner dependencies."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_PUBLISHER_FINGERPRINT = (
    "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
)
GATE_SIGNATURE_NAMESPACE = "codex-skill-release-gate"
REMOTE_RELEASE_ROOT = "/opt/jiaotang-kb-runtime/current"


def run(
    arguments: list[str],
    *,
    capture: bool = True,
    input_text: str | None = None,
) -> str:
    completed = subprocess.run(
        arguments,
        check=True,
        capture_output=capture,
        text=True,
        input=input_text,
    )
    return completed.stdout.strip() if capture else ""


def json_command(arguments: list[str]) -> object:
    return json.loads(run(arguments))


def release_json(payload: object) -> str:
    """将发布结果统一输出为可序列化 JSON。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_gate_attestation(gate_report: Path) -> dict[str, Path | str]:
    metadata_path = gate_report.with_name(
        gate_report.name + ".signature.json"
    )
    if not metadata_path.is_file():
        raise RuntimeError("发布门禁报告缺少固定发布者签名元数据")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise RuntimeError("发布门禁签名元数据根节点必须是对象")
    expected = {
        "algorithm": "OpenSSH-Ed25519",
        "signature_namespace": GATE_SIGNATURE_NAMESPACE,
        "signed_file": gate_report.name,
        "signed_file_sha256": sha256(gate_report),
        "public_key_fingerprint": OFFICIAL_PUBLISHER_FINGERPRINT,
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise RuntimeError("发布门禁签名元数据与报告或官方身份不一致")
    signature_name = str(metadata.get("signature") or "")
    public_key_name = str(metadata.get("public_key") or "")
    if (
        Path(signature_name).name != signature_name
        or Path(public_key_name).name != public_key_name
    ):
        raise RuntimeError("发布门禁签名伴随物路径不安全")
    signature = gate_report.parent / signature_name
    public_key = gate_report.parent / public_key_name
    if not signature.is_file() or not public_key.is_file():
        raise RuntimeError("发布门禁报告缺少签名或发布公钥")
    fingerprint = run(
        ["ssh-keygen", "-lf", str(public_key), "-E", "sha256"]
    ).split()[1]
    if fingerprint != OFFICIAL_PUBLISHER_FINGERPRINT:
        raise RuntimeError("发布门禁报告的公钥不是官方固定发布者")
    allowed_fd, allowed_name = tempfile.mkstemp(
        prefix="jiaotang-gate-allowed-signers-"
    )
    os.close(allowed_fd)
    allowed_path = Path(allowed_name)
    allowed_path.write_text(
        "jiaotang " + public_key.read_text(encoding="utf-8").strip() + "\n",
        encoding="utf-8",
    )
    allowed_path.chmod(0o600)
    process = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(allowed_path),
            "-I",
            "jiaotang",
            "-n",
            GATE_SIGNATURE_NAMESPACE,
            "-s",
            str(signature),
        ],
        input=gate_report.read_bytes(),
        check=False,
        capture_output=True,
    )
    if process.returncode:
        raise RuntimeError("发布门禁报告的 Ed25519 签名无效")
    return {
        "status": "verified",
        "signature": signature,
        "metadata": metadata_path,
        "public_key": public_key,
        "publisher_fingerprint": fingerprint,
    }


def validate_release_provenance_environment(
    provenance: dict[str, object],
) -> None:
    manager_root = Path(
        os.environ.get(
            "JIAOTANG_RELEASE_MANAGER_ROOT",
            str(Path.home() / ".codex" / "skills" / "skill-release-manager"),
        )
    ).expanduser().resolve()
    manager_scripts = manager_root / "scripts"
    declared_manager = provenance.get("release_manager_sha256")
    if not isinstance(declared_manager, dict) or not declared_manager:
        raise RuntimeError("发布门禁报告缺少发布管理器哈希")
    actual_manager = {
        path.name: sha256(path)
        for path in sorted(manager_scripts.glob("*.py"))
        if path.is_file()
    }
    if declared_manager != actual_manager:
        raise RuntimeError("发布门禁报告使用的发布管理器与当前固定版本不一致")
    declared_tools = provenance.get("toolchain")
    if not isinstance(declared_tools, dict):
        raise RuntimeError("发布门禁报告缺少工具链锁定信息")
    for name in ("python", "git", "ssh-keygen"):
        item = declared_tools.get(name)
        if not isinstance(item, dict):
            raise RuntimeError(f"发布门禁报告缺少工具链：{name}")
        executable = Path(str(item.get("executable") or "")).resolve()
        if (
            not executable.is_file()
            or item.get("executable_sha256") != sha256(executable)
        ):
            raise RuntimeError(f"发布门禁工具链身份不一致：{name}")


def tracked_source_digest(root: Path) -> tuple[str, int]:
    tracked = [
        item
        for item in run(
            ["git", "-C", str(root), "ls-files", "-z"]
        ).split("\0")
        if item
    ]
    digest = hashlib.sha256()
    for relative in sorted(tracked):
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"Git跟踪文件在工作树缺失：{relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), len(tracked)


def normalize_version(value: str) -> tuple[str, str, str]:
    match = re.fullmatch(
        r"V?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?",
        value.strip(),
    )
    if not match:
        raise ValueError(
            "版本必须形如 1.3、1.3.1、1.3.1.1，或带V前缀"
        )
    major, minor = match.group(1), match.group(2)
    explicit_patch = match.group(3)
    patch = explicit_patch or "0"
    hotfix = match.group(4)
    if hotfix is not None:
        public = f"{major}.{minor}.{patch}.{hotfix}"
        semantic = public
    else:
        public = (
            f"{major}.{minor}.{patch}"
            if explicit_patch is not None
            else f"{major}.{minor}"
        )
        semantic = f"{major}.{minor}.{patch}"
    return public, semantic, f"V{public}"


def release_action(
    *,
    stage: bool,
    promote: bool,
    monitor: bool,
    execute: bool,
    confirm_text: str,
) -> str:
    if execute:
        raise RuntimeError(
            "--execute一步直发已停用；请先使用--stage，收到独立确认后再使用--promote"
        )
    if promote:
        if confirm_text != "确认正式发布":
            raise RuntimeError(
                "缺少独立确认；--confirm-text必须逐字为“确认正式发布”"
            )
        return "promote"
    if monitor:
        return "monitor"
    return "stage" if stage else "preflight"


def load_portal_publisher(root: Path):
    path = root / "services/knowledge-portal/scripts/publish_skill_release.py"
    specification = importlib.util.spec_from_file_location(
        "portal_release_publisher", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载网站发布校验器")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def load_release_companion_builder(root: Path):
    path = root / "scripts/release_companions.py"
    specification = importlib.util.spec_from_file_location(
        "release_companion_builder", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载发布伴随物生成器")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def load_release_transaction_module(root: Path):
    path = (
        root
        / "services"
        / "knowledge-portal"
        / "scripts"
        / "release_transaction.py"
    )
    specification = importlib.util.spec_from_file_location(
        "release_transaction", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载签名发布事务模块")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def generic_publisher_fingerprint(archive: Path) -> str:
    with zipfile.ZipFile(archive, "r") as bundle:
        matches = [
            name
            for name in bundle.namelist()
            if name.endswith("/publisher-key.json")
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "通用正式包必须且只能包含一个publisher-key.json"
            )
        payload = json.loads(bundle.read(matches[0]).decode("utf-8"))
    fingerprint = str(payload.get("fingerprint_sha256") or "")
    if not fingerprint.startswith("SHA256:"):
        raise RuntimeError("通用正式包缺少发布者公钥指纹")
    return fingerprint


def build_release_transaction_manifest(
    *,
    repository: str,
    commit: str,
    validation: dict[str, object],
    release_assets: list[Path],
    publisher_fingerprint: str,
) -> dict[str, object]:
    asset_hashes = {
        path.name: sha256(path) for path in sorted(release_assets)
    }
    package_hashes = {
        target: str(data["sha256"])
        for target, data in validation["artifacts"].items()
    }
    return {
        "schema": "jiaotang-release-transaction/v1",
        "version": validation["short_version"],
        "semantic_version": validation["semantic_version"],
        "tag": validation["tag"],
        "repository": repository,
        "git_commit": commit,
        "publisher_fingerprint": publisher_fingerprint,
        "participants": {
            "github": {
                "release_tag": validation["tag"],
                "target_commit": commit,
                "required_asset_sha256": asset_hashes,
            },
            "portal": {
                "release_version": validation["short_version"],
                "package_sha256": package_hashes,
            },
            "installation": {
                "release_tag": validation["tag"],
                "generic_package_sha256": package_hashes["generic"],
                "skill_count": validation["skill_total"],
                "publisher_fingerprint": publisher_fingerprint,
                "required_result": (
                    "atomic-install-and-three-way-signature-audit-pass"
                ),
            },
        },
        "lease_policy": {
            "scope": "release-version",
            "single_writer": True,
            "non_holder_mode": "read-only-monitor",
            "takeover": "same-signed-transaction-after-expiry-only",
        },
    }


def prepare_release_transaction_assets(
    *,
    directory: Path,
    manifest: dict[str, object],
    tag: str,
    signing_key: Path,
    publisher_public_key: Path,
    expected_fingerprint: str,
) -> tuple[list[Path], dict[str, object]]:
    transaction = load_release_transaction_module(ROOT)
    manifest_bytes, signature_payload, fingerprint = (
        transaction.sign_transaction_manifest(
            manifest,
            private_key_path=signing_key,
            public_key_path=publisher_public_key,
        )
    )
    if fingerprint != expected_fingerprint:
        raise RuntimeError("发布事务签名公钥与正式包发布者不一致")
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / f"jiaotang-release-transaction-{tag}.json"
    signature_path = (
        directory / f"jiaotang-release-transaction-{tag}.sig.json"
    )
    public_key_path = (
        directory / f"jiaotang-release-transaction-{tag}.pub"
    )
    manifest_path.write_bytes(manifest_bytes)
    signature_path.write_text(
        json.dumps(
            signature_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    shutil.copy2(publisher_public_key, public_key_path)
    verification = transaction.verify_transaction_files(
        manifest_path=manifest_path,
        signature_path=signature_path,
        public_key_path=public_key_path,
        expected_fingerprint=expected_fingerprint,
    )
    return [manifest_path, signature_path, public_key_path], verification


def lease_holder_id(explicit: str = "") -> str:
    holder = explicit.strip() or os.environ.get("CODEX_THREAD_ID", "").strip()
    if not holder:
        raise RuntimeError(
            "发布写操作缺少任务身份；请设置CODEX_THREAD_ID或--lease-owner"
        )
    return holder


def lease_checkpoint_path(
    *,
    config_dir: Path,
    tag: str,
    holder_id: str,
) -> Path:
    owner_digest = hashlib.sha256(
        holder_id.encode("utf-8")
    ).hexdigest()[:16]
    return (
        config_dir
        / "release-transactions"
        / f"{tag}-{owner_digest}.credential.json"
    )


def load_or_create_lease_credential(
    *,
    path: Path,
    holder_id: str,
    transaction_sha256: str,
    create: bool,
) -> dict[str, str]:
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("holder_id") != holder_id
            or payload.get("transaction_sha256") != transaction_sha256
            or not payload.get("lease_token")
        ):
            raise RuntimeError("本地发布租约凭证与当前签名事务不一致")
        return {
            "holder_id": str(payload["holder_id"]),
            "lease_token": str(payload["lease_token"]),
            "transaction_sha256": str(payload["transaction_sha256"]),
        }
    if not create:
        raise RuntimeError(
            "当前任务没有该版本的发布租约凭证，已降级为只读监控"
        )
    payload = {
        "holder_id": holder_id,
        "lease_token": secrets.token_urlsafe(32),
        "transaction_sha256": transaction_sha256,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)
    return payload


def validate_inputs(
    root: Path,
    version: str,
    packages: dict[str, Path],
    gate_report: Path,
    notes: Path,
    companions: dict[str, object],
    expected_commit: str,
) -> dict[str, object]:
    short, semantic, tag = normalize_version(version)
    manifest = json.loads(
        (root / "skills/suite-manifest.json").read_text(encoding="utf-8")
    )
    release = manifest.get("release", {})
    if release.get("tag") != tag or release.get("version") != semantic:
        raise RuntimeError("suite-manifest、发布标签和语义版本不一致")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    if f'version = "{semantic}"' not in pyproject:
        raise RuntimeError("pyproject.toml 组件版本未与产品语义版本对齐")
    readme = (root / "README.md").read_text(encoding="utf-8")
    if tag not in readme:
        raise RuntimeError("README 未声明当前发布版本")
    if not notes.is_file() or tag not in notes.read_text(encoding="utf-8"):
        raise RuntimeError("发布说明不存在或版本不一致")
    release_notes = notes.read_text(encoding="utf-8")
    for fact in [str(release.get("summary") or ""), *release.get("changes", [])]:
        if fact and fact not in release_notes:
            raise RuntimeError("发布说明未覆盖 suite-manifest 中的版本事实")
    gate = json.loads(gate_report.read_text(encoding="utf-8"))
    gate_attestation = verify_gate_attestation(gate_report)
    if (
        gate.get("status") != "pass"
        or gate.get("failed")
        or gate.get("passed") != gate.get("gate_count")
    ):
        raise RuntimeError("本地发布门禁报告未全部通过")
    provenance = gate.get("source_provenance")
    if not isinstance(provenance, dict):
        raise RuntimeError("发布门禁报告缺少源码与工具链溯源")
    current_tree = run(
        ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"]
    )
    source_digest, tracked_files = tracked_source_digest(root)
    expected_provenance = {
        "git_commit": expected_commit,
        "git_tree": current_tree,
        "dirty": False,
        "tracked_source_sha256": source_digest,
        "tracked_files": tracked_files,
        "suite_manifest_sha256": sha256(
            root / "skills" / "suite-manifest.json"
        ),
    }
    if any(
        provenance.get(key) != value
        for key, value in expected_provenance.items()
    ):
        raise RuntimeError("发布门禁报告与当前提交、源码或套件清单不一致")
    validate_release_provenance_environment(provenance)
    publisher = load_portal_publisher(root)
    package_validation = publisher.validate_release_packages(packages, short)
    final_artifacts = gate.get("final_artifacts")
    if (
        gate.get("final_artifacts_complete") is not True
        or not isinstance(final_artifacts, dict)
    ):
        raise RuntimeError("发布门禁报告尚未绑定最终候选包")
    for target, artifact in package_validation["artifacts"].items():
        declared = final_artifacts.get(target)
        if (
            not isinstance(declared, dict)
            or declared.get("sha256") != artifact.get("sha256")
        ):
            raise RuntimeError(
                f"发布门禁报告绑定的{target}包与当前候选包不一致"
            )
    payload = companions.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("发布伴随物没有返回机器可读清单")
    if (
        payload.get("release_tag") != tag
        or payload.get("release_version") != semantic
        or payload.get("skill_count") != len(manifest.get("skills", []))
    ):
        raise RuntimeError("发布伴随物与 suite-manifest 不一致")
    return {
        "short_version": short,
        "semantic_version": semantic,
        "tag": tag,
        "skill_total": len(manifest.get("skills", [])),
        "targets": package_validation["targets"],
        "artifacts": package_validation["artifacts"],
        "gate_sha256": sha256(gate_report),
        "gate_attestation": gate_attestation,
        "source_provenance": provenance,
        "manual_sha256": payload["manual"]["sha256"],
        "companion_sha256": sha256(Path(str(companions["companion"]))),
    }


def validate_clean_default_branch(repository: str) -> str:
    git_root = ["git", "-C", str(ROOT)]
    if run([*git_root, "status", "--porcelain"]):
        raise RuntimeError("受控发布必须从无未提交改动的工作树执行")
    branch = run([*git_root, "branch", "--show-current"])
    repository_data = json_command(
        ["gh", "repo", "view", repository, "--json", "defaultBranchRef"]
    )
    default_branch = repository_data["defaultBranchRef"]["name"]
    if branch != default_branch:
        raise RuntimeError(
            f"受控发布必须从默认分支 {default_branch} 执行，当前为 {branch}"
        )
    run([*git_root, "fetch", "origin", default_branch])
    local = run([*git_root, "rev-parse", "HEAD"])
    remote = run([*git_root, "rev-parse", f"origin/{default_branch}"])
    if local != remote:
        raise RuntimeError("本地默认分支与 GitHub 默认分支不一致")
    return local


def prepare_ascii_assets(
    directory: Path,
    tag: str,
    packages: dict[str, Path],
    gate_report: Path,
    companions: dict[str, Path] | None = None,
) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    names = {
        "generic": f"jiaotang-skills-{tag}.zip",
        "workbuddy": f"jiaotang-skills-{tag}-WorkBuddy.zip",
    }
    targets: list[Path] = []
    for target_name, source in packages.items():
        target = directory / names[target_name]
        shutil.copy2(source, target)
        targets.append(target)
    gate_target = directory / gate_report.name
    shutil.copy2(gate_report, gate_target)
    targets.append(gate_target)
    gate_attestation = verify_gate_attestation(gate_report)
    for key in ("signature", "metadata", "public_key"):
        source = Path(str(gate_attestation[key]))
        target = directory / source.name
        shutil.copy2(source, target)
        targets.append(target)
    companion_names = {
        "manual": f"jiaotang-user-manual-{tag}.docx",
        "companion": f"jiaotang-release-companions-{tag}.json",
    }
    for companion_type, source in (companions or {}).items():
        if companion_type not in companion_names:
            raise RuntimeError(f"不支持的发布伴随物：{companion_type}")
        target = directory / companion_names[companion_type]
        shutil.copy2(source, target)
        targets.append(target)
    return targets


def ensure_prerelease(
    repository: str,
    tag: str,
    commit: str,
    notes: Path,
    assets: list[Path],
    *,
    create_if_missing: bool = True,
    allow_published: bool = False,
) -> str:
    existing = subprocess.run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "url,isPrerelease,targetCommitish,assets",
        ],
        capture_output=True,
        text=True,
    )
    if existing.returncode == 0:
        payload = json.loads(existing.stdout)
        if not payload.get("isPrerelease") and not allow_published:
            raise RuntimeError(f"GitHub {tag} 已是正式版，不能重新进入发布中")
        target = str(payload.get("targetCommitish") or "")
        if target != commit:
            raise RuntimeError("GitHub 预发布的目标提交与当前正式提交不一致")
        remote_assets = {
            str(item["name"]): str(item.get("digest") or "")
            for item in payload.get("assets", [])
        }
        expected_assets = {
            path.name: f"sha256:{sha256(path)}" for path in assets
        }
        if remote_assets != expected_assets:
            raise RuntimeError("GitHub 预发布资产与本地候选包不一致")
        return str(payload["url"])
    if not create_if_missing:
        raise RuntimeError(f"GitHub {tag} 尚未进入正式发布中，不能直接提升")
    return run(
        [
            "gh",
            "release",
            "create",
            tag,
            *(str(path) for path in assets),
            "--repo",
            repository,
            "--target",
            commit,
            "--title",
            f"企业全生命周期助手 {tag}",
            "--notes-file",
            str(notes),
            "--prerelease",
        ]
    )


def _remote_release_context() -> tuple[list[str], str, str]:
    deploy_host = os.environ.get("JIAOTANG_DEPLOY_HOST")
    deploy_key = os.environ.get("JIAOTANG_DEPLOY_KEY")
    if not deploy_host or not deploy_key:
        raise RuntimeError("缺少 JIAOTANG_DEPLOY_HOST 或 JIAOTANG_DEPLOY_KEY")
    ssh = ["ssh", "-i", deploy_key, "-o", "IdentitiesOnly=yes", deploy_host]
    return ssh, deploy_host, deploy_key


def remote_release_transaction_call(
    *,
    mode: str,
    version: str,
    transaction_files: list[Path] | None = None,
    credential_file: Path | None = None,
    transaction_sha256: str = "",
    target_state: str = "",
    evidence_file: Path | None = None,
    lease_ttl_seconds: int,
) -> dict[str, object]:
    ssh, deploy_host, deploy_key = _remote_release_context()
    remote_stage = (
        f"/tmp/jiaotang-release-transaction-{version}-"
        f"{int(time.time())}-{secrets.token_hex(4)}"
    )
    uploads = [
        *(transaction_files or []),
        *([evidence_file] if evidence_file else []),
    ]
    if uploads:
        run([*ssh, f"install -d -m 0700 {shlex.quote(remote_stage)}"])
        run(
            [
                "scp",
                "-i",
                deploy_key,
                "-o",
                "IdentitiesOnly=yes",
                *(str(path) for path in uploads),
                f"{deploy_host}:{remote_stage}/",
            ]
        )
    options = [
        f"--mode {shlex.quote(mode)}",
        "--database \"$JIAOTANG_DATA_DIR/knowledge.db\"",
        "--release-dir \"$JIAOTANG_SKILL_RELEASE_DIR\"",
        f"--version {shlex.quote(version)}",
        f"--lease-ttl-seconds {lease_ttl_seconds}",
    ]
    if transaction_files:
        options.extend(
            [
                "--transaction-manifest "
                + shlex.quote(
                    f"{remote_stage}/{transaction_files[0].name}"
                ),
                "--transaction-signature "
                + shlex.quote(
                    f"{remote_stage}/{transaction_files[1].name}"
                ),
                "--publisher-public-key "
                + shlex.quote(
                    f"{remote_stage}/{transaction_files[2].name}"
                ),
            ]
        )
    if credential_file:
        options.append("--lease-credential-stdin")
    if transaction_sha256:
        options.append(
            "--transaction-sha256 " + shlex.quote(transaction_sha256)
        )
    if target_state:
        options.append("--transaction-state " + shlex.quote(target_state))
    if evidence_file:
        options.append(
            "--transaction-evidence-file "
            + shlex.quote(f"{remote_stage}/{evidence_file.name}")
        )
    remote_command = (
        "set -a; source /etc/jiaotang-kb.env; set +a; "
        f"{REMOTE_RELEASE_ROOT}/.venv/bin/python "
        f"{REMOTE_RELEASE_ROOT}/scripts/publish_skill_release.py "
        + " ".join(options)
    )
    return json.loads(
        run(
            [*ssh, remote_command],
            input_text=(
                credential_file.read_text(encoding="utf-8")
                if credential_file
                else None
            ),
        )
    )


def transaction_evidence_file(
    directory: Path,
    state: str,
    payload: dict[str, object],
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{state}-evidence.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def stage_portal(
    version: str,
    packages: dict[str, Path],
    notes: Path,
    commit: str,
    release_url: str,
    *,
    transaction_files: list[Path],
    credential_file: Path,
    lease_ttl_seconds: int,
) -> dict[str, object]:
    ssh, deploy_host, deploy_key = _remote_release_context()
    remote_stage = f"/tmp/jiaotang-release-{version}-{int(time.time())}"
    run([*ssh, f"install -d -m 0700 '{remote_stage}'"])
    run(
        [
            "scp",
            "-i",
            deploy_key,
            "-o",
            "IdentitiesOnly=yes",
            *(str(package) for package in packages.values()),
            str(notes),
            *(str(path) for path in transaction_files),
            f"{deploy_host}:{remote_stage}/",
        ]
    )
    package_flags = " ".join(
        f"--workbuddy-package "
        f"{shlex.quote(f'{remote_stage}/{package.name}')}"
        if target != "generic"
        else f"--generic-package {shlex.quote(f'{remote_stage}/{package.name}')}"
        for target, package in packages.items()
    )
    remote_command = (
        "set -a; source /etc/jiaotang-kb.env; set +a; "
        f"{REMOTE_RELEASE_ROOT}/.venv/bin/python "
        f"{REMOTE_RELEASE_ROOT}/scripts/publish_skill_release.py "
        "--mode stage "
        f"--database \"$JIAOTANG_DATA_DIR/knowledge.db\" "
        f"--release-dir \"$JIAOTANG_SKILL_RELEASE_DIR\" "
        f"{package_flags} "
        f"--version {shlex.quote(version)} "
        f"--release-notes-file {shlex.quote(f'{remote_stage}/{notes.name}')} "
        f"--git-commit {shlex.quote(commit)} "
        f"--github-url {shlex.quote(release_url)} "
        f"--transaction-manifest "
        f"{shlex.quote(f'{remote_stage}/{transaction_files[0].name}')} "
        f"--transaction-signature "
        f"{shlex.quote(f'{remote_stage}/{transaction_files[1].name}')} "
        f"--publisher-public-key "
        f"{shlex.quote(f'{remote_stage}/{transaction_files[2].name}')} "
        "--lease-credential-stdin "
        f"--lease-ttl-seconds {lease_ttl_seconds}"
    )
    return json.loads(
        run(
            [*ssh, remote_command],
            input_text=credential_file.read_text(encoding="utf-8"),
        )
    )


def promote_portal(
    version: str,
    *,
    transaction_files: list[Path],
    credential_file: Path,
    lease_ttl_seconds: int,
) -> dict[str, object]:
    ssh, deploy_host, deploy_key = _remote_release_context()
    remote_stage = (
        f"/tmp/jiaotang-release-promote-{version}-{int(time.time())}"
    )
    run([*ssh, f"install -d -m 0700 {shlex.quote(remote_stage)}"])
    run(
        [
            "scp",
            "-i",
            deploy_key,
            "-o",
            "IdentitiesOnly=yes",
            *(str(path) for path in transaction_files),
            f"{deploy_host}:{remote_stage}/",
        ]
    )
    remote_command = (
        "set -a; source /etc/jiaotang-kb.env; set +a; "
        f"{REMOTE_RELEASE_ROOT}/.venv/bin/python "
        f"{REMOTE_RELEASE_ROOT}/scripts/publish_skill_release.py "
        "--mode promote "
        f"--database \"$JIAOTANG_DATA_DIR/knowledge.db\" "
        f"--release-dir \"$JIAOTANG_SKILL_RELEASE_DIR\" "
        f"--version {shlex.quote(version)} "
        f"--transaction-manifest "
        f"{shlex.quote(f'{remote_stage}/{transaction_files[0].name}')} "
        f"--transaction-signature "
        f"{shlex.quote(f'{remote_stage}/{transaction_files[1].name}')} "
        f"--publisher-public-key "
        f"{shlex.quote(f'{remote_stage}/{transaction_files[2].name}')} "
        "--lease-credential-stdin "
        f"--lease-ttl-seconds {lease_ttl_seconds}"
    )
    return json.loads(
        run(
            [*ssh, remote_command],
            input_text=credential_file.read_text(encoding="utf-8"),
        )
    )


def run_local_skill_deployment_gate(
    *,
    development_root: Path,
    generic_package: Path,
    install_root: Path,
    config_dir: Path,
    audit_dir: Path,
) -> dict[str, object]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "post_release_skill_gate.py"),
        "--development-root",
        str(development_root),
        "--release-archive",
        str(generic_package),
        "--install-root",
        str(install_root),
        "--config-dir",
        str(config_dir),
        "--audit-dir",
        str(audit_dir),
    ]
    process = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(process.stdout or process.stderr)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "本机Skills部署后门禁未返回有效JSON："
            + (process.stdout or process.stderr)[-2000:]
        ) from exc
    if process.returncode or payload.get("status") != "pass":
        raise RuntimeError(
            "本机Skills原子升级或部署后门禁失败："
            + str(payload.get("error") or payload)
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="两阶段受控发布：进入正式发布中 → 独立确认后正式发布"
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--generic-package", type=Path)
    parser.add_argument(
        "--workbuddy-package",
        type=Path,
        help="同时适用于macOS和Windows的WorkBuddy插件市场包",
    )
    parser.add_argument("--gate-report", type=Path)
    parser.add_argument("--release-notes", type=Path)
    parser.add_argument(
        "--repository",
        default="sakuruamayday-ops/project-application-assistant",
    )
    parser.add_argument(
        "--local-skills-target",
        type=Path,
        default=Path.home() / ".codex" / "skills",
        help="正式提升前必须完成原子升级和三方验签的本机Skills目录",
    )
    parser.add_argument(
        "--local-install-config-dir",
        type=Path,
        default=Path.home() / ".config" / "project-assistant",
        help="安装日志、备份和事务证据目录",
    )
    parser.add_argument(
        "--deployment-audit-dir",
        type=Path,
        default=Path.home()
        / ".config"
        / "project-assistant"
        / "deployment-audits",
        help="开发源、正式包、实际安装目录三方审计报告目录",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--stage",
        action="store_true",
        help="创建GitHub预发布并在网站登记为正式发布中，然后暂停",
    )
    action.add_argument(
        "--promote",
        action="store_true",
        help="将已处于正式发布中的版本提升为网站正式版和GitHub Latest",
    )
    action.add_argument(
        "--monitor",
        action="store_true",
        help="只读查看该版本发布事务、租约与GitHub状态",
    )
    action.add_argument(
        "--execute",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--confirm-text",
        default="",
        help="promote时必须逐字提供“确认正式发布”",
    )
    parser.add_argument(
        "--signing-key",
        type=Path,
        default=Path.home()
        / ".codex"
        / "skill-signing"
        / "publisher-ed25519",
    )
    parser.add_argument(
        "--publisher-public-key",
        type=Path,
        default=Path.home()
        / ".codex"
        / "skill-signing"
        / "publisher-ed25519.pub",
    )
    parser.add_argument("--lease-owner", default="")
    parser.add_argument(
        "--lease-ttl-seconds",
        type=int,
        default=4 * 60 * 60,
    )
    arguments = parser.parse_args()
    action_name = release_action(
        stage=arguments.stage,
        promote=arguments.promote,
        monitor=arguments.monitor,
        execute=arguments.execute,
        confirm_text=arguments.confirm_text,
    )
    if action_name == "monitor":
        short_version, _, tag = normalize_version(arguments.version)
        portal = remote_release_transaction_call(
            mode="lease-monitor",
            version=short_version,
            lease_ttl_seconds=arguments.lease_ttl_seconds,
        )
        github_process = subprocess.run(
            [
                "gh",
                "release",
                "view",
                tag,
                "--repo",
                arguments.repository,
                "--json",
                "url,isPrerelease,targetCommitish,assets",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        github = (
            json.loads(github_process.stdout)
            if github_process.returncode == 0
            else {"status": "not-found"}
        )
        print(
            release_json(
                {
                    "status": "read-only-monitor",
                    "version": short_version,
                    "portal_transaction": portal,
                    "github": github,
                }
            )
        )
        return
    packages = {
        target: package.resolve()
        for target, package in (
            ("generic", arguments.generic_package),
            ("workbuddy", arguments.workbuddy_package),
        )
        if package is not None
    }
    if not packages:
        parser.error("至少提供一个发布包")
    if "generic" not in packages:
        parser.error(
            "受控发布必须提供--generic-package，"
            "用于正式提升前的本机原子升级、全量验签和三方哈希门禁"
        )
    if arguments.gate_report is None or arguments.release_notes is None:
        parser.error("发布预检、暂存和提升必须提供门禁报告与发布说明")
    companion_workspace = tempfile.TemporaryDirectory(
        prefix="jiaotang-release-companions-"
    )
    companion_builder = load_release_companion_builder(ROOT)
    companion_result = companion_builder.generate(
        ROOT,
        Path(companion_workspace.name),
        apply_brand=True,
        render=True,
    )
    companion_files = {
        "manual": Path(str(companion_result["manual"])),
        "companion": Path(str(companion_result["companion"])),
    }
    gate_report = arguments.gate_report.resolve()
    release_notes = arguments.release_notes.resolve()
    commit = validate_clean_default_branch(arguments.repository)
    validation = validate_inputs(
        ROOT,
        arguments.version,
        packages,
        gate_report,
        release_notes,
        companion_result,
        commit,
    )
    with tempfile.TemporaryDirectory(
        prefix="jiaotang-controlled-release-transaction-"
    ) as directory:
        workspace = Path(directory)
        assets = prepare_ascii_assets(
            workspace / "assets",
            validation["tag"],
            packages,
            gate_report,
            companion_files,
        )
        package_fingerprint = generic_publisher_fingerprint(
            packages["generic"]
        )
        transaction_manifest = build_release_transaction_manifest(
            repository=arguments.repository,
            commit=commit,
            validation=validation,
            release_assets=assets,
            publisher_fingerprint=package_fingerprint,
        )
        transaction_files, transaction_verification = (
            prepare_release_transaction_assets(
                directory=workspace / "transaction",
                manifest=transaction_manifest,
                tag=str(validation["tag"]),
                signing_key=arguments.signing_key.expanduser().resolve(),
                publisher_public_key=(
                    arguments.publisher_public_key.expanduser().resolve()
                ),
                expected_fingerprint=package_fingerprint,
            )
        )
        all_assets = [*assets, *transaction_files]
        transaction_sha = str(
            transaction_verification["manifest_sha256"]
        )
        preflight = {
            "status": "preflight-pass",
            "release": validation,
            "commit": commit,
            "release_transaction": {
                "manifest_sha256": transaction_sha,
                "signature_status": transaction_verification[
                    "signature_status"
                ],
                "publisher_fingerprint": package_fingerprint,
                "github_asset_count": len(all_assets),
                "participants": [
                    "github",
                    "portal",
                    "installation",
                ],
            },
        }
        if action_name == "preflight":
            print(release_json(preflight))
            return

        holder = lease_holder_id(arguments.lease_owner)
        credential_path = lease_checkpoint_path(
            config_dir=(
                arguments.local_install_config_dir.expanduser().resolve()
            ),
            tag=str(validation["tag"]),
            holder_id=holder,
        )
        portal_result: dict[str, object] | None = None
        github_published = False
        try:
            credential = load_or_create_lease_credential(
                path=credential_path,
                holder_id=holder,
                transaction_sha256=transaction_sha,
                create=action_name == "stage",
            )
        except RuntimeError:
            monitored = remote_release_transaction_call(
                mode="lease-monitor",
                version=str(validation["short_version"]),
                lease_ttl_seconds=arguments.lease_ttl_seconds,
            )
            print(
                release_json(
                    {
                        **preflight,
                        "status": "read-only-monitor",
                        "release_transaction": monitored,
                    }
                )
            )
            return
        if credential["transaction_sha256"] != transaction_sha:
            raise RuntimeError("发布租约凭证事务哈希不一致")
        lease = remote_release_transaction_call(
            mode="lease-acquire",
            version=str(validation["short_version"]),
            transaction_files=transaction_files,
            credential_file=credential_path,
            transaction_sha256=transaction_sha,
            lease_ttl_seconds=arguments.lease_ttl_seconds,
        )
        if lease.get("mode") != "writer":
            print(
                release_json(
                    {
                        **preflight,
                        "status": "read-only-monitor",
                        "release_transaction": lease,
                    }
                )
            )
            return

        def transition(
            state: str,
            evidence: dict[str, object],
        ) -> dict[str, object]:
            evidence_path = transaction_evidence_file(
                workspace / "evidence",
                state,
                evidence,
            )
            return remote_release_transaction_call(
                mode="lease-transition",
                version=str(validation["short_version"]),
                credential_file=credential_path,
                transaction_sha256=transaction_sha,
                target_state=state,
                evidence_file=evidence_path,
                lease_ttl_seconds=arguments.lease_ttl_seconds,
            )

        if action_name == "stage":
            try:
                release_url = ensure_prerelease(
                    arguments.repository,
                    str(validation["tag"]),
                    commit,
                    release_notes,
                    all_assets,
                )
                transition(
                    "github_staged",
                    {
                        "release_url": release_url,
                        "asset_sha256": {
                            path.name: sha256(path)
                            for path in all_assets
                        },
                    },
                )
                portal_result = stage_portal(
                    str(validation["short_version"]),
                    packages,
                    release_notes,
                    commit,
                    release_url,
                    transaction_files=transaction_files,
                    credential_file=credential_path,
                    lease_ttl_seconds=arguments.lease_ttl_seconds,
                )
            except Exception as exc:
                try:
                    transition("failed", {"stage_error": str(exc)})
                except Exception:
                    pass
                raise
            print(
                release_json(
                    {
                        **preflight,
                        "status": "staged-awaiting-acceptance",
                        "release_url": release_url,
                        "portal": portal_result,
                        "lease": lease,
                        "next_action": "等待主人明确说“确认正式发布”",
                    }
                )
            )
            return

        try:
            release_url = ensure_prerelease(
                arguments.repository,
                str(validation["tag"]),
                commit,
                release_notes,
                all_assets,
                create_if_missing=False,
                allow_published=True,
            )
            transition(
                "installing",
                {
                    "generic_package_sha256": validation["artifacts"][
                        "generic"
                    ]["sha256"],
                    "install_root": str(
                        arguments.local_skills_target.expanduser().resolve()
                    ),
                },
            )
            local_deployment = run_local_skill_deployment_gate(
                development_root=ROOT / "skills",
                generic_package=packages["generic"],
                install_root=(
                    arguments.local_skills_target.expanduser().resolve()
                ),
                config_dir=(
                    arguments.local_install_config_dir.expanduser().resolve()
                ),
                audit_dir=(
                    arguments.deployment_audit_dir.expanduser().resolve()
                ),
            )
            audit_path = Path(str(local_deployment.get("report") or ""))
            transition(
                "installed",
                {
                    "status": local_deployment.get("status"),
                    "summary": local_deployment.get("summary"),
                    "audit_report": str(audit_path),
                    "audit_sha256": (
                        sha256(audit_path) if audit_path.is_file() else ""
                    ),
                },
            )
            portal_result = promote_portal(
                str(validation["short_version"]),
                transaction_files=transaction_files,
                credential_file=credential_path,
                lease_ttl_seconds=arguments.lease_ttl_seconds,
            )
            run(
                [
                    "gh",
                    "release",
                    "edit",
                    str(validation["tag"]),
                    "--repo",
                    arguments.repository,
                    "--prerelease=false",
                    "--latest",
                ]
            )
            github_published = True
            transition(
                "github_published",
                {
                    "release_url": release_url,
                    "target_commit": commit,
                },
            )
            delivery = companion_builder.deliver(
                ROOT,
                Path(companion_workspace.name),
            )
            completed = transition(
                "completed",
                {
                    "github": "published",
                    "portal": portal_result.get("release_state"),
                    "installation": local_deployment.get("status"),
                    "delivery": delivery.get("status"),
                },
            )
        except Exception as exc:
            try:
                transition(
                    "failed",
                    {
                        "promote_error": str(exc),
                        "partial_state": (
                            "portal-published-github-pending"
                            if portal_result is not None
                            and not github_published
                            else "pre-publication-failed"
                        ),
                        "portal": (
                            portal_result.get("release_state")
                            if portal_result
                            else None
                        ),
                        "github": (
                            "published" if github_published else "pending"
                        ),
                        "resume": (
                            "使用同一签名事务和租约重新执行 --promote；"
                            "事务从 last_success_state 继续，禁止换包"
                        ),
                    },
                )
            except Exception:
                pass
            raise
        print(
            release_json(
                {
                    **preflight,
                    "status": "published",
                    "release_url": release_url,
                    "local_skill_deployment": local_deployment,
                    "portal": portal_result,
                    "delivery": delivery,
                    "release_transaction": completed,
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(
            release_json({"status": "blocked", "error": str(error)}),
            file=sys.stderr,
        )
        raise SystemExit(1)

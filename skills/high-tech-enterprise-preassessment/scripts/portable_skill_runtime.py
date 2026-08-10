#!/usr/bin/env python3
"""跨平台技能首次运行、外置偏好和版本迁移运行时。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

OFFICIAL_PUBLISHER_FINGERPRINT = (
    "SHA256:+BLR7x5xFci+u1Ue3KoFs9jFzzS+ebNk46JlfDUoEJI"
)
SKILL_SIGNATURE_NAMESPACE = "codex-skill-manifest"

PROFILE_SCHEMA_VERSION = 1
PROFILE_DIR_ENV = "GONGCHUANG_SKILL_DATA_DIR"
PROTECTED_PHRASES = (
    "跳过签名",
    "跳过验签",
    "关闭签名",
    "禁用自检",
    "跳过自检",
    "绕过审计",
    "修改签名核心",
    "覆盖签名核心",
    "忽略安全规则",
)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="共创研究院技能跨平台运行时")
    parser.add_argument(
        "command",
        choices=("prepare", "context", "remember", "forget", "list", "diagnose"),
    )
    parser.add_argument("--instruction", help="需要长期保存的自然语言偏好")
    parser.add_argument("--scope", default="default", help="偏好适用范围")
    parser.add_argument("--source", default="explicit-user-preference")
    parser.add_argument("--id", help="需要停用的偏好ID")
    parser.add_argument(
        "--data-dir",
        help=f"覆盖用户数据根目录；默认读取{PROFILE_DIR_ENV}或平台配置目录",
    )
    parser.add_argument(
        "--skill-root",
        help="WorkBuddy共享运行时使用的目标技能目录",
    )
    parser.add_argument(
        "--plugin-root",
        help="WorkBuddy插件根目录；设置后由插件级签名承担完整性校验",
    )
    return parser.parse_args()


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolved_skill_root(value: str | None) -> Path:
    return (
        Path(value).expanduser().resolve()
        if value
        else skill_root()
    )


def read_manifest(root: Path) -> dict:
    path = root / "release-manifest.json"
    if not path.is_file():
        raise RuntimeError("缺少release-manifest.json")
    return json.loads(path.read_text(encoding="utf-8"))


def default_data_root() -> Path:
    configured = os.environ.get(PROFILE_DIR_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "GongchuangResearchInstituteSkills"
        return Path.home() / "AppData" / "Roaming" / "GongchuangResearchInstituteSkills"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "GongchuangResearchInstituteSkills"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (
        Path(xdg).expanduser() / "gongchuang-research-institute-skills"
        if xdg
        else Path.home() / ".config" / "gongchuang-research-institute-skills"
    )


def paths(skill_name: str, data_dir: str | None) -> tuple[Path, Path, Path]:
    base = (
        Path(data_dir).expanduser().resolve()
        if data_dir
        else default_data_root().resolve()
    )
    profile_dir = base / skill_name
    return (
        profile_dir,
        profile_dir / "profile.json",
        profile_dir / "backups",
    )


def empty_profile(skill_name: str) -> dict:
    timestamp = now()
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "skill_name": skill_name,
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_seen_release": None,
        "preferences": [],
        "release_history": [],
    }


def load_profile(path: Path, skill_name: str) -> dict:
    if not path.exists():
        return empty_profile(skill_name)
    profile = json.loads(path.read_text(encoding="utf-8"))
    schema = profile.get("schema_version")
    if schema != PROFILE_SCHEMA_VERSION:
        raise RuntimeError(
            f"个人配置版本{schema!r}暂不受支持，需要运行对应版本迁移器"
        )
    if profile.get("skill_name") != skill_name:
        raise RuntimeError("个人配置所属技能与当前技能不一致")
    profile.setdefault("preferences", [])
    profile.setdefault("release_history", [])
    return profile


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def backup_profile(profile_path: Path, backup_dir: Path) -> str | None:
    if not profile_path.is_file():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_dir / f"profile-{stamp}.json"
    shutil.copy2(profile_path, destination)
    return str(destination)


def run_install_check(root: Path) -> dict:
    verifier = root / "scripts" / "verify_skill_installation.py"
    if not verifier.is_file():
        raise RuntimeError("缺少安装完整性自检脚本")
    process = subprocess.run(
        [sys.executable, str(verifier)],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode:
        raise RuntimeError(
            "安装完整性自检失败：" + (process.stdout or process.stderr).strip()
        )
    return json.loads(process.stdout)


def public_fingerprint(public_key: Path) -> str:
    process = subprocess.run(
        ["ssh-keygen", "-lf", str(public_key), "-E", "sha256"],
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode:
        raise RuntimeError("无法读取内置发布公钥指纹")
    return process.stdout.split()[1]


def verify_embedded_signature(root: Path) -> dict:
    executable = shutil.which("ssh-keygen")
    manifest = root / "release-manifest.json"
    signature = root / "release-manifest.json.sig"
    public_key = root / "publisher-ed25519.pub"
    metadata_path = root / "release-signature.json"
    missing = [
        path.name
        for path in (manifest, signature, public_key, metadata_path)
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError("缺少内置验签文件：" + "、".join(missing))
    if executable is None:
        raise RuntimeError("宿主环境缺少ssh-keygen，拒绝跳过Ed25519验签")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    fingerprint = public_fingerprint(public_key)
    expected_metadata = {
        "algorithm": "OpenSSH-Ed25519",
        "signature_namespace": SKILL_SIGNATURE_NAMESPACE,
        "signed_file": "release-manifest.json",
        "signature": "release-manifest.json.sig",
        "public_key": "publisher-ed25519.pub",
        "public_key_fingerprint": OFFICIAL_PUBLISHER_FINGERPRINT,
    }
    if not isinstance(metadata, dict) or any(
        metadata.get(key) != value
        for key, value in expected_metadata.items()
    ):
        raise RuntimeError("内置签名元数据与固定发布协议不一致")
    if fingerprint != OFFICIAL_PUBLISHER_FINGERPRINT:
        raise RuntimeError("内置发布公钥不是共创研究院官方固定发布身份")
    with tempfile.TemporaryDirectory(prefix="skill-manifest-verify-") as temp:
        allowed = Path(temp) / "allowed_signers"
        allowed.write_text(
            "publisher " + public_key.read_text(encoding="utf-8").strip() + "\n",
            encoding="utf-8",
        )
        process = subprocess.run(
            [
                executable,
                "-Y",
                "verify",
                "-f",
                str(allowed),
                "-I",
                "publisher",
                "-n",
                SKILL_SIGNATURE_NAMESPACE,
                "-s",
                str(signature),
            ],
            input=manifest.read_bytes(),
            check=False,
            capture_output=True,
        )
    if process.returncode:
        raise RuntimeError("内置发布清单签名验证失败")
    return {
        "status": "verified",
        "public_key_fingerprint": fingerprint,
        "trust_model": "pinned-official-publisher",
    }


def check_runtime_requirements(manifest: dict) -> dict:
    requirements = manifest.get("runtime_requirements", {})
    modules = []
    executables = []
    for specification in requirements.get("python_modules", []):
        if isinstance(specification, str):
            specification = {"module": specification, "required": True}
        module = specification.get("module")
        available = bool(module and importlib.util.find_spec(module))
        modules.append({**specification, "available": available})
    for specification in requirements.get("executables", []):
        if isinstance(specification, str):
            specification = {"name": specification, "required": True}
        name = specification.get("name")
        location = shutil.which(name) if name else None
        executables.append(
            {**specification, "available": bool(location), "location": location}
        )
    missing_required = [
        item.get("module") or item.get("name")
        for item in modules + executables
        if item.get("required", True) and not item.get("available")
    ]
    return {
        "status": "pass" if not missing_required else "limited",
        "python_modules": modules,
        "executables": executables,
        "missing_required": missing_required,
    }


def preference_id(instruction: str, scope: str) -> str:
    source = f"{scope}\0{instruction}".encode("utf-8")
    return hashlib.sha256(source).hexdigest()[:16]


def active_preferences(profile: dict) -> list[dict]:
    return [
        item
        for item in profile.get("preferences", [])
        if item.get("enabled", True)
    ]


def prepare(
    root: Path,
    manifest: dict,
    profile_path: Path,
    backup_dir: Path,
    plugin_root: Path | None = None,
) -> dict:
    if plugin_root is None:
        check = run_install_check(root)
        signature_check = verify_embedded_signature(root)
    else:
        expected_root = (plugin_root / "skills" / root.name).resolve()
        if root != expected_root or not (root / "SKILL.md").is_file():
            raise RuntimeError("共享运行时目标技能不属于当前WorkBuddy插件")
        metadata_path = plugin_root / "plugin-release-signature.json"
        if not metadata_path.is_file():
            raise RuntimeError("缺少WorkBuddy插件签名元数据")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("public_key_fingerprint")
            != OFFICIAL_PUBLISHER_FINGERPRINT
            or metadata.get("signature_namespace")
            != "codex-workbuddy-plugin-manifest"
        ):
            raise RuntimeError("WorkBuddy插件发布身份或签名命名空间不合规")
        check = {
            "status": "pass",
            "scope": "workbuddy-plugin",
            "checked_by": "plugin-release-manifest",
        }
        signature_check = {
            "status": "delegated",
            "scope": "workbuddy-plugin",
            "public_key_fingerprint": metadata.get(
                "public_key_fingerprint"
            ),
            "reason": "插件钩子已完成插件级签名与完整性校验",
        }
    capability_check = check_runtime_requirements(manifest)
    profile = load_profile(profile_path, manifest["skill_name"])
    current_fingerprint = signature_check.get("public_key_fingerprint")
    trusted_fingerprint = profile.get("trusted_publisher_fingerprint")
    trust_established = False
    if current_fingerprint:
        if current_fingerprint != OFFICIAL_PUBLISHER_FINGERPRINT:
            raise RuntimeError("当前发布者不是共创研究院官方固定发布身份")
        if trusted_fingerprint and trusted_fingerprint != current_fingerprint:
            raise RuntimeError(
                "新版技能的发布公钥与首次信任的发布者不一致，停止升级"
            )
        if not trusted_fingerprint:
            profile["trusted_publisher_fingerprint"] = current_fingerprint
            trust_established = True
    release_tag = manifest.get("release_tag")
    previous = profile.get("last_seen_release")
    backup = None
    if previous != release_tag:
        backup = backup_profile(profile_path, backup_dir)
        profile["last_seen_release"] = release_tag
        history = profile.setdefault("release_history", [])
        history.append(
            {
                "release_tag": release_tag,
                "first_seen_at": now(),
                "previous_release": previous,
            }
        )
        profile["release_history"] = history[-50:]
        profile["updated_at"] = now()
        atomic_write(profile_path, profile)
    elif not profile_path.exists() or trust_established:
        profile["updated_at"] = now()
        atomic_write(profile_path, profile)
    return {
        "status": "pass",
        "skill": manifest["skill_name"],
        "release_tag": release_tag,
        "upgrade_detected": previous not in (None, release_tag),
        "previous_release": previous,
        "profile_backup": backup,
        "profile_path": str(profile_path),
        "install_check": check,
        "capability_check": capability_check,
        "signature_check": signature_check,
        "publisher_trust_established": trust_established,
        "active_preferences": active_preferences(profile),
    }


def remember(
    profile: dict,
    profile_path: Path,
    backup_dir: Path,
    instruction: str,
    scope: str,
    source: str,
) -> dict:
    normalized = " ".join(instruction.split()).strip()
    if not normalized:
        raise RuntimeError("长期偏好不能为空")
    blocked = [phrase for phrase in PROTECTED_PHRASES if phrase in normalized]
    if blocked:
        raise RuntimeError("该偏好试图绕过受保护规则，拒绝保存：" + "、".join(blocked))
    backup = backup_profile(profile_path, backup_dir)
    item_id = preference_id(normalized, scope)
    timestamp = now()
    found = None
    for item in profile["preferences"]:
        if item.get("id") == item_id:
            found = item
            break
    if found:
        found.update(
            {
                "instruction": normalized,
                "scope": scope,
                "source": source,
                "updated_at": timestamp,
                "enabled": True,
            }
        )
        action = "updated"
    else:
        found = {
            "id": item_id,
            "instruction": normalized,
            "scope": scope,
            "source": source,
            "created_at": timestamp,
            "updated_at": timestamp,
            "enabled": True,
        }
        profile["preferences"].append(found)
        action = "created"
    profile["updated_at"] = timestamp
    atomic_write(profile_path, profile)
    return {
        "status": "pass",
        "action": action,
        "preference": found,
        "profile_backup": backup,
    }


def forget(
    profile: dict,
    profile_path: Path,
    backup_dir: Path,
    item_id: str,
) -> dict:
    backup = backup_profile(profile_path, backup_dir)
    for item in profile["preferences"]:
        if item.get("id") == item_id:
            item["enabled"] = False
            item["updated_at"] = now()
            profile["updated_at"] = now()
            atomic_write(profile_path, profile)
            return {
                "status": "pass",
                "action": "disabled",
                "preference": item,
                "profile_backup": backup,
            }
    raise RuntimeError(f"未找到偏好：{item_id}")


def main() -> int:
    options = arguments()
    root = resolved_skill_root(options.skill_root)
    try:
        manifest = read_manifest(root)
        skill_name = manifest["skill_name"]
        profile_dir, profile_path, backup_dir = paths(skill_name, options.data_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)

        if options.command == "prepare":
            result = prepare(
                root,
                manifest,
                profile_path,
                backup_dir,
                (
                    Path(options.plugin_root).expanduser().resolve()
                    if options.plugin_root
                    else None
                ),
            )
        else:
            profile = load_profile(profile_path, skill_name)
            if options.command in {"context", "list"}:
                result = {
                    "status": "pass",
                    "skill": skill_name,
                    "release_tag": manifest.get("release_tag"),
                    "profile_path": str(profile_path),
                    "preferences": active_preferences(profile),
                }
            elif options.command == "remember":
                if options.instruction is None:
                    raise RuntimeError("remember需要--instruction")
                result = remember(
                    profile,
                    profile_path,
                    backup_dir,
                    options.instruction,
                    options.scope,
                    options.source,
                )
            elif options.command == "forget":
                if options.id is None:
                    raise RuntimeError("forget需要--id")
                result = forget(
                    profile,
                    profile_path,
                    backup_dir,
                    options.id,
                )
            else:
                result = {
                    "status": "pass",
                    "skill": skill_name,
                    "release_tag": manifest.get("release_tag"),
                    "profile_schema_version": PROFILE_SCHEMA_VERSION,
                    "profile_path": str(profile_path),
                    "profile_exists": profile_path.exists(),
                    "active_preferences": len(active_preferences(profile)),
                    "runtime_python": sys.version.split()[0],
                    "platform": platform.platform(),
                }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "skill_dir": str(root),
                    "errors": [str(exc)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""校验正式技能总数与可验证 Ed25519 签名覆盖率。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SIGNATURE_FILES = (
    "release-manifest.json",
    "release-manifest.json.sig",
    "release-signature.json",
    "publisher-ed25519.pub",
)


def verify_ed25519(skill_dir: Path, metadata: dict[str, object]) -> str | None:
    executable = shutil.which("ssh-keygen")
    if executable is None:
        return "宿主环境缺少 ssh-keygen，无法执行 Ed25519 验签"
    public_key = skill_dir / "publisher-ed25519.pub"
    fingerprint = subprocess.run(
        [executable, "-lf", str(public_key), "-E", "sha256"],
        check=False,
        capture_output=True,
        text=True,
    )
    if fingerprint.returncode:
        return "无法读取发布公钥指纹"
    actual_fingerprint = fingerprint.stdout.split()[1]
    if actual_fingerprint != metadata.get("public_key_fingerprint"):
        return "发布公钥指纹与签名元数据不一致"
    with tempfile.TemporaryDirectory(prefix="jiaotang-deploy-signature-") as temporary:
        allowed_signers = Path(temporary) / "allowed_signers"
        allowed_signers.write_text(
            "publisher " + public_key.read_text(encoding="utf-8").strip() + "\n",
            encoding="utf-8",
        )
        verification = subprocess.run(
            [
                executable,
                "-Y",
                "verify",
                "-f",
                str(allowed_signers),
                "-I",
                "publisher",
                "-n",
                str(metadata.get("signature_namespace") or "codex-skill-manifest"),
                "-s",
                str(skill_dir / "release-manifest.json.sig"),
            ],
            input=(skill_dir / "release-manifest.json").read_bytes(),
            check=False,
            capture_output=True,
        )
    return None if verification.returncode == 0 else "发布清单 Ed25519 验签失败"


def validate_signature_coverage(skills_root: Path) -> dict[str, object]:
    errors: list[str] = []
    suite_path = skills_root / "suite-manifest.json"
    if not suite_path.is_file():
        return {"status": "fail", "errors": ["缺少 suite-manifest.json"]}
    try:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "fail", "errors": [f"正式套件清单无法读取：{exc}"]}
    declared = suite.get("skills")
    if not isinstance(declared, list) or not declared or not all(
        isinstance(name, str) and name.strip() for name in declared
    ):
        return {"status": "fail", "errors": ["suite-manifest.json 的 skills 必须是非空字符串数组"]}
    skill_names = [name.strip() for name in declared]
    if len(set(skill_names)) != len(skill_names):
        errors.append("suite-manifest.json 存在重复技能名称")
    actual_names = sorted(
        path.name
        for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )
    missing_skills = sorted(set(skill_names) - set(actual_names))
    unexpected_skills = sorted(set(actual_names) - set(skill_names))
    if missing_skills:
        errors.append("正式清单中的技能目录缺失：" + "、".join(missing_skills))
    if unexpected_skills:
        errors.append("存在未列入正式清单的技能目录：" + "、".join(unexpected_skills))

    release_tag = str((suite.get("release") or {}).get("tag") or "")
    verified: list[str] = []
    for skill_name in skill_names:
        skill_dir = skills_root / skill_name
        if not skill_dir.is_dir():
            continue
        missing_files = [name for name in SIGNATURE_FILES if not (skill_dir / name).is_file()]
        if missing_files:
            errors.append(f"{skill_name} 缺少验签文件：" + "、".join(missing_files))
            continue
        try:
            manifest = json.loads((skill_dir / "release-manifest.json").read_text(encoding="utf-8"))
            metadata = json.loads((skill_dir / "release-signature.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{skill_name} 的签名清单无法读取：{exc}")
            continue
        if manifest.get("skill_name") != skill_name:
            errors.append(f"{skill_name} 的发布清单技能名称不一致")
        signature_error = verify_ed25519(skill_dir, metadata)
        if signature_error:
            errors.append(f"{skill_name}：{signature_error}")
        elif manifest.get("skill_name") == skill_name:
            verified.append(skill_name)

    signature_count = sum(
        1 for name in skill_names if (skills_root / name / "release-manifest.json.sig").is_file()
    )
    if signature_count != len(skill_names):
        errors.append(f"签名数量 {signature_count} 与技能总数 {len(skill_names)} 不一致")
    return {
        "status": "pass" if not errors else "fail",
        "release_tag": release_tag,
        "skill_total": len(skill_names),
        "signature_count": signature_count,
        "verified_count": len(verified),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", required=True)
    parser.add_argument("--output")
    parser.add_argument("--deployment-id", default="")
    parser.add_argument("--scope", default="local-preflight")
    options = parser.parse_args()
    result = validate_signature_coverage(Path(options.skills_root).expanduser().resolve())
    result.update(
        {
            "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "deployment_id": options.deployment_id,
            "scope": options.scope,
            "gate_type": "deployment-signature-coverage",
            "content_integrity_gate": "由技能套件发布流程独立执行",
        }
    )
    if options.output:
        output_path = Path(options.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

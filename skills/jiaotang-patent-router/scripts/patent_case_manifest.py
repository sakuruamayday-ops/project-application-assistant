#!/usr/bin/env python3
"""Create and enforce the single source of truth for a patent application case."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


MANIFEST_NAME = "patent-case-manifest.json"
SCHEMA_VERSION = "patent-case-manifest/v1"
DEFAULT_CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "patent-application-delivery-contract.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON根节点必须是对象：{path}")
    return value


def load_contract(path: Path) -> dict[str, Any]:
    contract = load_json(path)
    if contract.get("schema_version") != "patent-application-delivery-contract/v1":
        raise ValueError("专利申请交付契约版本无效")
    return contract


def manifest_path(case_dir: Path) -> Path:
    return case_dir.resolve() / MANIFEST_NAME


def load_manifest(case_dir: Path) -> dict[str, Any]:
    path = manifest_path(case_dir)
    if not path.is_file():
        raise ValueError(f"全案唯一清单不存在：{path}")
    manifest = load_json(path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("全案唯一清单版本无效")
    return manifest


def relative_case_path(case_dir: Path, value: str) -> tuple[Path, str]:
    root = case_dir.resolve()
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("案卷文件必须使用案卷目录内的相对路径")
    resolved = (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("案卷文件越出案卷目录") from exc
    if resolved == root:
        raise ValueError("案卷文件不能指向案卷目录本身")
    return resolved, relative.as_posix()


def role_spec(contract: dict[str, Any], role: str) -> dict[str, Any]:
    roles = contract.get("roles")
    spec = roles.get(role) if isinstance(roles, dict) else None
    if not isinstance(spec, dict):
        raise ValueError(f"交付契约未登记角色：{role}")
    return spec


def artifact_for(manifest: dict[str, Any], role: str) -> dict[str, Any] | None:
    artifacts = manifest.get("artifacts")
    value = artifacts.get(role) if isinstance(artifacts, dict) else None
    return value if isinstance(value, dict) else None


def init_manifest(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = args.case_dir.resolve()
    case_dir.mkdir(parents=True, exist_ok=True)
    target = manifest_path(case_dir)
    if target.exists():
        raise ValueError(f"全案唯一清单已存在：{target}")
    contract_path = args.contract.resolve()
    contract = load_contract(contract_path)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "case_id": args.case_id,
        "case_revision": 1,
        "anonymized_test_fixture": bool(args.fixture),
        "contract": {
            "contract_id": contract["contract_id"],
            "schema_version": contract["schema_version"],
            "sha256": sha256_file(contract_path),
        },
        "artifacts": {},
        "superseded_artifacts": [],
    }
    atomic_write_json(target, manifest)
    return {
        "status": "pass",
        "manifest": str(target),
        "case_id": args.case_id,
        "case_revision": 1,
    }


def revise_manifest(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(args.case_dir)
    manifest["case_revision"] = int(manifest.get("case_revision") or 0) + 1
    manifest["revision_reason"] = args.reason
    atomic_write_json(manifest_path(args.case_dir), manifest)
    return {
        "status": "pass",
        "case_revision": manifest["case_revision"],
        "message": "案件版本已提升；旧版本文件会在交付门禁中被判为错版。",
    }


def register_artifact(
    *,
    case_dir: Path,
    manifest: dict[str, Any],
    contract: dict[str, Any],
    role: str,
    path_value: str,
    dependencies: list[str] | None,
) -> dict[str, Any]:
    spec = role_spec(contract, role)
    absolute, relative = relative_case_path(case_dir, path_value)
    if not absolute.is_file():
        raise ValueError(f"待登记文件不存在：{relative}")
    suffix = absolute.suffix.lower().lstrip(".")
    formats = [str(item).lower() for item in spec.get("formats") or []]
    if suffix not in formats:
        raise ValueError(f"{role}文件格式必须是：{', '.join(formats)}")
    if suffix == "json":
        content = load_json(absolute)
        embedded_case_id = str(content.get("case_id") or "").strip()
        if embedded_case_id and embedded_case_id != manifest.get("case_id"):
            raise ValueError(
                f"{role}属于案件{embedded_case_id}，"
                f"当前清单为{manifest.get('case_id')}"
            )
        embedded_revision = content.get("case_revision")
        if (
            embedded_revision is not None
            and int(embedded_revision) != int(manifest.get("case_revision") or 0)
        ):
            raise ValueError(
                f"{role}内容属于案件版本{embedded_revision}，"
                f"当前版本为{manifest.get('case_revision')}"
            )

    artifacts = manifest.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        raise ValueError("全案唯一清单的artifacts字段无效")
    for existing_role, existing in artifacts.items():
        if (
            existing_role != role
            and isinstance(existing, dict)
            and existing.get("path") == relative
        ):
            raise ValueError(f"同一文件已登记为另一角色：{existing_role}")

    required_dependencies = [
        str(item) for item in spec.get("depends_on") or []
    ]
    requested_dependencies = (
        list(dict.fromkeys(dependencies))
        if dependencies is not None
        else required_dependencies
    )
    missing_declared = [
        item for item in required_dependencies if item not in requested_dependencies
    ]
    if missing_declared:
        raise ValueError(
            f"{role}缺少契约依赖声明：{', '.join(missing_declared)}"
        )
    dependency_hashes: dict[str, str] = {}
    for dependency_role in requested_dependencies:
        dependency = artifact_for(manifest, dependency_role)
        if not dependency:
            raise ValueError(f"{role}依赖尚未登记：{dependency_role}")
        dependency_hashes[dependency_role] = str(dependency.get("sha256") or "")

    existing = artifact_for(manifest, role)
    if existing:
        history = manifest.setdefault("superseded_artifacts", [])
        if not isinstance(history, list):
            raise ValueError("全案唯一清单的superseded_artifacts字段无效")
        history.append(existing)
    record = {
        "role": role,
        "path": relative,
        "format": suffix,
        "stage": str(spec.get("stage") or ""),
        "revision": int(manifest["case_revision"]),
        "sha256": sha256_file(absolute),
        "dependency_hashes": dependency_hashes,
    }
    artifacts[role] = record
    atomic_write_json(manifest_path(case_dir), manifest)
    return record


def register_command(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(args.case_dir)
    contract = load_contract(args.contract.resolve())
    record = register_artifact(
        case_dir=args.case_dir,
        manifest=manifest,
        contract=contract,
        role=args.role,
        path_value=args.path,
        dependencies=args.depends_on,
    )
    return {"status": "pass", "artifact": record}


def validate_manifest(
    case_dir: Path,
    manifest: dict[str, Any],
    contract: dict[str, Any],
    milestone: str,
) -> dict[str, Any]:
    milestones = contract.get("milestones")
    specification = milestones.get(milestone) if isinstance(milestones, dict) else None
    if not isinstance(specification, dict):
        raise ValueError(f"交付契约未登记里程碑：{milestone}")

    errors: list[dict[str, str]] = []

    def add(code: str, role: str, message: str, repair: str) -> None:
        errors.append(
            {
                "code": code,
                "role": role,
                "message": message,
                "repair_task": repair,
            }
        )

    if (
        manifest.get("anonymized_test_fixture")
        and not specification.get("allow_anonymized_test_fixture")
    ):
        add(
            "FIXTURE_NOT_FILING_READY",
            "manifest",
            "匿名测试夹具不得作为正式提交案卷。",
            "新建非测试案件清单并使用已确认的真实事实底稿重新生成全部交付物。",
        )

    current_revision = int(manifest.get("case_revision") or 0)
    required_roles = [str(item) for item in specification.get("required_roles") or []]
    for role in required_roles:
        spec = role_spec(contract, role)
        artifact = artifact_for(manifest, role)
        if not artifact:
            add(
                "MISSING_ARTIFACT",
                role,
                f"缺少交付角色：{role}",
                f"生成并登记{role}，然后重新运行{milestone}门禁。",
            )
            continue
        try:
            absolute, relative = relative_case_path(case_dir, str(artifact.get("path") or ""))
        except ValueError as exc:
            add(
                "INVALID_PATH",
                role,
                str(exc),
                f"将{role}移入案卷目录并重新登记。",
            )
            continue
        if not absolute.is_file():
            add(
                "MISSING_FILE",
                role,
                f"清单中的文件不存在：{relative}",
                f"恢复{relative}或重新生成并登记{role}。",
            )
            continue
        actual_sha = sha256_file(absolute)
        if actual_sha != artifact.get("sha256"):
            add(
                "HASH_MISMATCH",
                role,
                f"{relative}内容已变化但未重新登记。",
                f"核对{role}内容后重新登记，并重建所有依赖该文件的下游文件。",
            )
        if (
            spec.get("requires_current_revision")
            and int(artifact.get("revision") or 0) != current_revision
        ):
            add(
                "WRONG_CASE_REVISION",
                role,
                f"{role}属于案件版本{artifact.get('revision')}，当前版本为{current_revision}。",
                f"基于案件版本{current_revision}重新生成并登记{role}。",
            )
        dependency_hashes = artifact.get("dependency_hashes")
        if not isinstance(dependency_hashes, dict):
            dependency_hashes = {}
        for dependency_role in [str(item) for item in spec.get("depends_on") or []]:
            dependency = artifact_for(manifest, dependency_role)
            if not dependency:
                add(
                    "MISSING_DEPENDENCY",
                    role,
                    f"{role}缺少上游文件：{dependency_role}",
                    f"先登记{dependency_role}，再重建并登记{role}。",
                )
                continue
            if dependency_hashes.get(dependency_role) != dependency.get("sha256"):
                add(
                    "STALE_DEPENDENCY",
                    role,
                    f"{role}引用的{dependency_role}不是清单中的当前版本。",
                    f"使用当前{dependency_role}重建{role}并重新登记。",
                )

    return {
        "schema_version": "patent-case-validation/v1",
        "case_id": manifest.get("case_id"),
        "case_revision": current_revision,
        "milestone": milestone,
        "completion_allowed": not errors,
        "status": "pass" if not errors else "fail",
        "errors": errors,
    }


def validate_command(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(args.case_dir)
    contract = load_contract(args.contract.resolve())
    return validate_manifest(args.case_dir, manifest, contract, args.milestone)


def checklist_command(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(args.case_dir)
    contract = load_contract(args.contract.resolve())
    output, relative = relative_case_path(args.case_dir, args.out)
    lines = [
        "# 专利申请提交清单",
        "",
        f"- 案件标识：`{manifest['case_id']}`",
        f"- 案件版本：`{manifest['case_revision']}`",
        f"- 测试夹具：`{str(bool(manifest.get('anonymized_test_fixture'))).lower()}`",
        "",
        "| 角色 | 文件 | SHA-256 | 版本 |",
        "|---|---|---|---:|",
    ]
    checklist_dependencies = [
        str(item)
        for item in role_spec(contract, "submission_checklist").get("depends_on") or []
    ]
    for role in checklist_dependencies:
        artifact = artifact_for(manifest, role)
        if artifact:
            lines.append(
                f"| `{role}` | `{artifact['path']}` | `{artifact['sha256']}` | "
                f"{artifact['revision']} |"
            )
        else:
            lines.append(f"| `{role}` | 缺失 | — | — |")
    lines.extend(
        [
            "",
            "> 本清单只证明案卷文件版本与依赖关系通过机器校验，不代替申请人、发明人和代理师的提交确认。",
            "",
        ]
    )
    atomic_write_text(output, "\n".join(lines))
    record = register_artifact(
        case_dir=args.case_dir,
        manifest=manifest,
        contract=contract,
        role="submission_checklist",
        path_value=relative,
        dependencies=checklist_dependencies,
    )
    return {"status": "pass", "artifact": record}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--case-dir", type=Path, required=True)
    init.add_argument("--case-id", required=True)
    init.add_argument("--fixture", action="store_true")
    init.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    init.set_defaults(function=init_manifest)

    revise = commands.add_parser("revise")
    revise.add_argument("--case-dir", type=Path, required=True)
    revise.add_argument("--reason", required=True)
    revise.set_defaults(function=revise_manifest)

    register = commands.add_parser("register")
    register.add_argument("--case-dir", type=Path, required=True)
    register.add_argument("--role", required=True)
    register.add_argument("--path", required=True)
    register.add_argument("--depends-on", action="append")
    register.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    register.set_defaults(function=register_command)

    validate = commands.add_parser("validate")
    validate.add_argument("--case-dir", type=Path, required=True)
    validate.add_argument(
        "--milestone",
        choices=("draft-ready", "fixture", "filing-ready"),
        required=True,
    )
    validate.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    validate.set_defaults(function=validate_command)

    checklist = commands.add_parser("checklist")
    checklist.add_argument("--case-dir", type=Path, required=True)
    checklist.add_argument("--out", default="submission-checklist.md")
    checklist.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    checklist.set_defaults(function=checklist_command)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = args.function(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"status": "fail", "completion_allowed": False, "error": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("completion_allowed") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

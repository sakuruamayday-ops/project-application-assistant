#!/usr/bin/env python3
"""Prepare an isolated full-suite Codex desktop-client evaluation workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "tests" / "codex-client-skill-matrix.json"
EXPECTED_PHASES = ("implicit", "explicit", "negative", "functional")
PHASE_GUARDS = {
    "implicit": (
        "这是隔离的Codex客户端隐式路由测试。只依据本提示中的脱敏或虚构信息作答；"
        "除读取本项目 .agents/skills 下被路由技能的说明和资源外，不读取其他工作区文件、"
        "历史任务或客户资料，不联网，不修改文件，不请求额外权限。"
    ),
    "explicit": (
        "这是隔离的Codex客户端显式加载测试。只允许读取本项目 .agents/skills 下点名技能的"
        "说明和资源；不读取其他工作区文件、历史任务或客户资料，不联网，不修改文件，不请求额外权限。"
    ),
    "negative": (
        "这是隔离的Codex客户端负向边界测试。只判断应路由到哪类能力并给出简短理由；"
        "除读取本项目 .agents/skills 下实际路由技能的说明外，不读取工作区资料，不联网，不修改文件，"
        "不请求额外权限。"
    ),
    "functional": (
        "这是隔离的Codex客户端功能交付测试。只使用提示内的脱敏或虚构数据；"
        "除读取本项目 .agents/skills 下点名技能的说明和资源外，不读取其他工作区文件、历史任务或"
        "客户资料；仅可额外读取用例明确列出的本地离线测试夹具。不联网，不请求额外权限。允许且只允许在 {artifact_dir} 写入本用例的测试状态与"
        "交付物；如技能需要持久化状态，必须将GONGCHUANG_SKILL_DATA_DIR显式设为该目录，禁止写入"
        "用户配置目录、正式知识库或其他路径。若用例无需文件交付，可以只在回复中完成。"
    ),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    ignored = {".DS_Store", "__pycache__", ".pytest_cache"}
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in ignored for part in path.parts)
    ]
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def effective_prompt(
    phase: str,
    raw_prompt: str,
    *,
    artifact_dir: Path | None = None,
) -> str:
    guard = PHASE_GUARDS[phase]
    if phase == "functional":
        if artifact_dir is None:
            raise RuntimeError("功能交付阶段必须提供隔离产物目录")
        guard = guard.format(artifact_dir=artifact_dir)
    return f"{guard}\n\n{raw_prompt.strip()}"


def frontmatter_description(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise RuntimeError(f"SKILL.md缺少首字节frontmatter：{skill_md}")
    match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"SKILL.md缺少description：{skill_md}")
    return match.group(1).strip()


def move_to_trash(path: Path) -> Path:
    trash = Path.home() / ".Trash"
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = trash / f"{path.name}-codex-client-harness-{stamp}"
    counter = 1
    while target.exists() or target.is_symlink():
        target = trash / f"{path.name}-codex-client-harness-{stamp}-{counter}"
        counter += 1
    shutil.move(str(path), str(target))
    return target


def validate_matrix(matrix: dict, declared_skills: list[str]) -> list[dict]:
    if matrix.get("schema_version") != 1:
        raise RuntimeError("客户端测试矩阵schema_version必须为1")
    cases = matrix.get("skills") or []
    names = [item.get("skill") for item in cases]
    if names != declared_skills:
        missing = sorted(set(declared_skills) - set(names))
        extra = sorted(set(names) - set(declared_skills))
        raise RuntimeError(
            "测试矩阵必须按suite-manifest顺序精确覆盖全部技能；"
            f"expected={len(declared_skills)}, missing={missing}, extra={extra}"
        )
    for expected_index, item in enumerate(cases, start=1):
        if item.get("index") != expected_index:
            raise RuntimeError(f"矩阵序号错误：{item.get('skill')}")
        for phase in EXPECTED_PHASES:
            prompt = str(item.get(f"{phase}_prompt") or "").strip()
            if not prompt:
                raise RuntimeError(f"{item['skill']}缺少{phase}测试提示")
        if item["skill"] in item["implicit_prompt"]:
            raise RuntimeError(f"{item['skill']}隐式路由提示泄露目标技能名")
        implicit_behavior = item.get("implicit_expected_behavior") or "triggered"
        if implicit_behavior not in {"triggered", "not_triggered"}:
            raise RuntimeError(f"{item['skill']}隐式行为类型无效：{implicit_behavior}")
        expected_negative = item.get("negative_expected_skill")
        expected_behavior = item.get("negative_expected_behavior") or (
            "rerouted" if expected_negative else "not_triggered"
        )
        if expected_behavior not in {"rerouted", "not_triggered", "refused_in_scope"}:
            raise RuntimeError(f"{item['skill']}负向行为类型无效：{expected_behavior}")
        if expected_behavior == "refused_in_scope":
            if expected_negative != item["skill"]:
                raise RuntimeError(f"{item['skill']}拒绝型负向用例必须由目标技能处理")
        elif expected_negative == item["skill"]:
            raise RuntimeError(f"{item['skill']}负向用例不能仍期待目标技能")
        elif expected_behavior == "rerouted" and not expected_negative:
            raise RuntimeError(f"{item['skill']}重路由负向用例缺少期望技能")
        elif expected_behavior == "not_triggered" and expected_negative:
            raise RuntimeError(f"{item['skill']}不触发负向用例不应指定期望技能")
    return cases


def prepare(options: argparse.Namespace) -> dict:
    skills_root = Path(options.skills_root).expanduser().resolve()
    project_root = Path(options.project_root).expanduser().resolve()
    suite = load_json(skills_root / "suite-manifest.json")
    declared = list(suite.get("skills") or [])
    if not declared or len(set(declared)) != len(declared):
        raise RuntimeError("Codex客户端全量测试要求suite-manifest声明非空且不重复的技能清单")
    matrix_path = Path(options.matrix).expanduser().resolve()
    matrix = load_json(matrix_path)
    cases = validate_matrix(matrix, declared)

    missing_dirs = [name for name in declared if not (skills_root / name / "SKILL.md").is_file()]
    if missing_dirs:
        raise RuntimeError(f"候选技能目录不完整：{missing_dirs}")

    repo_skills = project_root / ".agents" / "skills"
    trashed = None
    if repo_skills.exists() or repo_skills.is_symlink():
        if not options.replace:
            raise RuntimeError(f"项目级Skills已存在；使用--replace才允许移入废纸篓：{repo_skills}")
        trashed = move_to_trash(repo_skills)
    repo_skills.mkdir(parents=True, exist_ok=False)

    skill_records = []
    description_chars = 0
    for name in declared:
        source = skills_root / name
        target = repo_skills / name
        if options.materialization == "copy":
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", ".pytest_cache"),
            )
        else:
            target.symlink_to(source, target_is_directory=True)
        description = frontmatter_description(source / "SKILL.md")
        estimated_entry = f"- {name}: {description} ({target / 'SKILL.md'})\n"
        description_chars += len(estimated_entry)
        skill_records.append(
            {
                "skill": name,
                "source": str(source),
                "project_path": str(target),
                "materialization": options.materialization,
                "tree_sha256": tree_sha256(source),
                "materialized_tree_sha256": tree_sha256(target),
                "description_chars": len(description),
            }
        )

    created_at = datetime.now(timezone.utc).astimezone()
    run_id = options.run_id or created_at.strftime("%Y%m%dT%H%M%S")
    run_dir = project_root / ".codex-client-harness" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "receipts").mkdir()
    (run_dir / "transcripts").mkdir()
    (run_dir / "artifacts").mkdir()

    case_dir = run_dir / "cases"
    case_dir.mkdir()
    for item in cases:
        artifact_dir = run_dir / "artifacts" / f"{item['index']:02d}-{item['skill']}"
        artifact_dir.mkdir()
        functional_fixture_path = None
        fixture = item.get("functional_fixture")
        if fixture:
            filename = str(fixture.get("filename") or "").strip()
            if not filename or Path(filename).name != filename:
                raise RuntimeError(f"{item['skill']}离线夹具文件名无效")
            functional_fixture_path = artifact_dir / filename
            functional_fixture_path.write_text(
                str(fixture.get("content") or ""),
                encoding="utf-8",
            )
        raw_prompts = {
            phase: item[f"{phase}_prompt"]
            for phase in EXPECTED_PHASES
        }
        if functional_fixture_path:
            raw_prompts["functional"] = raw_prompts["functional"].replace(
                "{functional_fixture_path}",
                str(functional_fixture_path),
            )
        effective_prompts = {
            phase: effective_prompt(
                phase,
                raw_prompts[phase],
                artifact_dir=artifact_dir if phase == "functional" else None,
            )
            for phase in EXPECTED_PHASES
        }
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            **item,
            "candidate_skill_tree_sha256": next(
                record["tree_sha256"]
                for record in skill_records
                if record["skill"] == item["skill"]
            ),
            "functional_artifact_dir": str(artifact_dir),
            "functional_fixture_path": (
                str(functional_fixture_path) if functional_fixture_path else None
            ),
            "prompt_sha256": {
                phase: sha256_bytes(effective_prompts[phase].encode("utf-8"))
                for phase in EXPECTED_PHASES
            },
            "raw_prompt_sha256": {
                phase: sha256_bytes(raw_prompts[phase].encode("utf-8"))
                for phase in EXPECTED_PHASES
            },
            "effective_prompt": effective_prompts,
        }
        (case_dir / f"{item['index']:02d}-{item['skill']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    run_manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": created_at.isoformat(timespec="seconds"),
        "status": "prepared",
        "execution_host": "codex-desktop-client",
        "execution_mode": "full-suite-isolated-client-threads-four-phases",
        "skill_materialization": options.materialization,
        "phase_guards": PHASE_GUARDS,
        "publish_authorized": False,
        "suite_release": suite.get("release", {}).get("tag"),
        "suite_manifest_sha256": sha256_bytes(
            (skills_root / "suite-manifest.json").read_bytes()
        ),
        "matrix_sha256": sha256_bytes(matrix_path.read_bytes()),
        "skill_count": len(declared),
        "phase_count": len(EXPECTED_PHASES),
        "expected_receipt_count": len(declared) * len(EXPECTED_PHASES),
        "description_budget": {
            "estimated_initial_list_chars": description_chars,
            "documented_unknown_context_limit_chars": 8000,
            "compression_risk": description_chars > 8000,
            "required_test": "all-declared-skills-present-implicit-routing",
        },
        "skills": skill_records,
        "project_skills_root": str(repo_skills),
        "replaced_project_skills_trashed_to": str(trashed) if trashed else None,
    }
    (run_dir / "run-manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "thread-map.json").write_text("{}\n", encoding="utf-8")
    print(json.dumps(run_manifest, ensure_ascii=False, indent=2))
    return run_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", default=str(ROOT / "skills"))
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--run-id")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--materialization",
        choices=("copy", "symlink"),
        default="copy",
        help="copy avoids cross-project sandbox approval; symlink is retained for compatibility checks",
    )
    options = parser.parse_args()
    prepare(options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

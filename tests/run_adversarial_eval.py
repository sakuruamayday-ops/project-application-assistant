#!/usr/bin/env python3
"""使用本机WorkBuddy插件对选定对抗题执行隔离评测。"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPTS = ROOT / "tests" / "adversarial-prompts.jsonl"
DEFAULT_EXPECTED = ROOT / "tests" / "adversarial-expected.json"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codebuddy-cli", required=True)
    parser.add_argument("--suite-zip", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prompts", default=str(DEFAULT_PROMPTS))
    parser.add_argument("--expected", default=str(DEFAULT_EXPECTED))
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="并行执行的隔离WorkBuddy用例数；默认1保持兼容。",
    )
    return parser.parse_args()


def extract_plugin(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = member.filename.replace("\\", "/")
            path = PurePosixPath(name)
            mode = (member.external_attr >> 16) & 0o170000
            canonical = "/".join(
                part for part in path.parts if part not in {"", "."}
            )
            identity = canonical.casefold()
            if (
                name != member.filename
                or not canonical
                or path.is_absolute()
                or ".." in path.parts
                or ":" in name
                or "\x00" in name
                or mode == stat.S_IFLNK
                or identity in seen
            ):
                raise RuntimeError(
                    f"ZIP条目不安全或重复：{member.filename}"
                )
            seen.add(identity)
            target = (destination / Path(*path.parts)).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"ZIP路径越界：{member.filename}")
        bundle.extractall(destination)
    manifests = list(destination.rglob(".codebuddy-plugin/plugin.json"))
    if len(manifests) != 1:
        raise RuntimeError(f"应有1个插件清单，实际{len(manifests)}")
    return manifests[0].parent.parent


def recoverable_workspace(prefix: str) -> Path:
    workspace_root = Path(
        os.environ.get("JIAOTANG_RELEASE_WORK_ROOT", tempfile.gettempdir())
    ).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=workspace_root))


def parse_route_json(stdout: str) -> dict:
    texts = [stdout]
    try:
        payload = json.loads(stdout)

        def collect(value):
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)

        collect(payload)
    except json.JSONDecodeError:
        pass
    matches = []
    for text in texts:
        matches.extend(re.findall(r"ROUTE_JSON:\s*(\{[^\r\n]*\})", text))
    if not matches:
        return {}
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return {}


def latest_active_skills(data_root: Path) -> list[str]:
    sessions = data_root / "workbuddy" / "preference-bridge" / "sessions"
    states = sorted(sessions.glob("*.json"), key=lambda path: path.stat().st_mtime)
    if not states:
        return []
    state = json.loads(states[-1].read_text(encoding="utf-8"))
    return [
        item.get("skill")
        for item in state.get("active_skills", [])
        if item.get("skill")
    ]


def score_case(
    expected: dict,
    route: dict,
    active_skills: list[str],
    exit_code: int,
    timed_out: bool,
) -> dict:
    declared = route.get("activated_skills", [])
    observed = sorted(set(active_skills) | set(declared))
    route_primary = route.get("primary_skill")
    inferred_candidates = [
        skill for skill in active_skills if skill != "project-task-router"
    ]
    effective_primary = route_primary or (
        inferred_candidates[0] if inferred_candidates else None
    )
    primary_ok = effective_primary == expected["expected_primary_skill"]
    forbidden_hit = sorted(set(expected.get("forbidden_skills", [])) & set(observed))
    required_missing = sorted(set(expected.get("required_skills", [])) - set(observed))
    clarification_ok = bool(route.get("clarification_required")) == bool(
        expected.get("clarification_required")
    )
    policy_ok = True
    limitation_ok = True
    if expected.get("category") == "stale-policy":
        policy_ok = route.get("policy_status") == "stale"
        limitation_ok = route.get("claims_limited") is True
    execution_ok = exit_code == 0 and not timed_out
    passed = (
        execution_ok
        and primary_ok
        and not forbidden_hit
        and not required_missing
        and clarification_ok
        and policy_ok
        and limitation_ok
    )
    return {
        "status": "pass" if passed else "fail",
        "execution_ok": execution_ok,
        "primary_ok": primary_ok,
        "effective_primary_skill": effective_primary,
        "primary_source": "route-json" if route_primary else "hook-inferred",
        "observed_skills": observed,
        "required_missing": required_missing,
        "forbidden_hit": forbidden_hit,
        "clarification_ok": clarification_ok,
        "policy_ok": policy_ok,
        "limitation_ok": limitation_ok,
    }


def run_case(
    *,
    item: dict,
    expected: dict,
    output: Path,
    plugin_root: Path,
    codebuddy_cli: str,
    max_turns: int,
    timeout_seconds: int,
) -> dict:
    case_dir = output / item["case_id"]
    case_dir.mkdir(parents=True)
    data_root = case_dir / "isolated-data"
    env = os.environ.copy()
    env["JIAOTANG_WORKBUDDY_PLUGIN_DATA"] = str(data_root / "workbuddy")
    env["GONGCHUANG_SKILL_DATA_DIR"] = str(data_root / "profiles")
    route_prompt = (
        item["prompt"]
        + "\n\n这是处理路径预检门禁，不是业务答复。请从当前加载的 "
        "jiaotang-workbuddy-skills 插件中实际加载完成路由所需的最少技能，"
        "但不要联网、不要检索外部资料、不要读取与路由无关的参考文件、"
        "不要分析企业条件、不要写正式材料，也不要输出解释、标题、表格或建议。"
        "primary_skill必须是已经实际加载的业务技能，并同时出现在"
        "activated_skills中；只加载project-task-router或只声明未加载的主技能"
        "都不合格。"
        "完成必要的技能加载后，只输出下面格式的一行，不得输出其他内容："
        'ROUTE_JSON: {"primary_skill":"技能目录名","activated_skills":'
        '["实际加载的技能目录名"],"clarification_required":false,'
        '"policy_status":"current|stale|unknown|not-applicable",'
        '"claims_limited":false}'
    )
    command = [
        codebuddy_cli,
        "-p",
        route_prompt,
        "--output-format",
        "json",
        "--max-turns",
        str(max_turns),
        "--plugin-dir",
        str(plugin_root),
    ]
    timed_out = False
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=timeout_seconds,
        )
        stdout = process.stdout
        stderr = process.stderr
        exit_code = process.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + (
            f"\n单题超过{timeout_seconds}秒，运行器已终止该题。"
        )
        exit_code = 124
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    (case_dir / "stdout.json").write_text(stdout, encoding="utf-8")
    (case_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    route = parse_route_json(stdout)
    active_skills = latest_active_skills(data_root)
    score = score_case(
        expected,
        route,
        active_skills,
        exit_code,
        timed_out,
    )
    return {
        "case_id": item["case_id"],
        "category": item["category"],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "route": route,
        "hook_active_skills": active_skills,
        **score,
    }


def main() -> int:
    options = arguments()
    output = Path(options.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    prompts = [
        json.loads(line)
        for line in Path(options.prompts).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    answers = {
        item["case_id"]: item
        for item in json.loads(
            Path(options.expected).read_text(encoding="utf-8")
        )["answers"]
    }
    if options.case_ids:
        wanted = set(options.case_ids)
        prompts = [item for item in prompts if item["case_id"] in wanted]
    if options.categories:
        wanted_categories = set(options.categories)
        prompts = [
            item for item in prompts if item["category"] in wanted_categories
        ]
    if options.limit:
        prompts = prompts[: options.limit]
    if not prompts:
        raise RuntimeError("没有选中任何测试用例")

    workspace = recoverable_workspace("jiaotang-adversarial-eval-")
    plugin_root = extract_plugin(
        Path(options.suite_zip).expanduser().resolve(), workspace / "plugin"
    )
    worker_count = max(1, min(options.workers, len(prompts)))
    codebuddy_cli = str(Path(options.codebuddy_cli).expanduser().resolve())
    results_by_case = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count
    ) as executor:
        futures = {
            executor.submit(
                run_case,
                item=item,
                expected=answers[item["case_id"]],
                output=output,
                plugin_root=plugin_root,
                codebuddy_cli=codebuddy_cli,
                max_turns=options.max_turns,
                timeout_seconds=options.timeout_seconds,
            ): item["case_id"]
            for item in prompts
        }
        for index, future in enumerate(
            concurrent.futures.as_completed(futures), start=1
        ):
            result = future.result()
            results_by_case[result["case_id"]] = result
            print(
                json.dumps(
                    {
                        "progress": f"{index}/{len(prompts)}",
                        "case_id": result["case_id"],
                        "status": result["status"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    results = [results_by_case[item["case_id"]] for item in prompts]

    passed = sum(item["status"] == "pass" for item in results)
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        ),
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "status": "pass" if passed == len(results) else "fail",
        "temporary_workspace": str(workspace),
        "results": results,
    }
    (output / "adversarial-eval-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())

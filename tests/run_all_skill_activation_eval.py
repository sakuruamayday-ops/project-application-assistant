#!/usr/bin/env python3
"""Exercise every declared Skill through a real WorkBuddy plugin session."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def safe_extract(archive: Path, destination: Path) -> None:
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
                raise RuntimeError(f"ZIP条目不安全或重复：{member.filename}")
            seen.add(identity)
            target = (destination / Path(*path.parts)).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"ZIP路径越界：{member.filename}")
        bundle.extractall(destination)


def latest_active_skills(data_root: Path) -> set[str]:
    sessions = data_root / "workbuddy" / "preference-bridge" / "sessions"
    states = sorted(
        sessions.glob("*.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    if not states:
        return set()
    state = json.loads(states[-1].read_text(encoding="utf-8"))
    return {
        str(item.get("skill"))
        for item in state.get("active_skills") or []
        if isinstance(item, dict) and item.get("skill")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codebuddy-cli", required=True)
    parser.add_argument("--suite-zip", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    options = parser.parse_args()
    cli = Path(options.codebuddy_cli).expanduser().resolve()
    if not cli.is_file():
        raise RuntimeError("真实WorkBuddy CLI不存在")
    output = Path(options.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    workspace_root = Path(
        os.environ.get("JIAOTANG_RELEASE_WORK_ROOT", tempfile.gettempdir())
    ).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    workspace = Path(
        tempfile.mkdtemp(
            prefix="all-skill-activation-",
            dir=workspace_root,
        )
    )
    extracted = workspace / "extracted"
    safe_extract(Path(options.suite_zip).expanduser().resolve(), extracted)
    manifests = list(extracted.rglob(".codebuddy-plugin/plugin.json"))
    if len(manifests) != 1:
        raise RuntimeError("候选包必须且只能包含一个WorkBuddy插件")
    plugin_root = manifests[0].parent.parent
    suite = json.loads(
        (plugin_root / "skills" / "suite-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    skills = list(suite.get("skills") or [])
    if not skills or len(set(skills)) != len(skills):
        raise RuntimeError("真实行为门禁要求套件技能清单非空且不重复")
    results = []
    for offset in range(0, len(skills), options.batch_size):
        expected = skills[offset : offset + options.batch_size]
        batch = offset // options.batch_size + 1
        data_root = output / f"batch-{batch:02d}-data"
        environment = os.environ.copy()
        environment["JIAOTANG_WORKBUDDY_PLUGIN_DATA"] = str(
            data_root / "workbuddy"
        )
        environment["GONGCHUANG_SKILL_DATA_DIR"] = str(data_root / "profiles")
        prompt = (
            "这是发布候选包的真实激活检查。请逐个实际加载下列技能，"
            "不要联网、不要写文件、不要执行其业务任务；加载完只回复"
            "“激活检查完成”："
            + "、".join(expected)
        )
        process = subprocess.run(
            [
                str(cli),
                "-p",
                prompt,
                "--output-format",
                "json",
                "--max-turns",
                str(max(8, len(expected) * 2)),
                "--plugin-dir",
                str(plugin_root),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=options.timeout_seconds,
        )
        (output / f"batch-{batch:02d}.stdout.json").write_text(
            process.stdout,
            encoding="utf-8",
        )
        (output / f"batch-{batch:02d}.stderr.txt").write_text(
            process.stderr,
            encoding="utf-8",
        )
        observed = latest_active_skills(data_root)
        missing = sorted(set(expected) - observed)
        results.append(
            {
                "batch": batch,
                "expected": expected,
                "observed": sorted(observed),
                "missing": missing,
                "exit_code": process.returncode,
                "status": (
                    "pass"
                    if process.returncode == 0 and not missing
                    else "fail"
                ),
            }
        )
    failed = [item for item in results if item["status"] != "pass"]
    report = {
        "status": "pass" if not failed else "fail",
        "skill_count": len(skills),
        "batches": results,
        "failed_batches": [item["batch"] for item in failed],
    }
    (output / "all-skill-activation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())

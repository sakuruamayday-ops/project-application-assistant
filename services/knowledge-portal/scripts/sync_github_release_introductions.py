#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.release_introductions import (  # noqa: E402
    release_function_introduction,
    release_introduction_versions,
)


def run_gh(*arguments: str) -> str:
    completed = subprocess.run(
        ["gh", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将共用功能简介目录同步到 GitHub 历史 Release"
    )
    parser.add_argument(
        "--repository",
        default="sakuruamayday-ops/project-application-assistant",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际更新 Release 标题和正文；默认仅审计差异",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    repository = str(arguments.repository).strip()
    raw = run_gh(
        "api",
        f"repos/{repository}/releases?per_page=100",
    )
    github_releases = json.loads(raw)
    by_tag = {
        str(item.get("tag_name") or ""): item
        for item in github_releases
        if isinstance(item, dict)
    }
    versions = release_introduction_versions()
    missing = [f"V{version}" for version in versions if f"V{version}" not in by_tag]
    if missing:
        raise SystemExit("GitHub 缺少功能简介目录中的版本：" + ", ".join(missing))

    records = []
    for version in versions:
        tag = f"V{version}"
        release = by_tag[tag]
        old_title = str(release.get("name") or "")
        old_body = str(release.get("body") or "")
        new_title = f"共创研究院企业全生命周期助手 {tag}"
        new_body = release_function_introduction(version)
        record = {
            "tag": tag,
            "old_title": old_title,
            "new_title": new_title,
            "old_body_sha256": sha256_text(old_body),
            "new_body_sha256": sha256_text(new_body),
            "title_changed": old_title != new_title,
            "body_changed": old_body != new_body,
            "applied": False,
        }
        if arguments.apply and (record["title_changed"] or record["body_changed"]):
            run_gh(
                "release",
                "edit",
                tag,
                "--repo",
                repository,
                "--title",
                new_title,
                "--notes",
                new_body,
            )
            record["applied"] = True
        records.append(record)

    changed = [record for record in records if record["title_changed"] or record["body_changed"]]
    print(
        json.dumps(
            {
                "schema": "gongchuang-github-release-introduction-sync/v1",
                "repository": repository,
                "mode": "apply" if arguments.apply else "audit",
                "release_count": len(records),
                "changed_count": len(changed),
                "applied_count": sum(bool(record["applied"]) for record in records),
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Manage the local preference overlay and synchronize it with the team service."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_runtime"))
from result_digest import canonical_json, loads
from sync_fields import differences


DEFAULT_PATH = Path.home() / ".config" / "project-assistant" / "preferences.json"
MISSING = object()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON顶层必须是对象：{path}")
    return payload


def write_local(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    temporary.replace(path)


def request_json(
    method: str,
    endpoint: str,
    token: str,
    route: str,
    payload=None,
):
    body = None if payload is None else canonical_json(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + route,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "project-assistant-preferences/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"云端返回HTTP {error.code}：{detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接云端偏好服务：{error.reason}") from error
    except http.client.HTTPException as error:
        raise RuntimeError(f"偏好服务响应读取失败：{error}") from error


def cloud_config(args) -> tuple[str, str]:
    endpoint = (args.endpoint or os.environ.get("GONGCHUANG_KB_ENDPOINT", "")).strip()
    token = (args.token or os.environ.get("GONGCHUANG_KB_TOKEN", "")).strip()
    if not endpoint or not token:
        raise ValueError("缺少GONGCHUANG_KB_ENDPOINT或GONGCHUANG_KB_TOKEN")
    return endpoint, token


def local_from_remote(remote: dict[str, object]) -> dict[str, object]:
    preferences = deepcopy(remote.get("preferences", {}))
    return {
        "schema_version": remote.get("schema_version", 1),
        "revision": remote.get("revision", 0),
        "preferences": preferences,
        "_meta": {
            "dirty": False,
            "synced_at": now_iso(),
            "base_revision": remote.get("revision", 0),
            "base_preferences": deepcopy(preferences),
        },
    }


def merge_three_way(base, local, remote, path=()):
    def clone(value):
        return MISSING if value is MISSING else deepcopy(value)

    def same(left, right):
        if left is MISSING or right is MISSING:
            return left is right
        return canonical_json(left) == canonical_json(right)

    if same(local, remote):
        return clone(local), []
    if same(local, base):
        return clone(remote), []
    if same(remote, base):
        return clone(local), []
    if all(isinstance(value, dict) for value in (base, local, remote)):
        merged = {}
        conflicts = []
        keys = set(base) | set(local) | set(remote)
        for key in sorted(keys):
            base_value = base.get(key, MISSING)
            local_value = local.get(key, MISSING)
            remote_value = remote.get(key, MISSING)
            value, child_conflicts = merge_three_way(base_value, local_value, remote_value, (*path, key))
            if value is not MISSING:
                merged[key] = value
            conflicts.extend(child_conflicts)
        return merged, conflicts
    return clone(local), [
        {
            "path": ".".join(path),
            "base": None if base is MISSING else base,
            "local": None if local is MISSING else local,
            "remote": None if remote is MISSING else remote,
        }
    ]


def command_pull(args) -> int:
    endpoint, token = cloud_config(args)
    remote = request_json("GET", endpoint, token, "/v1/preferences")
    write_local(args.file, local_from_remote(remote))
    print(f"已同步云端偏好R{remote['revision']}：{args.file}")
    return 0


def sync_snapshot(remote):
    if not isinstance(remote, dict) or not isinstance(remote.get("preferences"), dict):
        raise ValueError("偏好服务返回缺少 preferences 对象")
    revision = remote.get("revision")
    if type(revision) is not int or revision < 0:
        raise ValueError("偏好服务返回缺少有效 revision")
    return {"preferences": remote["preferences"], "revision": revision}


def command_push(args) -> int:
    endpoint, token = cloud_config(args)
    local = read_json(args.file)
    if not local:
        raise ValueError("本地偏好文件不存在，请先pull")
    meta = local.get("_meta", {})
    meta = meta if isinstance(meta, dict) else {}
    base = meta.get("base_preferences", {})
    report = {"created_at": now_iso(), "base_revision": meta.get("base_revision", 0)}

    def fail(stage, conflicts):
        conflict_path = args.file.with_name("preference-merge-conflicts.json")
        write_local(conflict_path, {**report, "status": "fail", "stage": stage, "conflicts": conflicts})
        print(f"偏好同步失败（{stage}），原基线已保留：{conflict_path}", file=sys.stderr)
        return 3

    try:
        remote = sync_snapshot(request_json("GET", endpoint, token, "/v1/preferences"))
    except (OSError, ValueError, RuntimeError) as error:
        return fail("read_before_write", [{"reason": str(error)}])
    report["remote_revision"] = remote["revision"]
    local_preferences = local.get("preferences", {})
    merged, conflicts = merge_three_way(base, local_preferences, remote["preferences"])
    if conflicts:
        return fail("merge", conflicts)

    expected_revision = remote["revision"] + 1
    expected = {"revision": expected_revision, "preferences": deepcopy(merged)}
    report.update(expected_revision=expected_revision, actual_revision=None)
    try:
        request_json(
            "PUT", endpoint, token, "/v1/preferences",
            {
                "preferences": merged,
                "base_revision": remote["revision"],
                "change_summary": args.summary,
            },
        )
    except (OSError, ValueError, RuntimeError) as error:
        return fail("write", [{"reason": str(error)}])

    try:
        readback = request_json("GET", endpoint, token, "/v1/preferences")
    except (OSError, ValueError, RuntimeError) as error:
        return fail("readback", [{"reason": str(error)}])
    if not isinstance(readback, dict):
        return fail("readback", [{"reason": "偏好服务回读须为 JSON 对象"}])

    actual = {field: readback[field] for field in expected if field in readback}
    report["actual_revision"] = actual.get("revision")
    conflicts = differences(expected, actual)
    try:
        saved = sync_snapshot(readback)
    except ValueError:
        # JSON 数值相等时，仍须拒绝非整数类型的 revision。
        if (
            "revision" in actual
            and type(actual["revision"]) is not int
            and not any(change["path"] == "/revision" for change in conflicts)
        ):
            conflicts.append({
                "path": "/revision", "kind": "mismatch",
                "expected": expected_revision, "actual": actual["revision"],
                "reason": "revision 须为非负整数",
            })
        return fail("readback", conflicts)
    if conflicts:
        return fail("verify", conflicts)

    write_local(args.file, local_from_remote(readback))
    print(f"偏好已写入并回读核对通过 R{saved['revision']}")
    return 0


def command_sync(args) -> int:
    local = read_json(args.file)
    meta = local.get("_meta", {}) if local else {}
    if local and isinstance(meta, dict) and meta.get("dirty"):
        return command_push(args)
    return command_pull(args)


def command_show(args) -> int:
    payload = read_json(args.file)
    print(canonical_json(payload))
    return 0


def command_set(args) -> int:
    payload = read_json(args.file)
    if not payload:
        payload = {"schema_version": 1, "revision": 0, "preferences": {}, "_meta": {}}
    preferences = payload.setdefault("preferences", {})
    if not isinstance(preferences, dict):
        raise ValueError("本地preferences必须是对象")
    keys = [part for part in args.path.split(".") if part]
    if not keys:
        raise ValueError("偏好路径不能为空")
    cursor = preferences
    for key in keys[:-1]:
        child = cursor.setdefault(key, {})
        if not isinstance(child, dict):
            raise ValueError(f"偏好路径不是对象：{key}")
        cursor = child
    try:
        value = loads(args.value)
    except json.JSONDecodeError:
        value = args.value
    cursor[keys[-1]] = value
    meta = payload.setdefault("_meta", {})
    if isinstance(meta, dict):
        meta["dirty"] = True
        meta["changed_at"] = now_iso()
    write_local(args.file, payload)
    print(f"已写入本地偏好：{args.path}")
    if args.sync:
        return command_push(args)
    return 0


def command_remote_action(args, route: str, label: str) -> int:
    endpoint, token = cloud_config(args)
    updated = request_json("POST", endpoint, token, route)
    write_local(args.file, local_from_remote(updated))
    print(f"{label}，当前云端偏好R{updated['revision']}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("--file", type=Path, default=DEFAULT_PATH)
    root.add_argument("--endpoint", default="")
    root.add_argument("--token", default="")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("pull")
    push = commands.add_parser("push")
    push.add_argument("--summary", default="本地个人偏好同步")
    sync = commands.add_parser("sync")
    sync.add_argument("--summary", default="跨设备三方合并")
    commands.add_parser("show")
    set_command = commands.add_parser("set")
    set_command.add_argument("path")
    set_command.add_argument("value")
    set_command.add_argument("--sync", action="store_true")
    set_command.add_argument("--summary", default="对话调校个人偏好")
    commands.add_parser("undo")
    commands.add_parser("reset")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "pull":
            return command_pull(args)
        if args.command == "push":
            return command_push(args)
        if args.command == "sync":
            return command_sync(args)
        if args.command == "show":
            return command_show(args)
        if args.command == "set":
            return command_set(args)
        if args.command == "undo":
            return command_remote_action(args, "/v1/preferences/undo", "已撤销上一版")
        return command_remote_action(args, "/v1/preferences/reset", "已恢复官方默认")
    except (ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

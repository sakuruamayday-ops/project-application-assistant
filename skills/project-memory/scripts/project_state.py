#!/usr/bin/env python3
"""校验或读取外置项目状态，不把客户数据写入技能目录。"""

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_runtime"))
from result_digest import canonical_json, loads
from sync_fields import differences

REQUIRED = {"identity", "policy", "facts", "decisions", "pending", "artifacts", "updated_at"}
SYNC_METADATA = {"identity", "version"}


def validate(value):
    errors = [f"缺少字段:{key}" for key in sorted(REQUIRED - set(value))]
    try:
        datetime.fromisoformat(str(value.get("updated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("updated_at不是ISO日期时间")
    return errors


def prepare_sync(local_state, fields):
    if not isinstance(local_state, dict):
        raise ValueError("项目状态须为 JSON 对象")
    if not fields or len(fields) != len(set(fields)) or SYNC_METADATA.intersection(fields):
        raise ValueError("请指定唯一的已授权内容字段，identity 和 version 单独核对")
    missing = (set(fields) | SYNC_METADATA) - local_state.keys()
    if missing:
        raise ValueError("写入前状态缺字段：" + "、".join(sorted(missing)))
    identity = local_state["identity"]
    version = local_state["version"]
    if not isinstance(identity, (dict, str)) or not identity or (isinstance(identity, str) and not identity.strip()):
        raise ValueError("identity 须为非空的项目主体")
    if type(version) is not int and (not isinstance(version, str) or not version.strip()):
        raise ValueError("version 须为整数或非空字符串")
    content = {field: deepcopy(local_state[field]) for field in sorted(fields)}
    return {
        "status": "prepared",
        "identity": deepcopy(identity),
        "version": version,
        "fields": sorted(fields),
        "local_state": content,
    }


def verify_sync(prepared, readback, operations=None, readback_error=None):
    expected = prepared["local_state"]
    fields = prepared["fields"]
    expected_metadata = {key: prepared[key] for key in SYNC_METADATA}
    if not isinstance(expected, dict) or set(fields) != expected.keys():
        raise ValueError("写入前快照与字段清单不一致")
    operations = [] if operations is None else operations
    if not isinstance(operations, list):
        raise ValueError("已发生操作须为 JSON 数组")
    target = None
    if isinstance(readback, dict) and readback_error is None:
        actual = {field: readback[field] for field in fields if field in readback}
        actual_metadata = {key: readback[key] for key in SYNC_METADATA if key in readback}
        target = {**actual_metadata, **actual}
        changes = differences(expected_metadata, actual_metadata) + differences(expected, actual)
    else:
        changes = [{"path": "", "kind": "readback_failed", "actual": readback_error or "目标回读须为 JSON 对象"}]
    return {
        "status": "fail" if changes else "pass",
        **expected_metadata,
        "fields": fields,
        "local_state": expected,
        "target_readback": target,
        "differences": changes,
        "operations": operations,
    }


def read_sync_json(path):
    return loads(Path(path).expanduser().read_text(encoding="utf-8"))


def sync_receipt(args, path):
    value = read_sync_json(path)
    if args.command == "prepare-sync":
        return prepare_sync(value, args.fields)
    operations = read_sync_json(args.operations) if args.operations else None
    try:
        readback = read_sync_json(args.readback) if args.readback else None
    except (OSError, ValueError) as error:
        return verify_sync(value, None, operations, str(error))
    return verify_sync(value, readback, operations, args.readback_error)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "get", "prepare-sync", "verify-sync"))
    parser.add_argument("state_file")
    parser.add_argument("--fields", nargs="+", help="写入前用户授权的内容字段")
    parser.add_argument("--readback", help="写入后宿主重新读取的目标状态 JSON")
    parser.add_argument("--readback-error", help="宿主回读失败原因")
    parser.add_argument("--operations", help="宿主已发生操作的 JSON 数组文件")
    args = parser.parse_args()
    path = Path(args.state_file).expanduser()
    if args.command in {"prepare-sync", "verify-sync"}:
        try:
            result = sync_receipt(args, path)
            print(canonical_json(result))
        except (OSError, ValueError, KeyError, TypeError) as error:
            result = {"status": "fail", "errors": [str(error)]}
            print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(2 if result["status"] == "fail" else 0)
    value = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(value)
    result = {"status": "pass" if not errors else "fail", "errors": errors}
    if args.command == "get" and not errors:
        result["state"] = value
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 2)


if __name__ == "__main__":
    main()

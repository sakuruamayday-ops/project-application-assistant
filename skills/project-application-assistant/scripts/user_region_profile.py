#!/usr/bin/env python3
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


HANGZHOU_DISTRICTS = {
    "余杭区",
    "临平区",
    "西湖区",
    "萧山区",
    "钱塘区",
    "拱墅区",
    "滨江区",
    "上城区",
    "临安区",
    "富阳区",
    "建德市",
    "桐庐县",
    "淳安县",
}


def profile_path():
    configured = os.environ.get("PROJECT_APPLICATION_ASSISTANT_PROFILE")
    return Path(configured).expanduser() if configured else Path.home() / ".project-application-assistant" / "profile.json"


def normalize_region(value):
    return re.sub(r"\s+", "", value.strip())


def region_parts(value):
    return list(
        dict.fromkeys(
            re.findall(r"[^省市区县]{2,12}(?:自治区|省|市|区|县)", normalize_region(value))
        )
    )


def default_region(value):
    parts = region_parts(value)
    province = next((part for part in parts if part.endswith(("省", "自治区"))), None)
    city = next((part for part in parts if part.endswith("市")), None)
    selected = [part for part in (province, city) if part]
    return "".join(selected) or normalize_region(value)


def region_scope(value):
    value = normalize_region(value)
    parts = region_parts(value)
    scope = []
    for part in reversed(parts):
        if part not in scope:
            scope.append(part)
    district = next((part for part in scope if part in HANGZHOU_DISTRICTS), None)
    if district:
        for parent in ("杭州市", "浙江省"):
            if parent not in scope:
                scope.append(parent)
    if value in HANGZHOU_DISTRICTS:
        scope = [value, "杭州市", "浙江省"]
    if "全国" not in scope:
        scope.append("全国")
    return scope


def load_profile(path):
    if not path.exists():
        return {"configured": False}
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["configured"] = True
    return profile


def save_profile(path, region):
    normalized = default_region(region)
    profile = {
        "default_region": normalized,
        "scope": region_scope(normalized),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return profile


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("get")
    setter = subparsers.add_parser("set")
    setter.add_argument("region")
    subparsers.add_parser("clear")
    scope_parser = subparsers.add_parser("scope")
    scope_parser.add_argument("region", nargs="?")
    args = parser.parse_args()
    path = profile_path()
    if args.command == "get":
        result = load_profile(path)
    elif args.command == "set":
        result = save_profile(path, args.region)
    elif args.command == "clear":
        path.unlink(missing_ok=True)
        result = {"configured": False}
    else:
        region = args.region or load_profile(path).get("default_region", "")
        result = {"region": region, "scope": region_scope(region) if region else []}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def request_json(
    url: str,
    token: str,
    device_id: str,
    device_name: str,
    payload: dict[str, object] | None = None,
) -> object:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Jiaotang-Device-ID": device_id,
            "X-Jiaotang-Device-Name": (
                device_name.encode("ascii", errors="ignore").decode("ascii").strip()
                or "Project Assistant"
            ),
            "Content-Type": "application/json",
        },
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="检索团队云端法律法规底库")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    endpoint = os.environ.get("JIAOTANG_KB_ENDPOINT", "").strip().rstrip("/")
    token = os.environ.get("JIAOTANG_KB_TOKEN", "").strip()
    device_id = os.environ.get("JIAOTANG_KB_DEVICE_ID", "").strip()
    device_name = os.environ.get("JIAOTANG_KB_DEVICE_NAME", "").strip()
    if not endpoint or not token or not device_id:
        print(
            json.dumps(
                {
                    "status": "unconfigured",
                    "detail": "团队知识服务地址、个人Token或设备标识未配置",
                },
                ensure_ascii=False,
            )
        )
        return 3
    try:
        identity = request_json(f"{endpoint}/v1/me", token, device_id, device_name)
        results = request_json(
            f"{endpoint}/v1/search",
            token,
            device_id,
            device_name,
            {"query": args.query, "limit": max(1, min(args.limit, 20))},
        )
    except urllib.error.HTTPError as error:
        print(json.dumps({"status": "http_error", "code": error.code}, ensure_ascii=False))
        return 4
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "unavailable", "detail": str(error)}, ensure_ascii=False))
        return 5
    print(json.dumps({"identity": identity, "search": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

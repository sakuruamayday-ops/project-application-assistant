#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import json
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request


CSRF_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')
TOKEN_PATTERN = re.compile(r"jtk_[A-Za-z0-9_-]+")
CHINESE_DIGITS = str.maketrans("0123456789", "零一二三四五六七八九")


def browser_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def form_request(opener, url: str, fields: dict[str, str]) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def provision_token(base_url: str, username: str, real_name: str, password: str, company: str) -> str:
    opener = browser_opener()
    form_request(
        opener,
        f"{base_url}/register",
        {
            "username": username,
            "company_name": company,
            "password": password,
            "confirm_password": password,
        },
    )
    status, login_html = form_request(
        opener,
        f"{base_url}/login",
        {"username": username, "password": password},
    )
    if status != 200:
        raise RuntimeError(f"{username} 登录失败：HTTP {status}")
    csrf_match = CSRF_PATTERN.search(login_html)
    if not csrf_match:
        raise RuntimeError(f"{username} 未找到 CSRF Token")
    status, token_html = form_request(
        opener,
        f"{base_url}/device-tokens",
        {
            "real_name": real_name,
            "company_name": company,
            "csrf_token": csrf_match.group(1),
        },
    )
    token_match = TOKEN_PATTERN.search(token_html)
    if status != 200 or not token_match:
        raise RuntimeError(f"{username} 创建用户凭据失败：HTTP {status}")
    return token_match.group(0)


def search_once(base_url: str, token: str, query: str) -> tuple[float, int, str]:
    body = json.dumps({"query": query, "limit": 8}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/v1/search",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return time.perf_counter() - started, response.status, str(len(payload["results"]))
    except Exception as error:
        return time.perf_counter() - started, 0, f"{type(error).__name__}: {error}"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="项目申报助手 50 用户端到端并发测试")
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--requests-per-user", type=int, default=2)
    parser.add_argument("--company", default="共创集团")
    parser.add_argument("--query", default="小巨人 产业链")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    run_id = int(time.time())
    password = f"Load-test-{run_id}-Password!"

    tokens = []
    for index in range(args.users):
        username = f"load{run_id}{index + 1:03d}"
        real_name = f"压测第{index + 1}位".translate(CHINESE_DIGITS)
        tokens.append(provision_token(base_url, username, real_name, password, args.company))

    jobs = [token for token in tokens for _ in range(args.requests_per_user)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as executor:
        results = list(executor.map(lambda token: search_once(base_url, token, args.query), jobs))
    elapsed = time.perf_counter() - started

    durations = [duration for duration, _, _ in results]
    failures = [(status, detail) for _, status, detail in results if status != 200]
    report = {
        "base_url": base_url,
        "users": args.users,
        "requests": len(results),
        "failures": len(failures),
        "elapsed_seconds": round(elapsed, 3),
        "requests_per_second": round(len(results) / elapsed, 2),
        "latency_ms": {
            "mean": round(statistics.mean(durations) * 1000, 2),
            "p50": round(percentile(durations, 0.50) * 1000, 2),
            "p95": round(percentile(durations, 0.95) * 1000, 2),
            "max": round(max(durations) * 1000, 2),
        },
        "failure_samples": failures[:5],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

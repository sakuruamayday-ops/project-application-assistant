#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://aiqice.cn"
PROJECTS = {
    "10": "浙江省首版次软件产品",
    "11": "浙江省首批次新材料",
    "12": "浙江省制造业首台（套）装备",
}
PROVINCE_LIST_PATTERNS = {
    "10": re.compile(r"浙江省.*首版次软件产品.*(?:目录|名单|公示|通知)"),
    "11": re.compile(r"浙江省.*(?:首批次新材料|重点新材料首批次).*(?:目录|名单|公示|认定|通知)"),
    "12": re.compile(r"浙江省.*首台.?套.*装备.*(?:名单|公示|认定|通知)"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从企策顾问展开三首项目历年产品级公示名单")
    parser.add_argument("--output", type=Path, default=Path.home() / "Downloads" / "qice_three_first_product_details.json")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--delay", type=float, default=1.2)
    return parser.parse_args()


def signed_headers(token: str) -> tuple[dict[str, str], int]:
    timestamp = int(time.time() * 1000)
    sign = hashlib.sha256(f"F%+@+==-2fe^$%&@%timestamp={timestamp}".encode("utf-8")).hexdigest()
    return {
        "Authorization": "",
        "Content-Type": "application/json;charset=UTF-8",
        "token": token,
        "timestamp": str(timestamp),
        "sign": sign,
        "User-Agent": "JiaotangKnowledgeCollector/1.0",
    }, timestamp


def post(session: requests.Session, token: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers, timestamp = signed_headers(token)
    response = session.post(f"{BASE_URL}{endpoint}?timestamp={timestamp}", headers=headers, json={**payload, "timestamp": timestamp}, timeout=60)
    response.raise_for_status()
    result = response.json()
    if result.get("code") != "000000":
        raise RuntimeError(f"企策接口失败：{endpoint} code={result.get('code')} mesg={result.get('mesg')}")
    return result


def get(session: requests.Session, token: str, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    headers, timestamp = signed_headers(token)
    response = session.get(f"{BASE_URL}{endpoint}", headers=headers, params={**params, "timestamp": timestamp}, timeout=60)
    response.raise_for_status()
    result = response.json()
    if result.get("code") != "000000":
        raise RuntimeError(f"企策接口失败：{endpoint} code={result.get('code')} mesg={result.get('mesg')}")
    return result


def related_policies(session: requests.Session, token: str, project_id: str) -> list[dict[str, Any]]:
    result = post(session, token, "/data-api/mobile/policyProject/v2/pageRelatedPolicyLastUpdate", {"projectId": project_id, "current": 1, "size": 200})
    return list(result.get("data", {}).get("records") or [])


def include_policy(project_id: str, policy: dict[str, Any]) -> bool:
    title = str(policy.get("title") or "")
    area = str(policy.get("areaName") or "")
    if area != "浙江省":
        return False
    if int(policy.get("policyType") or 0) != 3:
        return False
    if any(term in title for term in ("奖励", "保险", "补偿", "攻关", "征集", "申报")):
        return False
    return bool(PROVINCE_LIST_PATTERNS[project_id].search(title))


def publicity_rows(session: requests.Session, token: str, index_id: str, page_size: int) -> dict[str, Any]:
    payload = {
        "orderFirstEids": [],
        "indexId": index_id,
        "parkIds": [],
        "isInCustomPark": False,
        "size": page_size,
        "current": 1,
        "entName": "",
        "projectName": "",
        "projectNames": [],
        "areaList": [],
        "industryList": [],
        "assessYears": [],
    }
    first = post(session, token, "/data-api/mobile/policy/publicityPage", payload).get("data", {})
    records = list(first.get("records") or [])
    pages = int(first.get("pages") or 1)
    for current in range(2, pages + 1):
        payload["current"] = current
        page = post(session, token, "/data-api/mobile/policy/publicityPage", payload).get("data", {})
        records.extend(page.get("records") or [])
        time.sleep(0.6)
    return {"records": records, "total": int(first.get("total") or len(records)), "pages": pages}


def main() -> None:
    args = parse_args()
    token = os.environ.get("QICE_TOKEN", "").strip()
    if not token:
        raise SystemExit("请在安全环境变量 QICE_TOKEN 中提供企策登录凭据；脚本不会把凭据写入文件或日志。")
    session = requests.Session()
    projects: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for project_id, project_name in PROJECTS.items():
        policies = related_policies(session, token, project_id)
        selected = [policy for policy in policies if include_policy(project_id, policy)]
        collected: list[dict[str, Any]] = []
        for policy in selected:
            try:
                detail = get(session, token, "/data-api/mobile/policy/detail", {"id": policy["id"], "indexId": policy["indexId"], "aesStatus": 1}).get("data", {})
                rows = publicity_rows(session, token, str(policy["indexId"]), args.page_size)
                collected.append({"policy": {**policy, **{key: detail.get(key) for key in ("originalLink", "publishDept", "sourceName", "levelName")}}, **rows})
            except Exception as exc:
                failures.append({"projectId": project_id, "policyId": str(policy.get("id")), "title": str(policy.get("title")), "error": str(exc)})
            time.sleep(args.delay)
        projects.append({"projectId": project_id, "projectName": project_name, "relatedPolicyCount": len(policies), "selectedPolicyCount": len(selected), "policies": collected})
    output = {
        "schema_version": 1,
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "projects": projects,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"projects": len(projects), "policies": sum(len(item["policies"]) for item in projects), "failures": len(failures), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

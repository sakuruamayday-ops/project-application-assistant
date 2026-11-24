#!/usr/bin/env python3
"""核对管理办法的官方文号、来源、正文与长期适用附件。"""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from policy_content import attachment_differences, body_differences, read_policy_text



def present(value):
    return isinstance(value, str) and bool(value.strip())


def read_original(root, value):
    if not present(value):
        raise ValueError("缺原件路径")
    return read_policy_text(root / value)


def validate_chain(payload, root):
    items = []

    def add(title, gap, action, priority="高"):
        items.append({"item": title, "gap": gap, "action": action, "priority": priority})

    if not isinstance(payload, dict):
        payload = {}
    region = payload.get("region")
    if not present(region) or not present(payload.get("project")):
        add("项目定位", "缺项目全称或属地", "核对企业目标项目及适用地区")
    documents = payload.get("documents")
    record = documents.get("management") if isinstance(documents, dict) else None
    item = "管理办法"
    if not isinstance(record, dict):
        add(item, "缺政策记录", "取得发文机关正式正文及随文附件")
    else:
        locator = record.get("official_url")
        official = urlsplit(locator) if present(locator) else None
        hostname = official.hostname if official else None
        if (not all(present(record.get(key)) for key in ("title", "issuer", "number"))
                or not hostname or not hostname.endswith(".gov.cn")
                or official.scheme not in ("http", "https")):
            add(item, "缺标题、发文机关、官方域名或正文文号", "填写已经核对的官方原文链接及文号")
        if record.get("status") != "current" or record.get("region") not in (region, "全国"):
            add(item, "未确认适用状态或属地", "区分现行、历史及异地政策并核对替代关系")
        body = ""
        try:
            body = read_original(root, record.get("body"))
        except ValueError as error:
            add(item + "正文", str(error), "取得全文并登记本地原件位置")
        else:
            for difference in body_differences(body, record, root):
                add(item + "正文", difference, "按发文原件核对政策名称、文号及关键条款")
        attachments = record.get("attachments", [])
        expected = record.get("attachments_expected", 0)
        if type(expected) is not int or expected < 0 or not isinstance(attachments, list) or len(attachments) != expected:
            add(item + "附件", "附件清单与原文列项数不一致", "按管理办法所列附件登记原件")
        for index, attachment in enumerate(attachments if isinstance(attachments, list) else [], 1):
            label = f"{item}附件 {index}"
            try:
                if not isinstance(attachment, dict) or not present(attachment.get("title")):
                    raise ValueError("附件登记缺标题")
                annex = read_original(root, attachment.get("path"))
            except ValueError as error:
                add(label, str(error), "取得并核对对应附件的名称及原件")
                continue
            for difference in attachment_differences(annex, attachment, body, record):
                add(label, difference, "按正文所列名称、文号及条款核对随文附件")
    return {"status": "incomplete" if items else "complete", "project": payload.get("project"),
            "year": payload.get("year"), "region": region,
            "documents": {"management": record} if isinstance(record, dict) else {}, "items": items}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.record.read_text(encoding="utf-8"))
        report = validate_chain(payload, args.record.resolve().parent)
    except (OSError, ValueError) as error:
        report = {"status": "incomplete", "items": [
            {"item": "政策记录文件", "gap": str(error), "action": "核对文件位置及 JSON 格式", "priority": "高"}
        ]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())

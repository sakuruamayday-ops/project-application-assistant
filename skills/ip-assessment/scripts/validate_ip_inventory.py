#!/usr/bin/env python3
"""校验知识产权清单的主体、状态和关联字段。"""

import argparse
from datetime import date
import json
from pathlib import Path
import unicodedata


REQUIRED = ("id", "type", "title", "owner", "status", "cutoff_date", "acquisition", "product_link")
EFFECTIVE = {
    "active", "effective", "valid", "granted-active", "granted-effective", "granted-valid",
    "有效", "授权有效", "有效授权", "已授权有效",
}


def normalized(value):
    if value is None or isinstance(value, bool):
        return ""
    return "".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()


def validate(items, registry=None):
    findings = []

    def finding(field, gap, action):
        findings.append({"item": field, "gap": gap, "action": action, "priority": "高"})

    if not isinstance(items, list) or not items:
        finding("清单", "未提供知识产权清单", "按权利项逐行填写，提供非空的 UTF-8 JSON 数组")
        return findings

    snapshots = {}
    if registry is not None:
        if not isinstance(registry, list) or not registry:
            finding("基准日登记", "登记快照须为非空数组", "提供同一基准日的官方登记记录")
            registry = []
        for record in registry:
            ref = normalized(record.get("id")) if isinstance(record, dict) else ""
            if not ref or ref in snapshots:
                finding("基准日登记", "登记凭证编号缺失或重复", "核对登记快照凭证编号")
                continue
            snapshots[ref] = record

    seen_ids = {}
    seen_rights = {}
    for index, item in enumerate(items, 1):
        label = f"第 {index} 条"
        if not isinstance(item, dict):
            finding(label, "该条权利记录格式错误", "填写一项包含编号、权利人、状态及关联的对象")
            continue
        for field in REQUIRED:
            value = item.get(field)
            if value is None or isinstance(value, bool) or not str(value).strip() or value in ([], {}):
                finding(f"{label} / {field}", "字段为空", "按现有权利资料补齐本字段")
        inventory_id = normalized(item.get("id"))
        right_number = normalized(item.get("number"))
        owner = normalized(item.get("owner"))
        prior_owners = []
        if inventory_id:
            previous = seen_ids.setdefault(inventory_id, (index, owner))
            if previous[0] != index:
                finding(f"{label} / id", f"清单编号重复 {item['id']}，已见第 {previous[0]} 条",
                        "按权利归并清单记录")
                prior_owners.append(previous)
        if right_number:
            previous = seen_rights.setdefault(right_number, (index, owner))
            if previous[0] != index:
                finding(f"{label} / number", f"权利编号重复 {item['number']}，已见第 {previous[0]} 条",
                        "按权利编号归并清单记录")
                prior_owners.append(previous)
        for prior_index, prior_owner in dict.fromkeys(prior_owners):
            if owner and prior_owner and owner != prior_owner:
                finding(f"{label} / owner", f"权利人冲突，与第 {prior_index} 条不一致",
                        "核对同一权利的现时登记及变更文件")
        current_owners = [item.get("registry_owner")]
        if registry is not None:
            snapshot = snapshots.get(normalized(item.get("registry_evidence")))
            if (snapshot is None or normalized(snapshot.get("right_id")) != inventory_id
                    or not right_number or normalized(snapshot.get("number")) != right_number
                    or snapshot.get("snapshot") != item.get("cutoff_date") or not normalized(snapshot.get("owner"))):
                finding(f"{label} / registry_evidence", "缺同一权利、同一基准日的登记关联",
                        "按权利编号与核验基准日回链登记凭证")
            else:
                current_owners.append(snapshot["owner"])
        if owner and any(normalized(name) not in ("", owner) for name in current_owners):
            finding(f"{label} / owner", "权利人冲突，清册与基准日登记不一致",
                    "核对当前登记及权属变更文件，冲突项暂停计入")
        cutoff = item.get("cutoff_date")
        if cutoff:
            try:
                parsed = date.fromisoformat(cutoff)
                if parsed.isoformat() != cutoff:
                    raise ValueError(cutoff)
            except (TypeError, ValueError):
                finding(f"{label} / cutoff_date", "日期无效", "按核验记录填写 YYYY-MM-DD")
        usable = item.get("usable_as_granted")
        if usable is not None and type(usable) is not bool:
            finding(f"{label} / usable_as_granted", "标记须为布尔值", "按该权利的当前有效状态填写 true 或 false")
        if usable is True:
            status = str(item.get("status", "")).strip().lower().replace("_", "-")
            effective_grant = status in EFFECTIVE or (status == "granted" and item.get("effective") is True)
            if not effective_grant or item.get("effective") is False:
                finding(f"{label} / status", "未证实为有效授权，当前标记为可用",
                        "核对基准日官方状态，按其实际状态分类")
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--registry", type=Path, help="独立的基准日登记快照 JSON")
    args = parser.parse_args()
    try:
        content = args.inventory.read_text(encoding="utf-8-sig").strip()
        registry = json.loads(args.registry.read_text(encoding="utf-8-sig")) if args.registry else None
        findings = validate(json.loads(content) if content else [], registry)
    except (OSError, ValueError) as error:
        findings = [{"item": "清单文件", "gap": f"未提供知识产权清单：{error}",
                     "action": "检查文件位置并提供含数据行的 UTF-8 JSON 数组", "priority": "高"}]
    errors = [f"{item['item']}：{item['gap']}" for item in findings]
    print(json.dumps({"status": "fail" if findings else "pass", "errors": errors, "items": findings},
                     ensure_ascii=False, indent=2))
    return 2 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

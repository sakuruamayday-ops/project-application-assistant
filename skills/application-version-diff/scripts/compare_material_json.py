#!/usr/bin/env python3
"""比较两个已结构化为键值对象的材料JSON。"""

import argparse
import json
from pathlib import Path


def flatten(value, prefix=""):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result.update(flatten(child, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.update(flatten(child, f"{prefix}[{index}]"))
    else:
        result[prefix] = value
    return result


def compare_fields(old, new, path="", old_path=None):
    old = flatten(old, path)
    new = flatten(new, path)
    changes = []
    for key in sorted(set(old) | set(new)):
        if key not in old:
            changes.append({"path": key, "kind": "added", "new": new[key]})
        elif key not in new:
            changes.append({"path": key, "kind": "deleted", "old": old[key]})
        elif old[key] != new[key]:
            changes.append({"path": key, "kind": "modified", "old": old[key], "new": new[key]})
    if old_path is not None and old_path != path:
        for change in changes:
            key = change["path"]
            if change["kind"] != "added":
                change["old_path"] = old_path + key[len(path):]
            if change["kind"] == "deleted":
                change["path"] = change["old_path"]
    return changes


def index_sections(sections):
    if not isinstance(sections, list):
        return None
    result = {}
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            return None
        identities = [(field, section.get(field)) for field in ("id", "title")]
        identity = next(
            ((field, value.strip()) for field, value in identities if isinstance(value, str) and value.strip()),
            None,
        )
        if identity is None or identity in result:
            return None
        result[identity] = (index, section)
    return result


def compare_materials(old, new):
    if not isinstance(old, dict) or not isinstance(new, dict):
        return compare_fields(old, new)
    old_sections = index_sections(old.get("sections"))
    new_sections = index_sections(new.get("sections"))
    if old_sections is None or new_sections is None:
        return compare_fields(old, new)

    changes = compare_fields({k: v for k, v in old.items() if k != "sections"},
                             {k: v for k, v in new.items() if k != "sections"})
    old_order = [identity for identity in old_sections if identity in new_sections]
    new_order = [identity for identity in new_sections if identity in old_sections]
    moved = {after for before, after in zip(old_order, new_order) if before != after}

    for identity, (index, section) in new_sections.items():
        path = f"sections[{index}]"
        if identity not in old_sections:
            changes.extend(compare_fields({}, section, path))
            continue
        previous_index, previous_section = old_sections[identity]
        previous_path = f"sections[{previous_index}]"
        if identity in moved:
            changes.append({"path": path, "kind": "moved", "old_path": previous_path,
                            "new_path": path, "section": section.get("title") or identity[1]})
        changes.extend(compare_fields(previous_section, section, path, previous_path))
    for identity, (index, section) in old_sections.items():
        if identity not in new_sections:
            changes.extend(compare_fields(section, {}, f"sections[{index}]"))
    return changes


def read_material(path):
    material = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if material is None or isinstance(material, str) and not material.strip() or not flatten(material):
        raise ValueError(f"材料没有可比较的内容：{Path(path).name}")
    return material


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old")
    parser.add_argument("new")
    args = parser.parse_args()
    try:
        old = read_material(args.old)
        new = read_material(args.new)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    changes = compare_materials(old, new)
    print(json.dumps({"status": "pass", "change_count": len(changes), "changes": changes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

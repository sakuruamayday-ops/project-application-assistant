#!/usr/bin/env python3
"""Select and copy a governed project report DOCX master."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "report-template-registry.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"[\s“”‘’「」『』()（）\-_—]+", "", value).casefold()


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("projects"), list):
        raise ValueError("模板索引格式无效")
    return value


def _select_by_alias(
    query: str,
    records: list[dict[str, Any]],
    *,
    id_key: str = "id",
    label_key: str = "label",
) -> dict[str, Any]:
    folded = normalize(query)
    if not folded:
        raise ValueError("选型条件不得为空")
    exact: list[dict[str, Any]] = []
    contained: list[tuple[int, dict[str, Any], str]] = []
    for record in records:
        names = [str(record.get(id_key) or ""), str(record.get(label_key) or "")]
        names.extend(str(item) for item in record.get("aliases", []))
        normalized = [normalize(item) for item in names if normalize(item)]
        if folded in normalized:
            exact.append(record)
            continue
        for alias in normalized:
            if alias in folded:
                contained.append((len(alias), record, alias))
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"选型冲突:{query}")
    if not contained:
        raise ValueError(f"未命中受控模板:{query}")
    longest = max(item[0] for item in contained)
    winners = {str(item[1].get(id_key)): item[1] for item in contained if item[0] == longest}
    if len(winners) != 1:
        raise ValueError(f"选型冲突:{query}")
    return next(iter(winners.values()))


def resolve_template(
    project_type: str,
    report_type: str,
    *,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    project = _select_by_alias(project_type, registry["projects"])
    report_records = [
        {"id": key, **value}
        for key, value in registry.get("report_types", {}).items()
        if isinstance(value, dict)
    ]
    report = _select_by_alias(report_type, report_records)
    report_id = str(report["id"])
    template = project.get("templates", {}).get(report_id)
    if not isinstance(template, dict):
        raise ValueError(f"项目未配置该报告模板:{project.get('id')}/{report_id}")
    skill_root = registry_path.resolve().parents[1]
    source = (skill_root / str(template.get("path") or "")).resolve()
    try:
        source.relative_to(skill_root)
    except ValueError as exc:
        raise ValueError("模板路径超出Skill边界") from exc
    if not source.is_file():
        raise FileNotFoundError(source)
    expected = str(template.get("sha256") or "").lower()
    actual = sha256_file(source)
    if len(expected) != 64 or actual != expected:
        raise ValueError(f"模板哈希不一致:{source}")
    return {
        "release_tag": registry.get("release_tag"),
        "project_id": project.get("id"),
        "project_label": project.get("label"),
        "core_object": project.get("core_object"),
        "report_type": report_id,
        "report_label": report.get("label"),
        "profile_id": report.get("profile_id"),
        "template_path": str(source),
        "template_sha256": actual,
    }


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", value).strip(" ._")
    return cleaned or "项目报告"


def materialize(
    selection: dict[str, Any],
    output_dir: Path,
    *,
    enterprise: str = "",
    output_name: str = "",
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_name:
        filename = safe_filename(output_name)
        if not filename.casefold().endswith(".docx"):
            filename += ".docx"
    else:
        prefix = f"{enterprise}_" if enterprise.strip() else ""
        filename = safe_filename(
            f"{prefix}{selection['project_label']}_{selection['report_label']}"
        ) + ".docx"
    target = output_dir / filename
    if target.exists():
        raise FileExistsError(f"拒绝覆盖现有文件:{target}")
    shutil.copy2(selection["template_path"], target)
    target_hash = sha256_file(target)
    if target_hash != selection["template_sha256"]:
        raise RuntimeError("模板复制后哈希不一致")
    receipt = {
        "schema": "gongchuang-project-report-template-selection/v1",
        **selection,
        "output_path": str(target),
        "output_sha256": target_hash,
        "editable": True,
        "next_gate": "回填企业和当期政策事实后导出PDF，再运行报告画像校验",
    }
    sidecar = target.with_suffix(".template-selection.json")
    sidecar.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {**receipt, "receipt_path": str(sidecar)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-type", required=True)
    parser.add_argument("--report-type", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--enterprise", default="")
    parser.add_argument("--output-name", default="")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()
    selection = resolve_template(
        args.project_type,
        args.report_type,
        registry_path=args.registry.expanduser().resolve(),
    )
    if args.output_dir:
        selection = materialize(
            selection,
            args.output_dir,
            enterprise=args.enterprise,
            output_name=args.output_name,
        )
    print(json.dumps(selection, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

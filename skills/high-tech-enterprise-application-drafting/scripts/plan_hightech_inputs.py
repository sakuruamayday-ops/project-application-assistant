#!/usr/bin/env python3
"""Inventory high-tech application inputs once and stop unchanged retry loops."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


SHARED_DETECTOR_DIR = Path(__file__).resolve().parents[2] / "project-application-assistant" / "scripts"
if str(SHARED_DETECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DETECTOR_DIR))

from document_format_detection import detect_document  # noqa: E402

SCHEMA = "gongchuang-hightech-input-plan/v1"
EXTRACTABLE_KINDS = {"docx", "pdf", "xls", "xlsx", "ods", "odt", "rtf", "text"}


def inspect_document(path: Path, role: str) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "role": role}
    if not path.is_file() or path.is_symlink():
        return {
            **record,
            "status": "unavailable",
            "action": "request_source" if role == "essential" else "skip",
            "reason": "输入必须是存在的普通文件",
        }
    stat = path.stat()
    detection = detect_document(path)
    record.update({**detection.to_dict(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    kind = detection.detected_kind
    if kind == "doc":
        return {
            **record,
            "status": "legacy_doc_probe",
            "action": "extract_once_then_convert_if_required",
            "reason": "先调用签名提取器一次；宿主无旧式 DOC 解析能力时再汇总请求转换，不尝试 COM、临时安装解析器或编码猜测",
        }
    if kind in EXTRACTABLE_KINDS:
        return {**record, "status": "supported", "action": "extract_once"}
    if kind in {"encrypted-office", "encrypted-archive"}:
        return {
            **record,
            "status": "encrypted_document",
            "action": "request_password_free_copy" if role == "essential" else "skip",
            "reason": "加密文档不尝试破解或保存密码，请提供无密码副本",
        }
    if kind.startswith("damaged-"):
        return {
            **record,
            "status": "damaged_document",
            "action": "request_valid_source" if role == "essential" else "skip",
            "reason": "文件容器不完整或已损坏，请从原应用重新另存有效副本",
        }
    if kind == "proprietary-office":
        return {
            **record,
            "status": "conversion_required",
            "action": "request_supported_conversion" if role == "essential" else "skip",
            "reason": "WPS 专有格式未识别为兼容 Office 或 ODF 容器，请另存为受支持格式",
        }
    return {
        **record,
        "status": "unsupported_format",
        "action": "request_supported_format" if role == "essential" else "skip",
        "reason": "未识别到可安全读取的 Office、ODF、PDF、RTF 或文本结构",
    }


def fingerprint(records: list[dict[str, object]]) -> str:
    stable = [
        {
            key: record.get(key)
            for key in ("path", "role", "status", "declared_suffix", "detected_kind", "size", "mtime_ns")
        }
        for record in records
    ]
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def load_manifest(path: Path) -> list[tuple[Path, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("输入清单schema_version必须为1")
    raw_documents = data.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValueError("输入清单documents必须为非空数组")
    documents: list[tuple[Path, str]] = []
    for index, item in enumerate(raw_documents):
        if not isinstance(item, dict):
            raise ValueError(f"documents[{index}]必须为对象")
        raw_path = item.get("path")
        role = item.get("role", "supporting")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"documents[{index}].path不能为空")
        if role not in {"essential", "supporting"}:
            raise ValueError(f"documents[{index}].role只能是essential或supporting")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        documents.append((candidate.absolute(), role))
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="含path和essential/supporting角色的JSON输入清单")
    parser.add_argument("--state", type=Path, required=True, help="用于识别同一失败状态的状态文件")
    parser.add_argument("--report", type=Path, required=True, help="本轮能力盘点报告")
    args = parser.parse_args()
    try:
        documents = load_manifest(args.manifest.resolve())
        records = [inspect_document(path, role) for path, role in documents]
        blocked = [
            record
            for record in records
            if record["role"] == "essential" and record["status"] not in {"supported", "legacy_doc_probe"}
        ]
        signature = fingerprint(records)
        previous: dict[str, object] = {}
        if args.state.is_file():
            try:
                loaded = json.loads(args.state.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    previous = loaded
            except (OSError, json.JSONDecodeError):
                previous = {}
        has_legacy_probe = any(record["status"] == "legacy_doc_probe" for record in records)
        repeated_legacy_probe = has_legacy_probe and previous.get("legacy_probe_fingerprint") == signature
        unchanged_failure = (bool(blocked) and previous.get("blocked_fingerprint") == signature) or repeated_legacy_probe
        if unchanged_failure:
            status = "stopped_no_progress"
            message = "必需输入的失败状态与上次相同，已停止重复试错；请转换后再继续"
            exit_code = 3
        elif blocked:
            status = "blocked_conversion_required"
            message = "请一次性补充无密码、未损坏的受支持格式；专有 WPS 文件请从原应用另存"
            exit_code = 2
        else:
            status = "ready_with_skips" if any(record["action"] == "skip" for record in records) else "ready"
            message = "能力盘点完成，可按真实内容类型对每份资料执行一次只读提取"
            exit_code = 0
        state = {
            "schema": SCHEMA,
            "status": status,
            "blocked_fingerprint": signature if blocked else None,
            "legacy_probe_fingerprint": signature if has_legacy_probe else None,
            "unchanged_failure_count": int(previous.get("unchanged_failure_count", 0)) + 1 if unchanged_failure else (1 if blocked else 0),
            "retry_allowed": not unchanged_failure,
        }
        report = {
            "schema": SCHEMA,
            "status": status,
            "message": message,
            "inventory_count": len(records),
            "supported_count": sum(record["status"] in {"supported", "legacy_doc_probe"} for record in records),
            "skipped_count": sum(record["action"] == "skip" for record in records),
            "blocked_count": len(blocked),
            "fingerprint": signature,
            "documents": records,
            "originals_modified": False,
        }
        atomic_json(args.state.resolve(), state)
        atomic_json(args.report.resolve(), report)
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        return exit_code
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "rejected", "error": str(error)}, ensure_ascii=False, separators=(",", ":")))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import certifi


DEFAULT_REGISTRY = Path(
    "/Volumes/知识库/_云端知识库/50_名单与对标/优质中小企业梯度培育/"
    "_全国小巨人批次主表/官方地方分片/official_fragments.json"
)
ALLOWED_HOST_SUFFIXES = (".gov.cn", "miit.gov.cn", "ncsti.gov.cn")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="增量下载已恢复的国家小巨人地方官方分片来源")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-bytes", type=int, default=80 * 1024 * 1024)
    return parser.parse_args()


def safe_part(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip(" .")[:100] or "unknown"


def allowed(url: str) -> bool:
    hostname = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(hostname == suffix.lstrip(".") or hostname.endswith(suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def extension(url: str, content_type: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in {".pdf", ".xls", ".xlsx", ".doc", ".docx", ".zip", ".html", ".htm"}:
        return suffix
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
    return ".html" if guessed in {".htm", ".html"} else guessed


def fetch(url: str, timeout: int, max_bytes: int) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 JiaotangKnowledgeBot/1.0",
            "Accept": "text/html,application/pdf,application/vnd.ms-excel,"
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.8",
        },
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"文件超过限制：{max_bytes} bytes")
    return body, content_type


def main() -> None:
    args = parse_args()
    payload = json.loads(args.registry.read_text(encoding="utf-8"))
    state_path = args.registry.parent / "official_fragment_collection_state.json"
    old_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {"urls": {}}
    state = {"updated_at": "", "urls": dict(old_state.get("urls", {}))}
    results: list[dict[str, object]] = []
    for fragment in payload.get("fragments", []):
        for url in fragment.get("official_urls", []):
            item = {
                "url": str(url),
                "batch": str(fragment.get("batch") or ""),
                "region": str(fragment.get("region") or ""),
                "status": "",
                "local_path": "",
                "sha256": "",
                "error": "",
            }
            if not allowed(str(url)):
                item["status"] = "skipped_non_official_domain"
                results.append(item)
                continue
            previous = state["urls"].get(str(url), {})
            try:
                body = b""
                content_type = ""
                error: Exception | None = None
                for attempt in range(args.retries + 1):
                    try:
                        body, content_type = fetch(str(url), args.timeout, args.max_bytes)
                        error = None
                        break
                    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                        error = exc
                        if attempt < args.retries:
                            time.sleep(1.5 * (attempt + 1))
                if error is not None:
                    raise error
                digest = hashlib.sha256(body).hexdigest()
                target_dir = (
                    args.registry.parent
                    / safe_part(str(fragment.get("recognition_year") or ""))
                    / safe_part(str(fragment.get("region") or "待核验"))
                )
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f"{safe_part(str(fragment.get('title') or '官方分片'))}_{digest[:12]}{extension(str(url), content_type)}"
                if digest == str(previous.get("sha256") or "") and Path(str(previous.get("local_path") or "")).is_file():
                    item["status"] = "unchanged"
                    target = Path(str(previous["local_path"]))
                else:
                    target.write_bytes(body)
                    item["status"] = "downloaded_new_or_changed"
                item["local_path"] = str(target)
                item["sha256"] = digest
                state["urls"][str(url)] = {
                    "sha256": digest,
                    "local_path": str(target),
                    "content_type": content_type,
                    "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = str(exc)
            results.append(item)
    state["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "generated_at": state["updated_at"],
        "downloaded_or_changed": sum(item["status"] == "downloaded_new_or_changed" for item in results),
        "unchanged": sum(item["status"] == "unchanged" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "skipped": sum(item["status"].startswith("skipped") for item in results),
        "results": results,
    }
    (args.registry.parent / "official_fragment_collection_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

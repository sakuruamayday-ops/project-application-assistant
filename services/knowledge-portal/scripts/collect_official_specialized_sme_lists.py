#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html as html_module
import json
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "references" / "official_specialized_sme_sources.json"
DEFAULT_OUTPUT = Path("/Volumes/知识库/_云端知识库/50_名单与对标/优质中小企业梯度培育/_省级专精特新")
ATTACHMENT_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".wps", ".zip"}
USER_AGENT = "JiaotangKnowledgeCollector/1.0"
JINA_READER_PREFIX = "https://r.jina.ai/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集11个疑似缺口地区的省级专精特新官方名单")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def safe_name(value: str, limit: int = 72) -> str:
    value = re.sub(r"[\\/:*?\"<>|\s]+", "_", value).strip("._")
    return value[:limit] or "官方来源"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def response_filename(response: requests.Response, url: str, fallback: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, flags=re.I)
    if match:
        return safe_name(unquote(match.group(1)), 120)
    path_name = unquote(Path(urlparse(url).path).name)
    if Path(path_name).suffix.lower() in ATTACHMENT_SUFFIXES:
        return safe_name(path_name, 120)
    mime = response.headers.get("content-type", "").split(";", 1)[0]
    suffix = mimetypes.guess_extension(mime) or ""
    return f"{safe_name(fallback)}{suffix}"


def attachment_evidence_type(source: dict[str, object], label: str) -> str:
    normalized = re.sub(r"\s+", "", label)
    if any(term in normalized for term in ("取消认定", "撤销", "不予通过", "未通过")):
        return "revocation"
    if any(term in normalized for term in ("更名", "名称变更")):
        return "identity_change"
    if any(term in normalized for term in ("拟认定", "拟通过", "公示名单", "名单公示")):
        return "public"
    if "复核通过" in normalized:
        return "final_review"
    if any(term in normalized for term in ("新认定", "认定企业名单", "申报通过名单")):
        return "final"
    return str(source["evidence_type"])


def evidence_filename(source: dict[str, object], original_name: str, label: str) -> str:
    evidence_type = attachment_evidence_type(source, label)
    marker = {
        "final": "正式认定",
        "historical_final_attachment": "历史正式认定",
        "final_review": "复核通过",
        "public": "公示过程",
        "application_notice": "申报通知",
        "identity_change": "企业更名",
        "revocation": "取消或未通过",
    }.get(evidence_type, "待核验证据")
    original = Path(original_name)
    stem = safe_name(f"{marker}_{source['expected_title']}_{original.stem}", 108)
    return f"{stem}{original.suffix.lower()}"


def attachment_links(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, str(anchor.get("href")))
        text = " ".join(anchor.get_text(" ", strip=True).split())
        parsed = urlparse(href)
        suffix = Path(unquote(parsed.path)).suffix.lower()
        hint = f"{text} {href}".lower()
        if suffix not in ATTACHMENT_SUFFIXES and not any(term in hint for term in ("download", "downfile", "附件", "file/")):
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append((href, text or Path(parsed.path).name or "附件"))
    decoded_html = html_module.unescape(html).replace("\\/", "/")
    paired_arrays = re.findall(
        r"(?:fLinks|fileLinks)\s*=\s*['\"]([^'\"]+)['\"]\.split\([^)]*\).*?"
        r"(?:fNames|fileNames)\s*=\s*['\"]([^'\"]+)['\"]\.split\([^)]*\)",
        decoded_html,
        flags=re.I | re.S,
    )
    for raw_links, raw_names in paired_arrays:
        urls = [item.strip() for item in raw_links.split(",")]
        names = [item.strip() for item in raw_names.split(",")]
        for index, raw_url in enumerate(urls):
            href = urljoin(base_url, raw_url)
            suffix = Path(unquote(urlparse(href).path)).suffix.lower()
            if suffix not in ATTACHMENT_SUFFIXES or href in seen:
                continue
            seen.add(href)
            label = names[index] if index < len(names) and names[index] else Path(urlparse(href).path).name
            links.append((href, label))
    for raw_url in re.findall(
        r"""(?P<url>(?:https?://|(?:\./|/))[^"'<>\\s,]+?\.(?:pdf|docx?|xlsx?|wps|zip)(?:\?[^"'<>\\s,]*)?)""",
        decoded_html,
        flags=re.I,
    ):
        href = urljoin(base_url, raw_url)
        if href in seen:
            continue
        seen.add(href)
        links.append((href, Path(unquote(urlparse(href).path)).name or "附件"))
    return links


def page_markdown(source: dict[str, object], html: str, final_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = "\n".join(
        line for line in (" ".join(item.split()) for item in soup.get_text("\n").splitlines()) if line
    )
    return "\n".join(
        [
            f"# {source['expected_title']}",
            "",
            f"- 地区：{source['region']}",
            f"- 名单年度：{source['year']}",
            f"- 证据类型：{source['evidence_type']}",
            f"- 官方来源：{final_url}",
            f"- 采集时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
            "",
            "## 官方页面正文",
            "",
            text[:300_000],
            "",
        ]
    )


def source_markdown(source: dict[str, object], final_url: str, attachment_name: str) -> str:
    return "\n".join(
        [
            f"# {source['expected_title']}",
            "",
            f"- 地区：{source['region']}",
            f"- 名单年度：{source['year']}",
            f"- 证据类型：{source['evidence_type']}",
            f"- 官方来源：{final_url}",
            f"- 官方附件：{attachment_name}",
            f"- 采集时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
            "",
            "## 证据口径",
            "",
            "本目录以正式公布、认定或复核通过名单为有效主表。公示、推荐和拟认定名单只保留为过程证据，不替代最终认定结果。",
            "",
        ]
    )


def jina_markdown(session: requests.Session, url: str, timeout: int) -> tuple[str, str]:
    reader_url = f"{JINA_READER_PREFIX}{url}"
    response = session.get(reader_url, timeout=max(timeout, 60), allow_redirects=True)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text, reader_url


def collect_source(session: requests.Session, source: dict[str, object], output: Path, timeout: int) -> dict[str, object]:
    key = hashlib.sha256(str(source["url"]).encode("utf-8")).hexdigest()[:12]
    target = output / str(source["region"]) / str(source["year"]) / f"{safe_name(str(source['expected_title']))}__{key}"
    target.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        **source,
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "attachments": [],
        "status": "pending",
    }
    try:
        response = session.get(str(source["url"]), timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        direct_suffix = Path(unquote(urlparse(response.url).path)).suffix.lower()
        if direct_suffix in ATTACHMENT_SUFFIXES or "application/pdf" in content_type or "application/msword" in content_type:
            original_name = response_filename(response, response.url, str(source["expected_title"]))
            name = evidence_filename(source, original_name, str(source["expected_title"]))
            payload = response.content
            path = target / name
            path.write_bytes(payload)
            (target / "官方来源说明.md").write_text(
                source_markdown(source, response.url, name),
                encoding="utf-8",
            )
            record["attachments"] = [{
                "name": name,
                "url": response.url,
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "evidence_type": attachment_evidence_type(source, str(source["expected_title"])),
            }]
            record["status"] = "downloaded_direct"
        else:
            response.encoding = response.apparent_encoding or response.encoding
            html = response.text
            (target / "官方页面.md").write_text(page_markdown(source, html, response.url), encoding="utf-8")
            attachments: list[dict[str, object]] = []
            for index, (url, label) in enumerate(attachment_links(html, response.url), start=1):
                try:
                    attachment = session.get(url, timeout=timeout, allow_redirects=True)
                    attachment.raise_for_status()
                    payload = attachment.content
                    if not payload:
                        continue
                    original_name = response_filename(attachment, attachment.url, f"附件{index}_{label}")
                    name = evidence_filename(source, original_name, label)
                    path = target / name
                    if path.exists() and sha256_bytes(path.read_bytes()) != sha256_bytes(payload):
                        path = target / f"{path.stem}_{index}{path.suffix}"
                    path.write_bytes(payload)
                    attachments.append({
                        "name": path.name,
                        "url": attachment.url,
                        "sha256": sha256_bytes(payload),
                        "bytes": len(payload),
                        "evidence_type": attachment_evidence_type(source, label),
                    })
                except requests.RequestException as exc:
                    attachments.append({"name": label, "url": url, "error": str(exc)})
            record["attachments"] = attachments
            record["status"] = "downloaded_page"
            record["final_url"] = response.url
    except requests.RequestException as exc:
        try:
            markdown, reader_url = jina_markdown(session, str(source["url"]), timeout)
            content = "\n".join(
                [
                    f"# {source['expected_title']}",
                    "",
                    f"- 地区：{source['region']}",
                    f"- 名单年度：{source['year']}",
                    f"- 证据类型：{source['evidence_type']}",
                    f"- 官方来源：{source['url']}",
                    f"- 采集方式：Jina Reader 只读镜像，原始权威来源不变",
                    f"- 采集时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
                    "",
                    "## 官方页面正文",
                    "",
                    markdown[:300_000],
                    "",
                ]
            )
            (target / "官方页面.md").write_text(content, encoding="utf-8")
            record["status"] = "downloaded_reader_fallback"
            record["final_url"] = str(source["url"])
            record["reader_url"] = reader_url
            record["direct_error"] = str(exc)
        except requests.RequestException as fallback_exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            record["reader_error"] = str(fallback_exc)
    (target / "source_record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def main() -> None:
    args = parse_args()
    payload = json.loads(args.config.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    results = [collect_source(session, source, args.output, args.timeout) for source in payload["sources"]]
    report = {
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total": len(results),
        "success": sum(item["status"] != "failed" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "attachments": sum(len(item.get("attachments", [])) for item in results),
        "results": results,
    }
    (args.output / "采集报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("total", "success", "failed", "attachments")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

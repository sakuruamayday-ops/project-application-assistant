#!/usr/bin/env python3
import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import ssl
import subprocess
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ATTACHMENT_SUFFIXES = (".pdf", ".xlsx", ".xls", ".docx", ".doc")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() not in {"a", "img"}:
            return
        values = dict(attrs)
        link = values.get("href") or values.get("src")
        if link:
            self.links.append(link)


def fetch(url, timeout):
    if shutil.which("curl"):
        with tempfile.NamedTemporaryFile() as target:
            result = subprocess.run(
                ["curl", "--location", "--fail", "--silent", "--show-error", "--max-time", str(timeout), "--output", target.name, "--write-out", "%{url_effective}\n%{content_type}", url],
                capture_output=True,
                text=True,
            )
            if result.returncode:
                raise OSError(result.stderr.strip() or f"curl退出码{result.returncode}")
            lines = result.stdout.splitlines()
            final_url = lines[0] if lines else url
            content_type = lines[1].split(";", 1)[0] if len(lines) > 1 else (mimetypes.guess_type(final_url)[0] or "application/octet-stream")
            target.seek(0)
            return target.read(), final_url, content_type
    request = Request(url, headers={"User-Agent": "ProjectApplicationAssistant/2.0"})
    with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        return response.read(), response.geturl(), response.headers.get_content_type()


def extract_text(path):
    if path.suffix.lower() != ".pdf":
        return ""
    try:
        import fitz
    except ImportError:
        return ""
    document = fitz.open(path)
    try:
        return "\n".join(page.get_text("text") for page in document)
    finally:
        document.close()


def classification_codes(text):
    ipc_groups = sorted(set(re.findall(r"\b[A-H]\d{2}[A-Z]\s*\d{1,4}/\d{1,6}\b", text.upper())))
    ipc_subclasses = sorted(set(re.findall(r"\b[A-H]\d{2}[A-Z]\b", text.upper())))
    locarno = sorted(set(re.findall(r"(?<!\d)(?:0[1-9]|[1-2]\d|3[0-2])-\d{2}(?!\d)", text)))
    return ipc_groups, ipc_subclasses, locarno


def previous_registry(path):
    if not path.exists():
        return {}
    try:
        return {item["center"]: item for item in json.loads(path.read_text(encoding="utf-8"))}
    except (KeyError, json.JSONDecodeError):
        return {}


def update_source(source, output, previous, timeout):
    center = source["center"]
    center_dir = output / re.sub(r"[^A-Za-z0-9\u4e00-\u9fff-]", "_", center)
    center_dir.mkdir(parents=True, exist_ok=True)
    result = {"center": center, "service_region": source.get("service_region", ""), "official_page": source["official_page"],
              "checked_at": now_iso(), "status": "error", "attachments": [], "ipc_groups": [],
              "ipc_subclasses": [], "locarno_classes": [], "error": ""}
    try:
        page_bytes, final_page, content_type = fetch(source["official_page"], timeout)
        result["official_page_final"] = final_page
        page_hash = hashlib.sha256(page_bytes).hexdigest()
        result["page_hash"] = page_hash
        links = []
        if content_type == "text/html":
            parser = LinkParser()
            parser.feed(page_bytes.decode("utf-8", "replace"))
            links.extend(urljoin(final_page, link) for link in parser.links if link.lower().split("?", 1)[0].endswith(ATTACHMENT_SUFFIXES))
        if source.get("direct_attachment"):
            links.insert(0, source["direct_attachment"])
        texts = []
        for index, link in enumerate(dict.fromkeys(links), 1):
            try:
                data, final_url, _ = fetch(link, timeout)
                suffix = Path(final_url.split("?", 1)[0]).suffix.lower() or ".bin"
                target = center_dir / f"attachment-{index}{suffix}"
                target.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                text = extract_text(target)
                texts.append(text)
                result["attachments"].append({"url": link, "final_url": final_url, "sha256": digest, "file": str(target)})
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                result["attachments"].append({"url": link, "error": str(error)})
        combined = "\n".join(texts)
        result["ipc_groups"], result["ipc_subclasses"], result["locarno_classes"] = classification_codes(combined)
        old = previous.get(center, {})
        old_signature = (old.get("page_hash"), [item.get("sha256") for item in old.get("attachments", [])])
        new_signature = (page_hash, [item.get("sha256") for item in result["attachments"]])
        result["status"] = "changed" if old and old_signature != new_signature else "unchanged" if old else "new"
        result["catalog_status"] = "official_page_only" if not result["attachments"] else "parsed" if combined.strip() else "attachment_downloaded_text_unavailable"
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError) as error:
        result["error"] = str(error)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=Path(__file__).resolve().parents[1] / "references" / "preexamination-sources.json")
    parser.add_argument("--output", type=Path, default=Path.home() / ".project-application-assistant" / "preexamination")
    parser.add_argument("--timeout", type=float, default=20)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    registry_path = arguments.output / "registry.json"
    previous = previous_registry(registry_path)
    sources = json.loads(arguments.sources.read_text(encoding="utf-8"))
    results = [update_source(source, arguments.output, previous, arguments.timeout) for source in sources]
    registry_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"status": "complete", "registry": str(registry_path), "centers": len(results),
               "new": sum(item["status"] == "new" for item in results),
               "changed": sum(item["status"] == "changed" for item in results),
               "unchanged": sum(item["status"] == "unchanged" for item in results),
               "errors": sum(item["status"] == "error" for item in results),
               "parsed": sum(item.get("catalog_status") == "parsed" for item in results)}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import fitz


SWIFT_SOURCE = r"""
import Foundation
import Vision
import ImageIO

for path in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: path)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        continue
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true
    try VNImageRequestHandler(cgImage: image).perform([request])
    let observations = (request.results ?? []).sorted {
        if abs($0.boundingBox.maxY - $1.boundingBox.maxY) > 0.01 {
            return $0.boundingBox.maxY > $1.boundingBox.maxY
        }
        return $0.boundingBox.minX < $1.boundingBox.minX
    }
    print("\n<!-- PAGE \(url.lastPathComponent) -->")
    for observation in observations {
        if let candidate = observation.topCandidates(1).first {
            print(candidate.string)
        }
    }
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用本地 macOS Vision OCR 回填扫描 PDF 全文缓存")
    parser.add_argument(
        "--extraction-report",
        type=Path,
        default=Path(os.environ.get("JIAOTANG_EXTRACTION_REPORT", Path.cwd() / "cloud_package_index/extraction_report.csv")),
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path(os.environ.get("JIAOTANG_UPLOAD_ALLOWLIST", Path.cwd() / "cloud_package_index/upload_allowlist.csv")),
    )
    parser.add_argument(
        "--knowledge-root", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_KNOWLEDGE_ROOT", Path.cwd() / "knowledge"))
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(os.environ.get("JIAOTANG_EXTRACTION_CACHE", Path.home() / ".cache/project-application-assistant/knowledge-extraction-cache.jsonl")),
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("JIAOTANG_LOCAL_OCR_WORK", Path.cwd() / "knowledge-migration/local-ocr-work")),
    )
    parser.add_argument("--path-prefix", default="")
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--start-at", type=int, default=1)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_vision_binary(work_root: Path) -> Path:
    tools = work_root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    source = tools / "vision_ocr.swift"
    binary = tools / "vision_ocr"
    source_hash = tools / "vision_ocr.sha256"
    expected_hash = sha256_text(SWIFT_SOURCE)
    if not source.exists() or source.read_text(encoding="utf-8") != SWIFT_SOURCE:
        source.write_text(SWIFT_SOURCE, encoding="utf-8")
    if not binary.exists() or not source_hash.exists() or source_hash.read_text() != expected_hash:
        subprocess.run(["swiftc", str(source), "-o", str(binary)], check=True)
        source_hash.write_text(expected_hash, encoding="utf-8")
    return binary


def render_pdf(path: Path, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    images: list[Path] = []
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            image = output / f"page-{page_number:04d}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False).save(image)
            images.append(image)
    return images


def load_completed(cache_path: Path) -> set[str]:
    completed: set[str] = set()
    if not cache_path.exists():
        return completed
    for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("status") == "indexed" and item.get("sha256"):
            completed.add(str(item["sha256"]))
    return completed


def is_pdf_target(knowledge_root: Path, relative_path: str) -> bool:
    try:
        return (knowledge_root / relative_path).read_bytes()[:4] == b"%PDF"
    except OSError:
        return False


def main() -> None:
    args = parse_args()
    report_path = args.extraction_report.expanduser().resolve()
    knowledge_root = args.knowledge_root.expanduser().resolve()
    cache_path = args.cache.expanduser().resolve()
    work_root = args.work_root.expanduser().resolve()
    binary = ensure_vision_binary(work_root)
    completed = load_completed(cache_path)
    pending_digests: set[str] | None = None
    if args.allowlist.exists():
        with args.allowlist.open(encoding="utf-8-sig") as source:
            pending_digests = {
                row["sha256"]
                for row in csv.DictReader(source)
                if row["decision"] == "object_only_pending_extraction"
            }

    if args.queue:
        with args.queue.expanduser().resolve().open(encoding="utf-8-sig") as source:
            candidates = [
                {"relative_path": row["相对路径"], "sha256": row["SHA256"]}
                for row in csv.DictReader(source)
                if row["相对路径"].startswith(args.path_prefix)
                and row["SHA256"] not in completed
                and (pending_digests is None or row["SHA256"] in pending_digests)
            ]
    else:
        with report_path.open(encoding="utf-8-sig") as source:
            candidates = [
                row
                for row in csv.DictReader(source)
                if (
                    row["status"] == "ocr_required"
                    or (
                        row["status"] == "manual_review"
                        and is_pdf_target(knowledge_root, row["relative_path"])
                    )
                )
                and row["relative_path"].startswith(args.path_prefix)
                and row["sha256"] not in completed
                and (pending_digests is None or row["sha256"] in pending_digests)
            ]
    all_targets = []
    queued_digests = set()
    for row in candidates:
        if row["sha256"] in queued_digests:
            continue
        queued_digests.add(row["sha256"])
        all_targets.append(row)
    start = max(args.start_at - 1, 0)
    targets = all_targets[start:]
    if args.limit is not None:
        targets = targets[: args.limit]

    results: list[dict[str, object]] = []
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    scratch = work_root / "scratch" / "pages"
    for target_number, target in enumerate(targets, start=1):
        source_path = knowledge_root / target["relative_path"]
        document_work = work_root / target["sha256"]
        document_work.mkdir(parents=True, exist_ok=True)
        try:
            images = render_pdf(source_path, scratch)
            process = subprocess.run(
                [str(binary), *(str(image) for image in images)],
                capture_output=True,
                check=True,
                text=True,
                timeout=max(180, len(images) * 45),
            )
            text = process.stdout.strip()
            status = "indexed" if len(text) >= 40 else "ocr_required"
            error = ""
        except Exception as exception:
            images = []
            text = ""
            status = f"error:{type(exception).__name__}"
            error = str(exception)
        (document_work / "result.md").write_text(text, encoding="utf-8")
        with cache_path.open("a", encoding="utf-8") as cache:
            cache.write(
                json.dumps(
                    {"sha256": target["sha256"], "status": status, "text": text},
                    ensure_ascii=False,
                )
                + "\n"
            )
        results.append(
            {
                "relative_path": target["relative_path"],
                "sha256": target["sha256"],
                "pages": len(images),
                "text_chars": len(text),
                "status": status,
                "work_path": str(document_work),
                "error": error,
            }
        )
        print(
            f"processed={target_number}/{len(targets)} "
            + json.dumps(results[-1], ensure_ascii=False),
            flush=True,
        )

    output = report_path.parent / "local_ocr_report.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=[
                "relative_path", "sha256", "pages", "text_chars", "status", "work_path", "error"
            ],
        )
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    main()

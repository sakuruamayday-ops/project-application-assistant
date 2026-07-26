#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

THIRD_PARTY = {"lawcheng.cn", "www.lawcheng.cn", "ccn.com.cn", "www.ccn.com.cn",
               "static.nfnews.com", "ipr.mofcom.gov.cn", "keyanchu.yeu.edu.cn",
               "scit.nju.edu.cn"}

def normalize_source(raw):
    raw = (raw or "").strip()
    if not raw or "..." in raw or "…" in raw or ";" in raw or "；" in raw or "（" in raw or "）" in raw:
        return None
    if " " in raw or raw.endswith(".cn"):
        return None
    url = raw if re.match(r"^https?://", raw) else "https://" + raw
    p = urlparse(url)
    return url if p.netloc and "." in p.netloc else None

def probe(url, timeout):
    if not url:
        return {"reachable": False, "http_status": None, "final_url": None, "error": "unusable_source_string"}
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 jiaotang-rule-audit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            body = r.read(2_000_000)
            return {
                "reachable": True,
                "http_status": getattr(r, "status", 200),
                "final_url": r.geturl(),
                "content_type": r.headers.get("Content-Type"),
                "last_modified": r.headers.get("Last-Modified"),
                "etag": r.headers.get("ETag"),
                "sha256_first_2mb": hashlib.sha256(body).hexdigest(),
            }
    except Exception as e:
        status = e.code if isinstance(e, urllib.error.HTTPError) else None
        return {"reachable": False, "http_status": status, "final_url": None, "error": f"{type(e).__name__}: {e}"}

def classify(center, live):
    raw = center.get("source", "")
    url = normalize_source(raw)
    host = urlparse(url).netloc.lower() if url else ""
    reasons = []
    if center.get("partial"):
        reasons.append("embedded_list_partial")
    if center.get("confidence") == "derived":
        reasons.append("derived_not_official")
    if host in THIRD_PARTY or center.get("confidence") == "website":
        reasons.append("officiality_not_proven")
    if not url:
        reasons.append("source_not_machine_resolvable")
    if not live.get("reachable"):
        reasons.append("source_not_reachable")
    if not center.get("official_snapshot_sha256"):
        reasons.append("no_official_snapshot_hash")
    if not center.get("official_published_at"):
        reasons.append("no_official_publication_date")
    if not center.get("verified_at"):
        reasons.append("no_record_level_verification_date")
    return ("verified_current" if not reasons else "not_verified_current"), reasons, url, host

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--probe", action="store_true")
    p.add_argument("--timeout", type=float, default=8)
    p.add_argument("--workers", type=int, default=8)
    a = p.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads(Path(a.input).read_text(encoding="utf-8"))
    centers = data["centers"]
    urls = [normalize_source(x.get("source")) for x in centers]
    if a.probe:
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            live = list(ex.map(lambda u: probe(u, a.timeout), urls))
    else:
        live = [{"reachable": False, "http_status": None, "final_url": None, "error": "probe_not_run"} for _ in urls]
    center_rows, entry_rows = [], []
    for c, lv in zip(centers, live):
        status, reasons, url, host = classify(c, lv)
        row = {
            "id": c.get("id"), "center": c.get("name"), "confidence": c.get("confidence"),
            "partial": bool(c.get("partial")), "declared_count": c.get("count"),
            "embedded_count": len(c.get("subclasses") or []), "source_raw": c.get("source"),
            "normalized_url": url, "host": host, "reachable": lv.get("reachable"),
            "http_status": lv.get("http_status"), "final_url": lv.get("final_url"),
            "content_type": lv.get("content_type"), "last_modified": lv.get("last_modified"),
            "etag": lv.get("etag"), "source_hash": lv.get("sha256_first_2mb"),
            "currentness_status": status, "reasons": reasons,
        }
        center_rows.append(row)
        for code in c.get("subclasses") or []:
            entry_rows.append({
                "center_id": c.get("id"), "center": c.get("name"), "ipc_subclass": code,
                "currentness_status": status, "inherited_reasons": reasons,
                "source_raw": c.get("source"), "normalized_url": url,
            })
    checked = datetime.now().astimezone().isoformat()
    report = {
        "checked_at": checked,
        "input": str(Path(a.input).resolve()),
        "input_sha256": hashlib.sha256(Path(a.input).read_bytes()).hexdigest(),
        "dataset_generated": data.get("meta", {}).get("generated"),
        "center_count": len(center_rows),
        "embedded_ipc_entries": len(entry_rows),
        "verified_current_centers": sum(x["currentness_status"] == "verified_current" for x in center_rows),
        "verified_current_entries": sum(x["currentness_status"] == "verified_current" for x in entry_rows),
        "partial_centers": sum(x["partial"] for x in center_rows),
        "derived_centers": sum(x["confidence"] == "derived" for x in center_rows),
        "machine_resolvable_sources": sum(bool(x["normalized_url"]) for x in center_rows),
        "reachable_sources": sum(bool(x["reachable"]) for x in center_rows),
        "conclusion": "PASS" if all(x["currentness_status"] == "verified_current" for x in center_rows) else "FAIL_NOT_VERIFIED_CURRENT",
        "centers": center_rows,
    }
    (out / "preexam_rule_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "preexam_ipc_entry_audit.json").write_text(json.dumps(entry_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out / "preexam_center_audit.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[k for k in center_rows[0] if k != "reasons"] + ["reasons"])
        w.writeheader()
        for x in center_rows:
            y = dict(x); y["reasons"] = "|".join(y["reasons"]); w.writerow(y)
    lines = [
        "# 地方专利预审规则逐项审计",
        "",
        f"- 核验时间：{checked}",
        f"- 中心记录：{len(center_rows)}",
        f"- 已录入 IPC 小类记录：{len(entry_rows)}",
        f"- 可标记 verified_current 的中心：{report['verified_current_centers']}",
        f"- 可标记 verified_current 的 IPC 记录：{report['verified_current_entries']}",
        f"- 部分清单中心：{report['partial_centers']}",
        f"- 派生中心：{report['derived_centers']}",
        f"- 可机器解析来源：{report['machine_resolvable_sources']}",
        f"- 在线可达来源：{report['reachable_sources']}",
        f"- 总结论：{report['conclusion']}",
        "",
        "只有存在可访问官方原文、发布日、内容快照哈希和逐记录核验日的记录才可标记为现行已核验。",
    ]
    (out / "preexam_rule_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "centers"}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["conclusion"] == "PASS" else 3)

if __name__ == "__main__":
    main()

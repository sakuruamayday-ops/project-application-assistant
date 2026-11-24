#!/usr/bin/env python3
import argparse
import json
import shutil
import sqlite3
import ssl
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def record_metrics(connection, arguments):
    connection.execute(
        """INSERT INTO collection_metrics(
        source, observed_at, pages_attempted, pages_succeeded, list_records,
        detail_requests, throttled_count, captcha_count, login_required_count,
        min_interval_seconds, max_interval_seconds, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            arguments.source,
            now_iso(),
            arguments.pages_attempted,
            arguments.pages_succeeded,
            arguments.list_records,
            arguments.detail_requests,
            arguments.throttled_count,
            arguments.captcha_count,
            arguments.login_required_count,
            arguments.min_interval_seconds,
            arguments.max_interval_seconds,
            arguments.notes,
        ),
    )
    connection.commit()
    return {"status": "recorded", "source": arguments.source}


def check_url(url, timeout):
    if shutil.which("curl"):
        command = ["curl", "--location", "--silent", "--show-error", "--max-time", str(timeout), "--output", "/dev/null", "--write-out", "%{http_code}\n%{url_effective}", url]
        result = subprocess.run(command, capture_output=True, text=True)
        lines = result.stdout.splitlines()
        status = int(lines[0]) if lines and lines[0].isdigit() else None
        final_url = lines[1] if len(lines) > 1 else url
        return status, final_url, result.returncode == 0 and status is not None and 200 <= status < 400, result.stderr.strip()
    request = Request(url, method="HEAD", headers={"User-Agent": "ProjectApplicationAssistant/2.0"})
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return response.status, response.geturl(), 200 <= response.status < 400, ""
    except HTTPError as error:
        if error.code in {405, 501}:
            fallback = Request(url, headers={"User-Agent": "ProjectApplicationAssistant/2.0", "Range": "bytes=0-1023"})
            try:
                with urlopen(fallback, timeout=timeout, context=ssl.create_default_context()) as response:
                    return response.status, response.geturl(), 200 <= response.status < 400, ""
            except (HTTPError, URLError, TimeoutError) as fallback_error:
                return getattr(fallback_error, "code", None), url, False, str(fallback_error)
        return error.code, url, False, str(error)
    except (URLError, TimeoutError) as error:
        return None, url, False, str(error)


def check_links(connection, arguments):
    rows = connection.execute(
        "SELECT id, official_url FROM records WHERE active=1 AND official_url<>'' ORDER BY last_seen_at DESC LIMIT ?",
        (arguments.limit,),
    ).fetchall()
    valid = 0
    for row in rows:
        status, final_url, is_valid, error = check_url(row["official_url"], arguments.timeout)
        connection.execute(
            "INSERT INTO official_link_checks(record_id, checked_at, http_status, final_url, valid, error) VALUES (?, ?, ?, ?, ?, ?)",
            (row["id"], now_iso(), status, final_url, int(is_valid), error),
        )
        valid += int(is_valid)
    connection.commit()
    total = len(rows)
    return {
        "status": "checked",
        "checked": total,
        "valid": valid,
        "invalid": total - valid,
        "valid_rate": round(valid / total, 4) if total else None,
    }


def report(connection):
    metrics = dict(connection.execute(
        """SELECT COALESCE(SUM(pages_attempted),0) pages_attempted,
        COALESCE(SUM(pages_succeeded),0) pages_succeeded,
        COALESCE(SUM(list_records),0) list_records,
        COALESCE(SUM(detail_requests),0) detail_requests,
        COALESCE(SUM(throttled_count),0) throttled_count,
        COALESCE(SUM(captcha_count),0) captcha_count,
        COALESCE(SUM(login_required_count),0) login_required_count
        FROM collection_metrics"""
    ).fetchone())
    links = dict(connection.execute(
        """SELECT COUNT(*) checked, COALESCE(SUM(valid),0) valid FROM official_link_checks
        WHERE id IN (SELECT MAX(id) FROM official_link_checks GROUP BY record_id)"""
    ).fetchone())
    links["valid_rate"] = round(links["valid"] / links["checked"], 4) if links["checked"] else None
    coverage = dict(connection.execute(
        "SELECT COUNT(*) records, COALESCE(SUM(CASE WHEN official_url<>'' THEN 1 ELSE 0 END),0) with_official_url FROM records WHERE active=1"
    ).fetchone())
    coverage["coverage_rate"] = round(coverage["with_official_url"] / coverage["records"], 4) if coverage["records"] else None
    return {"collection": metrics, "official_link_coverage": coverage, "official_links": links}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    metrics = subparsers.add_parser("record-metrics")
    metrics.add_argument("--source", default="aiqice")
    for name in ("pages-attempted", "pages-succeeded", "list-records", "detail-requests", "throttled-count", "captcha-count", "login-required-count"):
        metrics.add_argument(f"--{name}", type=int, default=0)
    metrics.add_argument("--min-interval-seconds", type=float, default=0)
    metrics.add_argument("--max-interval-seconds", type=float, default=0)
    metrics.add_argument("--notes", default="")
    links = subparsers.add_parser("check-links")
    links.add_argument("--limit", type=int, default=100)
    links.add_argument("--timeout", type=float, default=10)
    subparsers.add_parser("report")
    arguments = parser.parse_args()
    connection = connect(arguments.db)
    if arguments.command == "record-metrics":
        result = record_metrics(connection, arguments)
    elif arguments.command == "check-links":
        result = check_links(connection, arguments)
    else:
        result = report(connection)
    connection.close()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

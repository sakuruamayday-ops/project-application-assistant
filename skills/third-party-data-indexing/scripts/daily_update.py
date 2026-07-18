#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE = SCRIPT_DIR / "index_engine.py"


def default_root():
    configured = os.environ.get("PROJECT_APPLICATION_ASSISTANT_INDEX_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / ".project-application-assistant" / "index"


def default_regions():
    profile = Path.home() / ".project-application-assistant" / "profile.json"
    if not profile.exists():
        return []
    try:
        return json.loads(profile.read_text(encoding="utf-8")).get("scope", [])
    except (OSError, json.JSONDecodeError):
        return []


def successful_dates(db, source):
    if not db.exists():
        return set()
    connection = sqlite3.connect(db)
    try:
        return {row[0] for row in connection.execute("SELECT collection_date FROM collection_days WHERE source=? AND status='success'", (source,))}
    except sqlite3.OperationalError:
        return set()
    finally:
        connection.close()


def planned_dates(successes, through, max_backfill_days):
    if successes:
        start = date.fromisoformat(max(successes)) + timedelta(days=1)
    else:
        start = through
    minimum = through - timedelta(days=max_backfill_days - 1)
    start = max(start, minimum)
    days = []
    current = start
    while current <= through:
        if current.isoformat() not in successes:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def ingest_file(db, path, source, collection_date, regions):
    command = [sys.executable, str(ENGINE), "--db", str(db), "ingest", "--input", str(path), "--source", source, "--collection-date", collection_date]
    for region in regions:
        command.extend(["--region", region])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def find_input(inbox, source, collection_date):
    for suffix in ("jsonl", "json"):
        candidate = inbox / f"{source}-{collection_date}.{suffix}"
        if candidate.exists():
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--source", default="aiqice")
    parser.add_argument("--through", type=date.fromisoformat, default=date.today())
    parser.add_argument("--max-backfill-days", type=int, default=30)
    parser.add_argument("--region", action="append")
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    args.region = args.region if args.region is not None else default_regions()
    args.root.mkdir(parents=True, exist_ok=True)
    inbox = args.root / "inbox"
    requests = args.root / "requests"
    inbox.mkdir(exist_ok=True)
    requests.mkdir(exist_ok=True)
    db = args.root / "policy-index.sqlite3"
    subprocess.run([sys.executable, str(ENGINE), "--db", str(db), "init"], check=True, capture_output=True, text=True)
    if not args.region:
        print(json.dumps({
            "status": "region_configuration_required",
            "db": str(db),
            "message": "请先在项目申报助手中设置默认政策地区",
            "ingested": [],
            "pending": [],
        }, ensure_ascii=False, sort_keys=True))
        return
    dates = planned_dates(successful_dates(db, args.source), args.through, args.max_backfill_days)
    ingested = []
    pending = []
    for collection_date in dates:
        input_path = find_input(inbox, args.source, collection_date)
        if input_path:
            result = ingest_file(db, input_path, args.source, collection_date, args.region)
            ingested.append(result)
            if result["status"] == "success":
                (requests / f"{args.source}-{collection_date}.json").unlink(missing_ok=True)
        else:
            request = {
                "source": args.source,
                "collection_date": collection_date,
                "regions": args.region,
                "record_types": ["申报通知", "公示公告"],
                "required_fields": ["eligibility_conditions", "beneficiary_companies", "beneficiary_count", "official_url"],
                "output": str(inbox / f"{args.source}-{collection_date}.jsonl"),
                "status": "browser_collection_required",
            }
            request_path = requests / f"{args.source}-{collection_date}.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            pending.append(request)
    if pending and args.open_browser:
        url = "https://www.aiqice.cn/policy"
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=False)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", url], check=False)
    has_partial_ingest = any(result["status"] != "success" for result in ingested)
    if pending:
        status = "partial" if ingested else "browser_collection_required"
    elif has_partial_ingest:
        status = "partial"
    else:
        status = "success"
    print(json.dumps({"status": status, "db": str(db), "ingested": ingested, "pending": pending}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

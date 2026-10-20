#!/usr/bin/env python3
"""List, export and acknowledge final reports using the existing SSH operations identity."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import client_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("/var/lib/jiaotang-kb/knowledge.db"))
    parser.add_argument("--root", type=Path, default=Path("/var/lib/jiaotang-kb/client-reports"))
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Completed reports not yet acknowledged by the collector")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)
    export = commands.add_parser("export", help="Write a complete, verified file to binary stdout")
    export.add_argument("--report-id", type=int, required=True)
    acknowledge = commands.add_parser("acknowledge", help="Confirm the daily collector successfully saved this report")
    acknowledge.add_argument("--report-id", type=int, required=True)
    cleanup = commands.add_parser("cleanup", help="Preview or explicitly release one successfully downloaded report copy")
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument("--report-id", type=int)
    args = parser.parse_args(argv)
    if args.command == "list" and (not 1 <= args.limit <= 1000 or args.offset < 0):
        parser.error("--limit must be between 1 and 1000; --offset must be nonnegative")
    if args.command == "cleanup" and not args.dry_run and args.report_id is None:
        parser.error("cleanup requires --dry-run or an exact --report-id")
    mode = "rw" if args.command == "acknowledge" or args.command == "cleanup" and not args.dry_run else "ro"
    try:
        with closing(sqlite3.connect(args.database.absolute().as_uri() + "?mode=" + mode, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            if mode == "ro":
                connection.execute("PRAGMA query_only=ON")
            if args.command == "list":
                reports = client_reports.list_reports(connection, undownloaded_only=True, limit=args.limit + 1, offset=args.offset)
                more = len(reports) > args.limit
                result = {"reports": reports[:args.limit], "next_offset": args.offset + args.limit if more else None}
            elif args.command == "export":
                _, path = client_reports.completed_file(connection, args.root, args.report_id)
                with path.open("rb") as stream:
                    shutil.copyfileobj(stream, sys.stdout.buffer)
                return 0
            elif args.command == "acknowledge":
                result = client_reports.acknowledge_download(connection, args.report_id)
            else:
                if args.report_id is not None:
                    result = client_reports.cleanup_report(connection, args.root, args.report_id, dry_run=args.dry_run)
                else:
                    rows = connection.execute("SELECT id AS report_id,filename,size_bytes,sha256,downloaded_at FROM client_reports WHERE completed_at IS NOT NULL AND downloaded_at IS NOT NULL AND cleaned_at IS NULL ORDER BY id").fetchall()
                    result = {"dry_run": True, "candidates": [dict(row) for row in rows], "deleted": 0}
            print(json.dumps(result, ensure_ascii=False))
            return 0
    except (OSError, sqlite3.Error, ValueError, client_reports.ReportNotFound) as error:
        # Paths, database details and customer metadata stay out of operation errors.
        print("Final report operation failed: " + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

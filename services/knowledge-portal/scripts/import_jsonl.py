from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.main import database, init_database


def default_source_key(record: dict[str, object]) -> str:
    stable_value = str(record.get("source") or "") + "\n" + str(record.get("title") or "")
    return hashlib.sha256(stable_value.encode("utf-8")).hexdigest()


def import_file(path: Path) -> tuple[int, int]:
    init_database()
    imported = 0
    rejected = 0
    with path.open("r", encoding="utf-8") as handle, closing(database()) as connection:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
                title = str(record["title"]).strip()
                content = str(record["content"]).strip()
                if not title or not content:
                    raise ValueError("title 和 content 不能为空")
                source = str(record.get("source") or "").strip() or None
                source_key = str(record.get("source_key") or "").strip() or default_source_key(record)
                updated_at = str(record.get("updated_at") or "").strip() or datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """
                    INSERT INTO documents(source_key, title, content, source, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_key) DO UPDATE SET
                        title = excluded.title,
                        content = excluded.content,
                        source = excluded.source,
                        updated_at = excluded.updated_at
                    """,
                    (source_key, title, content, source, updated_at),
                )
                imported += 1
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                print(f"第 {line_number} 行跳过：{exc}", file=sys.stderr)
                rejected += 1
        connection.commit()
    return imported, rejected


def main() -> None:
    parser = argparse.ArgumentParser(description="导入企业全生命周期助手知识库 JSONL 文件")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    imported, rejected = import_file(args.path)
    print(json.dumps({"imported": imported, "rejected": rejected}, ensure_ascii=False))


if __name__ == "__main__":
    main()

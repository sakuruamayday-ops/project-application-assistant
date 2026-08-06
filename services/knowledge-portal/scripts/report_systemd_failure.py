from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="记录焦糖运维systemd单元失败")
    parser.add_argument("--unit", required=True)
    parser.add_argument(
        "--clear",
        action="store_true",
        help="记录当前单元已恢复，清除过期的异常显示",
    )
    args = parser.parse_args()
    data_dir = Path(os.environ.get("JIAOTANG_DATA_DIR", "/var/lib/jiaotang-kb"))
    path = data_dir / "systemd-failure-status.json"
    properties = subprocess.run(
        [
            "systemctl",
            "show",
            args.unit,
            "--property=ActiveState,SubState,Result,ExecMainStatus",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    now = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    payload = {
        "status": "正常" if args.clear else "异常",
        "checked_at": now,
        "unit": args.unit,
        "systemd": properties.stdout.strip()[:2000],
    }
    payload["recovered_at" if args.clear else "failed_at"] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


if __name__ == "__main__":
    main()

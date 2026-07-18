#!/usr/bin/env bash
set -euo pipefail

health_url="${JIAOTANG_HEALTH_URL:-http://127.0.0.1:8100/health}"
data_dir="${JIAOTANG_DATA_DIR:-/var/lib/jiaotang-kb}"
public_host="${JIAOTANG_PUBLIC_HOST:?请设置 JIAOTANG_PUBLIC_HOST}"
response="$(curl --fail --silent --show-error --max-time 10 "${health_url}")"
checked_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
disk_percent="$(df -P "${data_dir}" | awk 'NR==2 {print $5}')"
certificate_expires="$(
    echo | openssl s_client -connect 127.0.0.1:443 -servername "${public_host}" 2>/dev/null \
        | openssl x509 -noout -enddate 2>/dev/null \
        | sed 's/^notAfter=//'
)"

python3 - "${data_dir}/health-status.json" "${checked_at}" "${disk_percent}" "${certificate_expires}" "${response}" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(sys.argv[5])
healthy = payload.get("status") == "ok"
status = {
    "status": "正常" if healthy else "异常",
    "checked_at": sys.argv[2],
    "disk_percent": sys.argv[3],
    "certificate_status": "有效" if sys.argv[4] else "待检查",
    "certificate_expires": sys.argv[4],
}
temporary = path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
os.chmod(temporary, 0o644)
os.replace(temporary, path)
raise SystemExit(0 if healthy else 1)
PY

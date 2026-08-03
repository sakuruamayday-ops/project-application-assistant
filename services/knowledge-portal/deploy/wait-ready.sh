#!/usr/bin/env bash
set -euo pipefail

ready_url="${JIAOTANG_READY_URL:-http://127.0.0.1:8100/readyz}"
for attempt in $(seq 1 45); do
    if curl --fail --silent --show-error --max-time 2 "${ready_url}" >/dev/null 2>&1; then
        exit 0
    fi
    sleep 1
done

echo "服务启动后45秒内未达到ready状态" >&2
exit 1

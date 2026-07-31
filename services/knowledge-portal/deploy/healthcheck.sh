#!/usr/bin/env bash
set -euo pipefail

app_dir="${JIAOTANG_APP_DIR:-/opt/jiaotang-kb}"
health_url="${JIAOTANG_HEALTH_URL:-http://127.0.0.1:8100/health}"
data_dir="${JIAOTANG_DATA_DIR:-/var/lib/jiaotang-kb}"
index_dir="${JIAOTANG_INDEX_DIR:-/srv/jiaotang/knowledge-index}"
public_host="${JIAOTANG_PUBLIC_HOST:?请设置 JIAOTANG_PUBLIC_HOST}"
response="$(curl --fail --silent --show-error --max-time 10 "${health_url}")"
disk_percent="$(df -P "${data_dir}" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
certificate_expires="$(
    echo | openssl s_client -connect 127.0.0.1:443 -servername "${public_host}" 2>/dev/null \
        | openssl x509 -noout -enddate 2>/dev/null \
        | sed 's/^notAfter=//'
)"
units=(
    jiaotang-kb.service
    jiaotang-kb-index-refresh.service
)
failed_args=()
for unit in "${units[@]}"; do
    if systemctl is-failed --quiet "${unit}"; then
        failed_args+=(--failed-unit "${unit}")
    fi
done

exec "${app_dir}/.venv/bin/python" \
    "${app_dir}/scripts/validate_operational_health.py" \
    --response-json "${response}" \
    --disk-percent "${disk_percent}" \
    --certificate-expires "${certificate_expires}" \
    --data-dir "${data_dir}" \
    --index-dir "${index_dir}" \
    --output "${data_dir}/health-status.json" \
    "${failed_args[@]}"

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

"${app_dir}/.venv/bin/python" \
    "${app_dir}/scripts/validate_operational_health.py" \
    --response-json "${response}" \
    --disk-percent "${disk_percent}" \
    --certificate-expires "${certificate_expires}" \
    --data-dir "${data_dir}" \
    --index-dir "${index_dir}" \
    --output "${data_dir}/health-status.json" \
    "${failed_args[@]}"

"${app_dir}/.venv/bin/python" \
    "${app_dir}/scripts/health_recovery_state.py" success \
    --state-file "${JIAOTANG_HEALTH_RECOVERY_STATE:-${data_dir}/health-recovery-state.json}" \
    --failure-threshold "${JIAOTANG_HEALTH_FAILURE_THRESHOLD:-2}" \
    --max-restarts "${JIAOTANG_HEALTH_MAX_RESTARTS:-3}" \
    --restart-window-seconds "${JIAOTANG_HEALTH_RESTART_WINDOW_SECONDS:-1800}" \
    --circuit-cooldown-seconds "${JIAOTANG_HEALTH_CIRCUIT_COOLDOWN_SECONDS:-3600}" \
    >/dev/null

"${app_dir}/.venv/bin/python" \
    "${app_dir}/scripts/report_systemd_failure.py" \
    --unit jiaotang-kb.service \
    --clear \
    >/dev/null

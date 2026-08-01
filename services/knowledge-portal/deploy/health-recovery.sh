#!/usr/bin/env bash
set -euo pipefail

app_dir="${JIAOTANG_APP_DIR:-/opt/jiaotang-kb-runtime/current}"
data_dir="${JIAOTANG_DATA_DIR:-/var/lib/jiaotang-kb}"
state_file="${JIAOTANG_HEALTH_RECOVERY_STATE:-${data_dir}/health-recovery-state.json}"
failed_unit="${1:-jiaotang-kb-health.service}"
state_json="$(
    "${app_dir}/.venv/bin/python" \
        "${app_dir}/scripts/health_recovery_state.py" failure \
        --state-file "${state_file}" \
        --failure-threshold "${JIAOTANG_HEALTH_FAILURE_THRESHOLD:-2}" \
        --max-restarts "${JIAOTANG_HEALTH_MAX_RESTARTS:-3}" \
        --restart-window-seconds "${JIAOTANG_HEALTH_RESTART_WINDOW_SECONDS:-1800}" \
        --circuit-cooldown-seconds "${JIAOTANG_HEALTH_CIRCUIT_COOLDOWN_SECONDS:-3600}"
)"
action="$(
    printf '%s' "${state_json}" \
        | "${app_dir}/.venv/bin/python" -c \
            'import json,sys; print(json.load(sys.stdin)["action"])'
)"
logger -t jiaotang-kb-health-recovery \
    "unit=${failed_unit} action=${action} state_file=${state_file}"

if [[ "${action}" == "restart" ]]; then
    systemctl restart jiaotang-kb.service
    systemctl is-active --quiet jiaotang-kb.service
fi

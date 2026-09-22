#!/usr/bin/env bash
set -euo pipefail

app_dir="${JIAOTANG_APP_DIR:-/opt/jiaotang-kb-runtime/current}"
data_dir="${JIAOTANG_DATA_DIR:-/var/lib/jiaotang-kb}"
state_file="${JIAOTANG_HEALTH_RECOVERY_STATE:-${data_dir}/health-recovery-state.json}"
failed_unit="${1:-jiaotang-kb-health.service}"
event=failure
# 容量、证书或索引巡检告警仍由 OnFailure 上报；不要重启可用服务并打断下载。
# 只有服务确实不可用时，才进入原有的连续失败计数和有上限的恢复流程。
if systemctl is-active --quiet jiaotang-kb.service; then
    if ready_json="$(curl --fail --silent --show-error --max-time 10 \
        "${JIAOTANG_READY_URL:-http://127.0.0.1:8100/readyz}")" \
        && printf '%s' "${ready_json}" | "${app_dir}/.venv/bin/python" -c \
            'import json,sys; p=json.load(sys.stdin); sys.exit(0 if p.get("status") == "ok" and p.get("checks", {}).get("portal_database") is True and p.get("checks", {}).get("knowledge_index") is True else 1)'; then
        event=success
    fi
fi
state_json="$(
    "${app_dir}/.venv/bin/python" \
        "${app_dir}/scripts/health_recovery_state.py" "${event}" \
        --state-file "${state_file}" \
        --failure-threshold "${JIAOTANG_HEALTH_FAILURE_THRESHOLD:-2}" \
        --max-restarts "${JIAOTANG_HEALTH_MAX_RESTARTS:-3}" \
        --restart-window-seconds "${JIAOTANG_HEALTH_RESTART_WINDOW_SECONDS:-1800}" \
        --circuit-cooldown-seconds "${JIAOTANG_HEALTH_CIRCUIT_COOLDOWN_SECONDS:-3600}"
)"
if [[ "${event}" == "success" ]]; then
    logger -t jiaotang-kb-health-recovery \
        "unit=${failed_unit} action=alert_only reason=portal_ready"
    exit 0
fi
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
